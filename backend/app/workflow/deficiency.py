"""Deficiency rounds, per-item response traceability and audited officer review."""
from dataclasses import replace
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID, NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.platform.registry import port
from app.workflow.commands import Command, GuardFacts, WorkflowConflict, WorkflowValidationFailed
from app.workflow.models import CaseState, Deficiency, DeficiencyItem, Ruleset
from contracts.errors import NotFound
from contracts.ports import ClockPort, LedgerPort, NotesPort, RulesetPort
from contracts.types import EventIn


def config(session, ruleset_key: str) -> dict:
    metadata = session.scalar(select(Ruleset.source_metadata).where(Ruleset.key == ruleset_key))
    result = (metadata or {}).get("deficiency")
    if result is None:
        raise WorkflowValidationFailed("DEFICIENCY_CONFIG_UNAVAILABLE")
    return result


def active(session, case_id: UUID) -> Deficiency | None:
    return session.scalar(select(Deficiency).where(Deficiency.application_id == case_id,
        Deficiency.status != "CLOSED").order_by(Deficiency.round_no))


def items(session, round_id: UUID) -> list[DeficiencyItem]:
    return list(session.scalars(select(DeficiencyItem).where(DeficiencyItem.deficiency_id == round_id)
                               .order_by(DeficiencyItem.item_key, DeficiencyItem.id)))


def read_facts(uow, case, command: Command, facts: GuardFacts) -> GuardFacts:
    """Persisted P1 facts override injected guesses; no mutation during UI previews."""
    metadata = uow.session.scalar(select(Ruleset.source_metadata).where(Ruleset.key == case.ruleset_key))
    settings = (metadata or {}).get("deficiency")
    if settings is None:
        if command.action in {"record_deficiency", "submit_compliance", "start_rescrutiny"}:
            raise WorkflowValidationFailed("DEFICIENCY_CONFIG_UNAVAILABLE")
        return facts
    outstanding = uow.session.scalar(select(func.count()).select_from(DeficiencyItem).join(Deficiency).where(
        Deficiency.application_id == case.application_id, DeficiencyItem.state != "ACCEPTED"))
    current = active(uow.session, case.application_id)
    facts = replace(facts, open_item_count=outstanding, reason_codes=frozenset(settings["reason_codes"]),
                    item_refs=frozenset(), response_refs=frozenset(),
                    deficiency_status=current.status if current else "CLOSED")
    if command.action == "record_deficiency":
        if current is not None:
            raise WorkflowValidationFailed("DEFICIENCY_ROUND_UNRESOLVED")
        keys = command.payload.item_keys
        if not keys:
            raise WorkflowValidationFailed("DEFICIENCY_ITEMS_REQUIRED")
        if len(keys) != len(set(keys)):
            raise WorkflowValidationFailed("DEFICIENCY_ITEMS_DUPLICATED")
        if not set(keys) <= set(settings["item_keys"]):
            raise WorkflowValidationFailed("DEFICIENCY_ITEM_INVALID")
    if command.action in {"submit_compliance", "start_rescrutiny"}:
        if current is None or current.status != "OPEN":
            raise WorkflowValidationFailed("NO_OPEN_DEFICIENCY")
        expected = {item.id for item in items(uow.session, current.id) if item.state == "OPEN"}
        supplied = [response.item_id for response in command.payload.responses]
        if not expected or len(supplied) != len(set(supplied)) or set(supplied) != expected:
            raise WorkflowValidationFailed("DEFICIENCY_RESPONSES_INCOMPLETE")
        facts = replace(facts, response_refs=frozenset(r.response_ref for r in command.payload.responses))
    return facts


def apply(uow, case, command: Command, now: datetime, common: dict) -> list[EventIn]:
    """Called after guards inside the engine's transaction, before timer execution."""
    if command.action == "record_deficiency":
        number = (uow.session.scalar(select(func.max(Deficiency.round_no)).where(
            Deficiency.application_id == case.application_id)) or 0) + 1
        round_id = uuid5(NAMESPACE_URL, f"sih26262:deficiency:{case.application_id}:{number}")
        row = Deficiency(id=round_id, application_id=case.application_id, round_no=number,
                         status="OPEN", opened_at=now, closed_at=None)
        uow.session.add(row)
        uow.session.flush()
        values = []
        for key in sorted(command.payload.item_keys):
            item_id = uuid5(NAMESPACE_URL, f"sih26262:deficiency-item:{round_id}:{key}")
            uow.session.add(DeficiencyItem(id=item_id, deficiency_id=round_id, item_key=key, state="OPEN"))
            values.append({"item_id": item_id, "item_key": key})
        uow.session.flush()
        return [EventIn(event_type="wf.deficiency_recorded", payload={"application_id": case.application_id,
            "deficiency_id": round_id, "round_no": number, "items": values}, **common)]
    if command.action in {"submit_compliance", "start_rescrutiny"}:
        row = active(uow.session, case.application_id)
        lookup = {item.id: item for item in items(uow.session, row.id)}
        events = []
        for response in sorted(command.payload.responses, key=lambda r: str(r.item_id)):
            item = lookup[response.item_id]
            item.state, item.response_ref = "RESPONDED", response.response_ref
            events.append(EventIn(event_type="wf.deficiency_item_responded", payload={
                "application_id": case.application_id, "deficiency_id": row.id,
                "item_id": item.id, "response_ref": response.response_ref}, **common))
        row.status = "RESPONDED"
        uow.session.flush()
        events.append(EventIn(event_type="wf.compliance_submitted", payload={
            "application_id": case.application_id, "deficiency_id": row.id, "round_no": row.round_no}, **common))
        return events
    return []


def close(uow, row: Deficiency, common: dict, now: datetime) -> int:
    if row.status != "RESPONDED" or any(item.state != "ACCEPTED" for item in items(uow.session, row.id)):
        raise WorkflowValidationFailed("OPEN_DEFICIENCY_ITEMS")
    if now < row.opened_at:
        raise WorkflowConflict("CLOCK_BEFORE_DEFICIENCY_ENTRY")
    row.status, row.closed_at = "CLOSED", now
    uow.session.flush()
    return port(LedgerPort).append(uow, EventIn(event_type="wf.deficiency_closed", payload={
        "application_id": row.application_id, "deficiency_id": row.id, "round_no": row.round_no}, **common))


class Output(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ItemOut(Output):
    id: UUID
    item_key: str
    state: Literal["OPEN", "RESPONDED", "ACCEPTED", "REJECTED"]
    response_ref: UUID | None
    decided_by: UUID | None
    decision_reason_code: str | None


class RoundOut(Output):
    id: UUID
    round_no: int
    status: Literal["OPEN", "RESPONDED", "CLOSED"]
    opened_at: datetime
    closed_at: datetime | None
    items: list[ItemOut]


class WindowOut(BaseModel):
    rule_id: str
    value: int
    unit: str
    source_status: Literal["DEMO_ASSUMPTION"] = "DEMO_ASSUMPTION"
    assumption_code: str


class DeficienciesOut(BaseModel):
    case_id: UUID
    version: int
    ruleset_key: str
    response_window: WindowOut
    rounds: list[RoundOut]


class ItemDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: UUID
    state: Literal["ACCEPTED", "REJECTED"]
    reason_code: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]*$")]


class ReviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: Annotated[int, Field(strict=True, ge=1)]
    decisions: list[ItemDecision] = Field(min_length=1)
    note: str | None = None


def read(session, case_id: UUID, principal) -> DeficienciesOut:
    from app.workflow.case_service import projection, scope, state_for
    scope(session, case_id, principal)
    case = state_for(session, projection(session, case_id))
    settings = config(session, case.ruleset_key)
    rule = port(RulesetPort).get(case.ruleset_key).deadline_rules[settings["response_rule_id"]]
    duration = rule["duration"] if isinstance(rule, dict) else rule.duration
    duration = duration if isinstance(duration, dict) else {"value": duration.value, "unit": duration.unit}
    rows = session.scalars(select(Deficiency).where(Deficiency.application_id == case_id).order_by(Deficiency.round_no))
    return DeficienciesOut(case_id=case_id, version=case.version, ruleset_key=case.ruleset_key,
        response_window=WindowOut(rule_id=settings["response_rule_id"], value=duration["value"], unit=duration["unit"],
            assumption_code=settings["assumption_code"]),
        rounds=[RoundOut(id=row.id, round_no=row.round_no, status=row.status, opened_at=row.opened_at,
            closed_at=row.closed_at, items=[ItemOut.model_validate(item) for item in items(session, row.id)]) for row in rows])


def review(uow, case_id: UUID, round_id: UUID, body: ReviewIn) -> DeficienciesOut:
    from app.workflow.case_service import projection, scope
    scope(uow.session, case_id, uow.principal, "case.record_deficiency")
    projection(uow.session, case_id, lock=True)  # same application -> case lock order as action API
    case = uow.session.get(CaseState, case_id, with_for_update=True, populate_existing=True)
    if case is None:
        raise NotFound("case state not found")
    if case.version != body.expected_version:
        raise WorkflowConflict("VERSION_CONFLICT")
    if case.current_stage != "RESCRUTINY":
        raise WorkflowValidationFailed("INVALID_REVIEW_STAGE")
    row = uow.session.get(Deficiency, round_id)
    if row is None or row.application_id != case_id:
        raise NotFound("deficiency not found")
    if row.status != "RESPONDED":
        raise WorkflowValidationFailed("DEFICIENCY_NOT_RESPONDED")
    settings = config(uow.session, case.ruleset_key)
    lookup = {item.id: item for item in items(uow.session, round_id)}
    ids = [decision.item_id for decision in body.decisions]
    if len(ids) != len(set(ids)):
        raise WorkflowValidationFailed("DEFICIENCY_ITEMS_DUPLICATED")
    for decision in body.decisions:
        if decision.item_id not in lookup or lookup[decision.item_id].state == "OPEN":
            raise WorkflowValidationFailed("DEFICIENCY_ITEM_NOT_RESPONDED")
        if decision.reason_code not in settings["reason_codes"]:
            raise WorkflowValidationFailed("REASON_CODE_INVALID")
    note_ref, note_hash = port(NotesPort).create(uow, body.note) if body.note else (None, None)
    common = dict(aggregate_type="application", aggregate_id=case_id, ruleset_rev=case.ruleset_key,
                  note_ref=note_ref, note_hash=note_hash)
    for decision in sorted(body.decisions, key=lambda d: str(d.item_id)):
        item = lookup[decision.item_id]
        item.state, item.decided_by, item.decision_reason_code = decision.state, uow.principal.user_id, decision.reason_code
        uow.session.flush()
        port(LedgerPort).append(uow, EventIn(event_type="wf.deficiency_item_decided", reason_code=decision.reason_code,
            payload={"application_id": case_id, "deficiency_id": round_id, "item_id": item.id,
                     "state": item.state, "decided_by": item.decided_by}, **common))
    case.version += 1
    uow.session.flush()
    if all(item.state == "ACCEPTED" for item in lookup.values()):
        close(uow, row, common, port(ClockPort).now())
    return read(uow.session, case_id, uow.principal)
