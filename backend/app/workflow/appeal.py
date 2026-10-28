"""The appeal against a Letter of Deficiency (APH 2024-27 cl. 1.11, p.25; cl. 2.24, p.45).

An LoD opens the APPEAL_7D window (routes.yaml appeal block). Within it the institution may appeal once; the case
then goes to the Standing Appellate Committee (SAC), which recommends, does not recommend, or refers the case back
for Scrutiny or EVC; the Council's decision on it (LoA/EoA, or a Letter of Rejection with a speaking order) is
final. If the window lapses unappealed the LoD stands and the case is rejected.

The system records these human decisions; it never makes one. Every step is a YAML transition applied by the
engine, which calls apply() inside the same transaction; this module keeps the appeal record and its events.
"""
from dataclasses import replace
from datetime import datetime
import logging
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.platform.db import new_session, unit_of_work
from app.platform.registry import port
from app.workflow.commands import Command, GuardFacts, WorkflowConflict, WorkflowValidationFailed
from app.workflow.models import Appeal, CaseState, Ruleset
from app.workflow.published import deadlines
from contracts.enums import Role
from contracts.ports import ClockPort, UnitOfWork
from contracts.types import EventIn, Principal

log = logging.getLogger("workflow-appeal")
IST = ZoneInfo("Asia/Kolkata")
SYSTEM = Principal(UUID(int=0), Role.SYSTEM)
RECOMMENDATIONS = {"sac_recommend": "RECOMMEND", "sac_not_recommend": "NOT_RECOMMEND",
                   "sac_refer_scrutiny": "REFER_SCRUTINY", "sac_refer_evc": "REFER_EVC"}
AFTER_RECOMMENDATION = {"RECOMMEND": "RECOMMENDED", "NOT_RECOMMEND": "NOT_RECOMMENDED",
                        "REFER_SCRUTINY": "REFERRED_BACK", "REFER_EVC": "REFERRED_BACK"}


def appeal_id(application_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"sih26262:wf:appeal:{application_id}")


def config(session: Session, ruleset_key: str) -> dict | None:
    metadata = session.scalar(select(Ruleset.source_metadata).where(Ruleset.key == ruleset_key))
    return (metadata or {}).get("appeal")


def current(session: Session, application_id: UUID) -> Appeal | None:
    return session.scalar(select(Appeal).where(Appeal.application_id == application_id))


def window(session: Session, row: Appeal):
    """The window's clock as the deadlines module keeps it (read-only)."""
    return session.execute(select(deadlines).where(deadlines.c.id == row.window_deadline_id)).mappings().one_or_none()


def _now() -> datetime:
    now = port(ClockPort).now()
    if now.tzinfo is None or now.utcoffset() is None:
        raise WorkflowValidationFailed("CLOCK_MUST_BE_AWARE")
    return now


def read_facts(uow, case, facts: GuardFacts) -> GuardFacts:
    """Appeal status from the appeal record; the window has lapsed once its clock is breached or past due."""
    row = current(uow.session, case.application_id)
    if row is None:
        return replace(facts, appeal_status=None, appeal_window_lapsed=None)
    lapsed = None
    if row.status == "WINDOW_OPEN":
        clock = window(uow.session, row)
        if clock is not None:
            lapsed = clock["status"] == "BREACHED" or _now() > clock["due_at"]
    return replace(facts, appeal_status=row.status, appeal_window_lapsed=lapsed)


def apply(uow: UnitOfWork, case: CaseState, source: str, action: str, command: Command, now: datetime, common: dict, *,
          settings: dict | None, opened: tuple, letter_ref: UUID | None, letter_type: str | None,
          note_ref: UUID | None, note_hash: str | None) -> list[EventIn]:
    """Called by the engine after guards, timers and letter registration, inside the command's transaction."""
    if settings is None:
        return []
    session = uow.session
    payload = {"application_id": case.application_id, "appeal_id": appeal_id(case.application_id)}
    if action == settings["trigger"]:
        if current(session, case.application_id) is not None:
            raise WorkflowConflict("APPEAL_ALREADY_USED")
        deadline = next((d.deadline_id for d in opened if d.rule_id == settings["window"]), None)
        if deadline is None or letter_ref is None:
            raise WorkflowValidationFailed("APPEAL_WINDOW_UNAVAILABLE")
        session.add(Appeal(id=payload["appeal_id"], application_id=case.application_id, status="WINDOW_OPEN",
                           lod_letter_ref=letter_ref, window_rule_id=settings["window"], window_deadline_id=deadline,
                           opened_at=now, hearing_no=0))
        session.flush()
        return [EventIn(event_type="wf.appeal_window_opened", payload={**payload, "lod_letter_ref": letter_ref,
            "deadline_id": deadline, "rule_id": settings["window"], "max_appeals": settings["max_appeals"]}, **common)]
    row = current(session, case.application_id)
    deciding = source == settings["stage"] and letter_type is not None
    if row is None:
        if action in RECOMMENDATIONS or deciding or action in {"file_appeal", "close_appeal_window", "return_to_sac"}:
            raise WorkflowValidationFailed("APPEAL_NOT_FOUND")
        return []
    if action == "file_appeal":
        row.status, row.filed_at, row.filed_by, row.hearing_no = "FILED", now, command.actor.user_id, 1
        row.grounds_note_ref, row.grounds_note_hash = note_ref, note_hash
        session.flush()
        return [EventIn(event_type="wf.appeal_filed", payload={**payload, "filed_by": row.filed_by,
                                                               "deadline_id": row.window_deadline_id}, **common)]
    if action == "close_appeal_window":
        row.status, row.closed_at = "LAPSED", now
        session.flush()
        return [EventIn(event_type="wf.appeal_lapsed", payload={**payload, "deadline_id": row.window_deadline_id},
                        **common)]
    if action in RECOMMENDATIONS:
        recommendation = RECOMMENDATIONS[action]
        row.status, row.recommendation = AFTER_RECOMMENDATION[recommendation], recommendation
        row.recommended_at, row.recommended_by = now, command.actor.user_id
        row.recommendation_report_ref = command.payload.decision_ref
        session.flush()
        return [EventIn(event_type="wf.appeal_recommended", payload={**payload, "hearing_no": row.hearing_no,
            "recommendation": recommendation, "report_ref": row.recommendation_report_ref,
            "recommended_by": row.recommended_by}, **common)]
    if action == "return_to_sac":
        # cl. 1.11(d): the reports made after a referral go before another SAC hearing.
        row.status, row.hearing_no = "FILED", row.hearing_no + 1
        row.recommendation = row.recommended_at = row.recommended_by = row.recommendation_report_ref = None
        session.flush()
        return []
    if deciding:
        if letter_ref is None:
            raise WorkflowValidationFailed("LETTER_DATA_REQUIRED")
        row.status, row.outcome, row.decided_at, row.decided_by = "DECIDED", letter_type, now, command.actor.user_id
        row.decision_letter_ref = letter_ref
        if letter_type == "LOR":
            row.speaking_order_note_ref, row.speaking_order_note_hash = note_ref, note_hash
        session.flush()
        return [EventIn(event_type="wf.appeal_decided", payload={**payload, "outcome": letter_type,
            "letter_ref": letter_ref, "decided_by": row.decided_by,
            "speaking_order_hash": row.speaking_order_note_hash}, **common)]
    return []


# ---- reads ----

class AppealWindowOut(BaseModel):
    rule_id: str
    deadline_id: UUID
    due_date: str | None
    clock_status: str | None
    days_left: int | None
    clause: str | None
    source_status: str | None


class AppealOut(BaseModel):
    id: UUID
    status: Literal["WINDOW_OPEN", "FILED", "RECOMMENDED", "NOT_RECOMMENDED", "REFERRED_BACK", "LAPSED", "DECIDED"]
    max_appeals: int
    opened_at: datetime
    lod_letter_ref: UUID
    window: AppealWindowOut
    filed_at: datetime | None
    filed_by: UUID | None
    grounds_note_hash: str | None
    hearing_no: int
    recommendation: Literal["RECOMMEND", "NOT_RECOMMEND", "REFER_SCRUTINY", "REFER_EVC"] | None
    recommended_at: datetime | None
    recommended_by: UUID | None
    recommendation_report_ref: UUID | None
    outcome: Literal["LOA", "EOA", "LOR"] | None
    decided_at: datetime | None
    decided_by: UUID | None
    decision_letter_ref: UUID | None
    speaking_order_note_hash: str | None
    closed_at: datetime | None
    source: dict | None


class CaseAppealOut(BaseModel):
    case_id: UUID
    appeal: AppealOut | None


def out(session: Session, row: Appeal, settings: dict | None) -> AppealOut:
    clock = window(session, row)
    days_left = None
    if clock is not None and row.status == "WINDOW_OPEN":
        days_left = max(0, (clock["due_date"] - _now().astimezone(IST).date()).days)
    return AppealOut(
        id=row.id, status=row.status, max_appeals=(settings or {}).get("max_appeals", 1), opened_at=row.opened_at,
        lod_letter_ref=row.lod_letter_ref,
        window=AppealWindowOut(rule_id=row.window_rule_id, deadline_id=row.window_deadline_id,
            due_date=clock["due_date"].isoformat() if clock else None, clock_status=clock["status"] if clock else None,
            days_left=days_left, clause=clock["clause"] if clock else None,
            source_status=clock["source_status"] if clock else None),
        filed_at=row.filed_at, filed_by=row.filed_by, grounds_note_hash=row.grounds_note_hash, hearing_no=row.hearing_no,
        recommendation=row.recommendation, recommended_at=row.recommended_at, recommended_by=row.recommended_by,
        recommendation_report_ref=row.recommendation_report_ref, outcome=row.outcome, decided_at=row.decided_at,
        decided_by=row.decided_by, decision_letter_ref=row.decision_letter_ref,
        speaking_order_note_hash=row.speaking_order_note_hash, closed_at=row.closed_at,
        source=(settings or {}).get("source"))


def read(session: Session, case_id: UUID, principal: Principal) -> CaseAppealOut:
    from app.workflow.case_service import projection, scope, state_for
    scope(session, case_id, principal)
    case = state_for(session, projection(session, case_id))
    row = current(session, case_id)
    return CaseAppealOut(case_id=case_id, appeal=out(session, row, config(session, case.ruleset_key)) if row else None)


# ---- the window's expiry (deadlines.yaml APPEAL_7D on_expiry: close_appeal_window) ----

def close_lapsed(limit: int = 50) -> int:
    """Close every appeal window whose clock the deadline worker has marked BREACHED, as SYSTEM, one case per
    transaction. A case that cannot be closed now (e.g. changed meanwhile) is left for the next run."""
    from app.workflow.case_api_models import ActionIn
    from app.workflow.case_service import apply_action

    with new_session() as session:
        due = session.scalars(select(Appeal.application_id).join(deadlines, deadlines.c.id == Appeal.window_deadline_id)
                              .where(Appeal.status == "WINDOW_OPEN", deadlines.c.status == "BREACHED")
                              .order_by(Appeal.opened_at, Appeal.id).limit(limit)).all()
    closed = 0
    for application_id in due:
        try:
            with unit_of_work(SYSTEM) as uow:
                case = uow.session.get(CaseState, application_id)
                apply_action(uow, application_id, ActionIn(action="close_appeal_window", expected_version=case.version))
            closed += 1
        except Exception as exc:  # noqa: BLE001 - one case must not stop the others; retried next run
            log.warning("appeal window of %s not closed: %s", application_id, getattr(exc, "reason_code", type(exc).__name__))
    return closed


class Expiry:
    """DeadlineExpiryPort: the workflow's expiry actions, run by the deadline worker."""

    def run_due(self, limit: int) -> int:
        return close_lapsed(limit)
