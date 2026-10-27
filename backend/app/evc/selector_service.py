"""Read-only snapshot adapter for the SIMULATED authorised selector (stand-in)."""
from datetime import date as DateValue
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.evc.models import AssignmentExpert, EvcRequest
from app.evc.pool import eligibility_snapshot, policy
from app.evc.selector import AssignmentFact, SelectorPolicy, SelectorRequest
from app.platform.registry import port
from contracts.errors import Conflict, NotFound, ValidationFailed
from contracts.ports import CasePort


def selector_request(session: Session, request_id: UUID, *, planning_until: DateValue | None = None) -> SelectorRequest:
    """Caller owns authorization and publication-time rechecks; this creates no reservation."""
    row = session.get(EvcRequest, request_id)
    if row is None:
        raise NotFound("EVC_REQUEST_NOT_FOUND")
    if row.status not in {"QUEUED", "PROPOSED"}:
        raise ValidationFailed("SELECTOR_REQUEST_NOT_SCHEDULABLE")
    if not row.ruleset_key:
        raise Conflict("EVC_REQUEST_METADATA_UNAVAILABLE")
    case = port(CasePort).lookup(session, row.application_id)
    if row.region != case.region or row.institution_ref != case.institution_id:
        raise Conflict("SELECTOR_CASE_REFERENCE_CHANGED")
    rules, _ = policy(row.ruleset_key)
    if row.category not in rules.routes:
        raise ValidationFailed("SELECTOR_CATEGORY_UNKNOWN")
    selected = SelectorPolicy.from_mapping(rules.expert_pool.get("selector"))
    history = tuple(AssignmentFact(row.assignment_id, row.expert_id, row.date, row.slot_part)
                    for row in session.scalars(select(AssignmentExpert).order_by(AssignmentExpert.assignment_id, AssignmentExpert.expert_id)))
    return SelectorRequest(eligibility_snapshot(session, request_id, planning_until=planning_until), row.category, selected, history)
