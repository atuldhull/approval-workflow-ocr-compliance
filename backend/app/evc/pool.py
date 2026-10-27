"""Expert management commands and eligibility snapshot adapter (EVC tables only)."""
from __future__ import annotations

from datetime import date as DateValue
from typing import TYPE_CHECKING
from uuid import UUID, NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.evc.eligibility import AvailabilityFact, EligibilityRequest, ExpertCandidate, ExpertPolicy
from app.evc.models import AssignmentExpert, Availability, Coi, EvcRequest, Expert
from app.platform.registry import port
from contracts.enums import Role
from contracts.errors import Conflict, Forbidden, NotFound
from contracts.ports import AuthzPort, LedgerPort, PersonalDataPort, RulesetPort, UnitOfWork
from contracts.types import EventIn, Principal, ResourceRef, RuleSet

if TYPE_CHECKING:
    from app.evc.pool_api import AvailabilitySet, CoiCreate, ExpertCreate


def authorize(principal: Principal, action: str, *, expert_id: UUID | None = None, region: str | None = None) -> None:
    port(AuthzPort).check(principal, action, ResourceRef("evc_expert", expert_id, region=region))
    if principal.role == Role.RO_OFFICER:
        if not principal.region or (region is not None and principal.region.upper() != region.upper()):
            raise Forbidden("EVC_EXPERT_REGION_FORBIDDEN")


def expert_row(uow: UnitOfWork, expert_id: UUID, action: str) -> Expert:
    authorize(uow.principal, action, expert_id=expert_id)
    expert = uow.session.get(Expert, expert_id, with_for_update=True)
    if expert is None:
        raise NotFound("EVC_EXPERT_NOT_FOUND")
    authorize(uow.principal, action, expert_id=expert.id, region=expert.region)
    return expert


def policy(key: str | None = None) -> tuple[RuleSet, ExpertPolicy]:
    registry = port(RulesetPort)
    key = key or registry.default_key()
    rules = registry.get(key)
    if rules.key != key:
        raise Conflict("EXPERT_POOL_RULESET_PIN_MISMATCH")
    return rules, ExpertPolicy.from_mapping(rules.expert_pool)


def register_expert(uow: UnitOfWork, body: ExpertCreate) -> Expert:
    authorize(uow.principal, "evc.expert.register", region=body.region)
    expert_id = uuid5(NAMESPACE_URL, f"sih26262:evc:expert:user:{body.user_ref}")
    created = uow.session.scalar(insert(Expert).values(id=expert_id, user_ref=body.user_ref, region=body.region,
        # Concurrent inserts can collide on either the derived PK or user_ref.
        expertise_tags=body.expertise_tags, active=body.active).on_conflict_do_nothing().returning(Expert.id))
    if created is None:
        raise Conflict("EVC_EXPERT_ALREADY_REGISTERED")
    row = uow.session.get(Expert, expert_id)
    if body.personal_details is not None:
        row.personal_ref = port(PersonalDataPort).store(uow, body.personal_details.model_dump(exclude_none=True), "EVC_EXPERT_CONTACT")
    uow.session.flush()
    port(LedgerPort).append(uow, EventIn(aggregate_type="evc_expert", aggregate_id=row.id,
        event_type="evc.expert_registered", personal_ref=row.personal_ref, payload=dict(expert_id=row.id,
            user_ref=row.user_ref, region=row.region, expertise_tags=row.expertise_tags, active=row.active, personal_ref=row.personal_ref)))
    return row


def set_availability(uow: UnitOfWork, expert_id: UUID, body: AvailabilitySet) -> dict:
    expert_row(uow, expert_id, "evc.availability.set")
    rules, _ = policy()
    changes = []
    rows = sorted(body.items, key=lambda row: (row.date, row.slot_part))
    for item in rows:
        key = (expert_id, item.date, item.slot_part)
        old = uow.session.get(Availability, key)
        if old is None:
            uow.session.add(Availability(expert_id=expert_id, date=item.date, slot_part=item.slot_part, available=item.available))
        elif old.available != item.available:
            old.available = item.available
        else:
            continue
        changes.append(item.model_dump(mode="json"))
    if changes:
        uow.session.flush()
        port(LedgerPort).append(uow, EventIn(aggregate_type="evc_expert", aggregate_id=expert_id,
            event_type="evc.availability_set", ruleset_rev=rules.key, payload=dict(expert_id=expert_id, changes=changes)))
    return dict(expert_id=expert_id, changed_count=len(changes), items=[r.model_dump(mode="json") for r in rows],
                ruleset_key=rules.key, source_status="DEMO_ASSUMPTION", assumption_code="EXPERT_POLICY_UNCONFIRMED")


def record_coi(uow: UnitOfWork, body: CoiCreate) -> dict:
    expert_row(uow, body.expert_id, "evc.coi.record")
    rules, _ = policy()
    values = body.model_dump()
    key = (body.expert_id, body.institution_ref, body.reason_code, body.source)
    created = uow.session.get(Coi, key) is None
    if created:
        uow.session.add(Coi(**values))
        try:
            uow.session.flush()
        except IntegrityError as exc:
            if getattr(getattr(exc.orig, "diag", None), "constraint_name", None) == "coi_institution_ref_fkey":
                raise NotFound("EVC_INSTITUTION_REFERENCE_NOT_FOUND") from None
            raise
        port(LedgerPort).append(uow, EventIn(aggregate_type="evc_expert", aggregate_id=body.expert_id,
            event_type="evc.coi_recorded", ruleset_rev=rules.key, payload=values))
    return dict(**values, created=created, ruleset_key=rules.key,
                source_status="DEMO_ASSUMPTION", assumption_code="EXPERT_POLICY_UNCONFIRMED")


def eligibility_snapshot(session: Session, request_id: UUID, *, planning_until: DateValue | None = None) -> EligibilityRequest:
    """Caller owns auth and reservation rechecks; materialize immutable inputs for the core."""
    request = session.get(EvcRequest, request_id)
    if request is None:
        raise NotFound("EVC_REQUEST_NOT_FOUND")
    if not request.ruleset_key:
        raise Conflict("EVC_REQUEST_METADATA_UNAVAILABLE")
    _, selected = policy(request.ruleset_key)
    experts = tuple(ExpertCandidate(row.id, row.user_ref, row.region, tuple(sorted(row.expertise_tags)), row.active)
                    for row in session.scalars(select(Expert).order_by(Expert.id)))
    end = planning_until or request.due_by
    availability = tuple(AvailabilityFact(row.expert_id, row.date, row.slot_part, row.available)
                         for row in session.scalars(select(Availability).where(Availability.date.between(request.earliest_date, end))))
    conflicts = frozenset((row.expert_id, row.institution_ref) for row in session.scalars(select(Coi).where(Coi.institution_ref == request.institution_ref)))
    reservations = frozenset((row.expert_id, row.date, row.slot_part) for row in session.scalars(select(AssignmentExpert)
                             .where(AssignmentExpert.date.between(request.earliest_date, end))))
    return EligibilityRequest(request.id, request.institution_ref, request.region, request.ruleset_key,
                              request.earliest_date, request.due_by, selected, experts, availability, conflicts, reservations, planning_until)
