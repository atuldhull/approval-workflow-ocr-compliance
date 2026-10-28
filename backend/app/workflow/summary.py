"""The electronic case summary: one read of everything recorded on a case, for review and printing.

Scoped exactly like the case detail (GET /cases/{id}). Free text never appears: notes, committee reports, appeal
grounds and speaking orders are shown by fingerprint (hash) only. Deadlines, obligations and letters belong to the
deadlines and compliance modules; they are read here, never written, and withheld when the caller may not read them.
"""
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.intake.models import Application
from app.platform.registry import port
from app.workflow import appeal as appeals
from app.workflow.case_api_models import RouteStageOut, VisitOut
from app.workflow.case_service import projection, scope, state_for
from app.workflow.committee import case_committees
from app.workflow.deficiency import items as deficiency_items
from app.workflow.models import Deficiency, ReportVersion, Ruleset, RouteDefinition
from app.workflow.published import LIVE_DEADLINES, deadlines, letters, obligations
from app.workflow.storage import visits
from contracts.enums import ApplicationStatus, Stage
from contracts.errors import Forbidden
from contracts.ports import AuthzPort, ClockPort, RulesetPort
from contracts.types import Principal, ResourceRef


class SummaryItemOut(BaseModel):
    item_key: str
    state: str
    decision_reason_code: str | None


class SummaryRoundOut(BaseModel):
    round_no: int
    status: str
    opened_at: datetime
    closed_at: datetime | None
    closure_kind: str | None
    items: list[SummaryItemOut]


class SummaryReportOut(BaseModel):
    id: UUID
    version_no: int
    created_at: datetime
    author_user_ref: UUID
    content_note_hash: str


class SummaryCommitteeOut(BaseModel):
    id: UUID
    ordinal: int
    type: str
    status: str
    member_count: int
    reports: list[SummaryReportOut]


class SummaryVisitOut(BaseModel):
    date: date
    slot_part: str
    panel_size: int
    simulation_status: str


class SummaryEvcOut(BaseModel):
    id: UUID
    status: str
    requested_at: datetime
    due_by: date
    closed_at: datetime | None
    rule_id: str | None
    duration_days: int | None
    source_status: Literal["DEMO_ASSUMPTION"] = "DEMO_ASSUMPTION"
    visit: SummaryVisitOut | None


class SummaryDeadlineOut(BaseModel):
    id: UUID
    rule_id: str
    status: str
    due_date: date
    clock_kind: str
    clock_owner: str
    clause: str | None
    source_status: str


class SummaryObligationOut(BaseModel):
    id: UUID
    kind: str
    status: str
    due_date: date | None
    rule_id: str | None
    source_clause: str | None
    source_status: str


class SummaryLetterOut(BaseModel):
    id: UUID
    letter_type: str
    academic_year: str
    issue_date: date
    issue_date_source: str
    valid_until: date | None


class CaseSummaryOut(BaseModel):
    case_id: UUID
    generated_at: datetime
    institution_id: UUID
    region: str
    academic_year: str | None
    route_id: str
    route_label: str | None
    clause_citation: dict | None
    ruleset_key: str | None
    status: ApplicationStatus
    stage: Stage | None
    version: int
    submitted_at: datetime | None
    route: list[RouteStageOut]
    stage_visits: list[VisitOut]
    deficiencies: list[SummaryRoundOut]
    committees: list[SummaryCommitteeOut]
    evc_requests: list[SummaryEvcOut]
    open_deadlines: list[SummaryDeadlineOut] | None
    obligations: list[SummaryObligationOut] | None
    letters: list[SummaryLetterOut] | None
    appeal: appeals.AppealOut | None
    # sections the caller's role may not read (deadline.read / compliance.read), shown as withheld, never empty
    withheld: list[Literal["open_deadlines", "obligations", "letters"]]
    assumption_status: Literal["DEMO_ASSUMPTION"] | None


def _may(principal: Principal, action: str, resource) -> bool:
    try:
        port(AuthzPort).check(principal, action, resource)
        return True
    except Forbidden:
        return False


def _committees(session: Session, case_id: UUID, principal: Principal) -> list[SummaryCommitteeOut]:
    result = []
    for row in case_committees(session, case_id, principal):
        reports = session.scalars(select(ReportVersion).where(ReportVersion.committee_id == row.id)
                                  .order_by(ReportVersion.version_no))
        result.append(SummaryCommitteeOut(id=row.id, ordinal=row.ordinal, type=row.type, status=row.status,
            member_count=len(row.members), reports=[SummaryReportOut(id=r.id, version_no=r.version_no,
                created_at=r.created_at, author_user_ref=r.author_user_ref, content_note_hash=r.content_note_hash)
                for r in reports]))
    return result


def _evc(session: Session, case_id: UUID, principal: Principal) -> list[SummaryEvcOut]:
    from app.evc.reads import case_evc
    requests = case_evc(session, principal, case_id)["requests"]
    return [SummaryEvcOut(id=r["id"], status=r["status"], requested_at=r["requested_at"], due_by=r["due_by"],
        closed_at=r["closed_at"], rule_id=r["rule_id"], duration_days=r["duration_days"],
        visit=SummaryVisitOut(date=r["visit"]["date"], slot_part=r["visit"]["slot_part"],
            panel_size=len(r["visit"]["expert_ids"]), simulation_status=r["visit"]["simulation_status"])
        if r["visit"] else None) for r in sorted(requests, key=lambda r: (r["requested_at"], str(r["id"])))]


def read(session: Session, case_id: UUID, principal: Principal) -> CaseSummaryOut:
    case, _ = scope(session, case_id, principal)
    row = state_for(session, projection(session, case_id))
    app = session.get(Application, case_id)
    route = session.scalar(select(RouteDefinition).where(RouteDefinition.ruleset_key == row.ruleset_key,
                                                         RouteDefinition.route_id == row.route_id))
    try:
        label = port(RulesetPort).route_for(row.route_id, row.ruleset_key).label
    except Exception:  # noqa: BLE001 - a ruleset no longer on disk still has its pinned route
        label = None
    history = session.execute(select(visits).where(visits.c.application_id == case_id)
                              .order_by(visits.c.entered_at, visits.c.id)).mappings().all()
    rounds = []
    for d in session.scalars(select(Deficiency).where(Deficiency.application_id == case_id).order_by(Deficiency.round_no)):
        rounds.append(SummaryRoundOut(round_no=d.round_no, status=d.status, opened_at=d.opened_at, closed_at=d.closed_at,
            closure_kind=d.closure_kind, items=[SummaryItemOut(item_key=i.item_key, state=i.state,
                decision_reason_code=i.decision_reason_code) for i in deficiency_items(session, d.id)]))
    withheld = []
    open_deadlines = None
    if _may(principal, "deadline.read", ResourceRef("deadline", case_id, case.institution_id, case.region)):
        open_deadlines = [SummaryDeadlineOut(**r) for r in session.execute(
            select(deadlines.c.id, deadlines.c.rule_id, deadlines.c.status, deadlines.c.due_date, deadlines.c.clock_kind,
                   deadlines.c.clock_owner, deadlines.c.clause, deadlines.c.source_status)
            .where(deadlines.c.subject_type == "application", deadlines.c.subject_id == case_id,
                   deadlines.c.status.in_(LIVE_DEADLINES)).order_by(deadlines.c.due_date, deadlines.c.id)).mappings()]
    else:
        withheld.append("open_deadlines")
    obligation_rows = letter_rows = None
    if _may(principal, "compliance.read", ResourceRef("compliance", owner_institution_id=case.institution_id, region=case.region)):
        obligation_rows = [SummaryObligationOut(**r) for r in session.execute(
            select(obligations.c.id, obligations.c.kind, obligations.c.status, obligations.c.due_date,
                   obligations.c.rule_id, obligations.c.source_clause, obligations.c.source_status)
            .where(obligations.c.application_id == case_id)
            .order_by(obligations.c.due_date.nulls_last(), obligations.c.id)).mappings()]
        letter_rows = [SummaryLetterOut(**r) for r in session.execute(
            select(letters.c.id, letters.c.letter_type, letters.c.academic_year, letters.c.issue_date,
                   letters.c.issue_date_source, letters.c.valid_until)
            .where(letters.c.application_id == case_id)
            .order_by(letters.c.issue_date, letters.c.registered_at, letters.c.id)).mappings()]
    else:
        withheld += ["obligations", "letters"]
    appeal_row = appeals.current(session, case_id)
    metadata = session.scalar(select(Ruleset.source_metadata).where(Ruleset.key == row.ruleset_key)) or {}
    source = metadata.get("workflow_source") or {}
    draft = row.status == ApplicationStatus.DRAFT
    return CaseSummaryOut(
        case_id=case_id, generated_at=port(ClockPort).now(), institution_id=case.institution_id, region=case.region,
        academic_year=app.academic_year if app else None, route_id=row.route_id, route_label=label,
        clause_citation=route.clause_citation if route else None, ruleset_key=None if draft else row.ruleset_key,
        status=row.status, stage=row.current_stage, version=row.version,
        submitted_at=app.submitted_at if app else None, route=route.stage_list if route else [],
        stage_visits=history, deficiencies=rounds, committees=_committees(session, case_id, principal),
        evc_requests=_evc(session, case_id, principal), open_deadlines=open_deadlines, obligations=obligation_rows,
        letters=letter_rows, appeal=appeals.out(session, appeal_row, metadata.get("appeal")) if appeal_row else None,
        withheld=withheld, assumption_status="DEMO_ASSUMPTION" if source.get("status") == "demo_assumption" else None)
