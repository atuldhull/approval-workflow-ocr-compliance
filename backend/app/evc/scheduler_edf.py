"""Earliest-Deadline-First baseline; SIMULATED authorised selector (stand-in)."""
from collections import Counter
from dataclasses import dataclass, replace
from datetime import date
from uuid import UUID, NAMESPACE_URL, uuid5

from sqlalchemy import select, text

from app.evc.metrics import evaluate_schedule
from app.evc.models import Assignment, EvcRequest, Expert, ScheduleRun, Slot
from app.evc.pool import policy
from app.evc.scheduling import (Allocation, SchedulingPlan, SchedulingProblem, SchedulingRequest, SchedulingSlot,
                                earliest_date, logical_date, selector_at)
from app.evc.selector import select_panel
from app.evc.selector_service import selector_request
from app.platform.db import unit_of_work
from app.platform.registry import port
from contracts.enums import Role
from contracts.errors import Conflict, Forbidden, ValidationFailed
from contracts.ports import AuthzPort, CasePort, ClockPort, LedgerPort, UnitOfWork
from contracts.types import EventIn, Principal, ResourceRef

SCHEDULING_LOCK = 26262035


def plan_edf(problem: SchedulingProblem) -> SchedulingPlan:
    """Pure greedy baseline, independent of persistence and shared metric implementation."""
    baseline = evaluate_schedule(problem, ())
    if baseline.metrics.hard_constraint_violations:
        raise ValidationFailed("SCHEDULER_BASELINE_INVALID")
    occupancy = Counter(allocation.slot_id for allocation in problem.existing)
    planned = []
    unscheduled = []
    for request in problem.ordered_requests:
        snapshot = selector_at(problem, request, tuple(planned))
        for slot in problem.ordered_slots:
            if slot.date < earliest_date(problem, request) or occupancy[slot.id] >= slot.capacity:
                continue
            if slot.slot_part not in snapshot.eligibility.policy.slot_parts:
                continue
            result = select_panel(snapshot, slot.date, slot.slot_part)
            if result.status != "SELECTED":
                continue
            planned.append(Allocation(request.id, slot.id, result.panel))
            occupancy[slot.id] += 1
            break
        else:
            unscheduled.append(request.id)
    result = evaluate_schedule(problem, tuple(planned))
    if result.metrics.hard_constraint_violations:
        raise ValidationFailed("SCHEDULER_PLAN_INVALID")
    return SchedulingPlan("EDF", tuple(planned), tuple(unscheduled), result.metrics, problem.fingerprint)


@dataclass(frozen=True)
class ScheduleCommand:
    run_id: UUID
    horizon_start: date
    horizon_end: date
    region: str | None = None


@dataclass(frozen=True)
class ProposedSchedule:
    run_id: UUID
    plan: SchedulingPlan
    assignment_ids: tuple[UUID, ...]
    status: str = "PROPOSED"


def _scheduler_policy(raw: dict) -> bool:
    if (not isinstance(raw, dict) or set(raw) != {"capacity_unit", "allow_late", "source_status", "assumption_code"}
        or raw["capacity_unit"] != "PANELS" or type(raw["allow_late"]) is not bool
        or raw["source_status"] != "DEMO_ASSUMPTION" or raw["assumption_code"] != "EDF_PLANNING_UNCONFIRMED"):
        raise ValidationFailed("SCHEDULER_POLICY_UNAVAILABLE")
    return raw["allow_late"]


def handle(uow: UnitOfWork, command: ScheduleCommand) -> ProposedSchedule:
    """Auth, lock, snapshot, plan, validate and persist inside the caller's transaction."""
    port(AuthzPort).check(uow.principal, "evc.schedule.propose", ResourceRef("evc_schedule_run", command.run_id, region=command.region))
    scope = command.region
    if uow.principal.role == Role.RO_OFFICER:
        if not uow.principal.region or (scope is not None and scope.upper() != uow.principal.region.upper()):
            raise Forbidden("SCHEDULE_REGION_FORBIDDEN")
        scope = uow.principal.region
    if command.horizon_end < command.horizon_start:
        raise ValidationFailed("SCHEDULER_HORIZON_INVALID")
    now = port(ClockPort).now()
    start = max(command.horizon_start, logical_date(now))
    if command.horizon_end < start:
        raise ValidationFailed("SCHEDULER_HORIZON_BEFORE_CLOCK")
    session = uow.session
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": SCHEDULING_LOCK})
    if session.get(ScheduleRun, command.run_id) is not None:
        raise Conflict("SCHEDULE_RUN_ALREADY_EXISTS")
    queued = session.scalars(select(EvcRequest).where(EvcRequest.status == "QUEUED")
                             .order_by(EvcRequest.due_by, EvcRequest.requested_at, EvcRequest.id).with_for_update()).all()
    selected = []
    for row in queued:
        case = port(CasePort).lookup(session, row.application_id)
        if scope is not None and case.region.upper() != scope.upper():
            continue
        port(AuthzPort).check(uow.principal, "evc.schedule.propose", ResourceRef("application", case.application_id,
            case.institution_id, case.region))
        if row.region != case.region or row.institution_ref != case.institution_id:
            raise Conflict("SCHEDULE_CASE_REFERENCE_CHANGED")
        selected.append(row)
    selected_ids = [row.id for row in selected]
    if selected_ids and session.scalar(select(Assignment.id).where(Assignment.evc_request_id.in_(selected_ids)).limit(1)):
        raise Conflict("SCHEDULE_REQUEST_ALREADY_ASSIGNED")
    # Slot -> expert order also cooperates with projection FK/slot locks and pool commands.
    slots = session.scalars(select(Slot).where(Slot.date.between(start, command.horizon_end))
                            .order_by(Slot.id).with_for_update()).all()
    locked_experts = {expert.id for expert in session.scalars(select(Expert).order_by(Expert.id).with_for_update())}
    requests = []
    for row in selected:
        if not row.ruleset_key:
            raise Conflict("EVC_REQUEST_METADATA_UNAVAILABLE")
        rules, expert_policy = policy(row.ruleset_key)
        if uow.principal.role == Role.RO_OFFICER and expert_policy.region_rule != "SAME_REGION":
            raise Forbidden("SCHEDULE_CROSS_REGION_SCOPE_FORBIDDEN")
        allow_late = _scheduler_policy(rules.expert_pool.get("scheduler"))
        snapshot = selector_request(session, row.id, planning_until=command.horizon_end)
        # A newly registered expert appearing after the lock snapshot waits for the next run.
        facts = replace(snapshot.eligibility, experts=tuple(e for e in snapshot.eligibility.experts if e.id in locked_experts))
        requests.append(SchedulingRequest(replace(snapshot, eligibility=facts), row.requested_at, allow_late))
    existing = tuple(Allocation(row.evc_request_id, row.slot_id, tuple(row.expert_ids)) for row in session.scalars(
        select(Assignment).where(Assignment.slot_id.in_([slot.id for slot in slots])).order_by(Assignment.id)))
    problem = SchedulingProblem(tuple(requests), tuple(SchedulingSlot(s.id, s.date, s.slot_part, s.capacity) for s in slots),
                                existing, start, command.horizon_end, now)
    plan = plan_edf(problem)
    parameters = dict(horizon_start_ordinal=start.toordinal(), horizon_end_ordinal=command.horizon_end.toordinal(),
        simulated_selector=True, capacity_counts_panels=True, demo_assumptions=True,
        input_fingerprint_bytes=list(bytes.fromhex(plan.input_fingerprint)))
    session.add(ScheduleRun(run_id=command.run_id, algorithm="EDF", status="PROPOSED", parameters=parameters,
                            created_at=now, metrics=plan.metrics.numeric_json()))
    session.flush()
    port(LedgerPort).append(uow, EventIn(aggregate_type="evc_schedule_run", aggregate_id=command.run_id,
        event_type="evc.schedule_proposed", payload=dict(run_id=command.run_id, algorithm="EDF", horizon_start=start.isoformat(),
            horizon_end=command.horizon_end.isoformat(), input_fingerprint=plan.input_fingerprint, metrics=plan.metrics.numeric_json(),
            simulation_status="SIMULATED", source_status="DEMO_ASSUMPTION")))
    by_id = {row.id: row for row in selected}
    slot_by_id = {row.id: row for row in slots}
    assignment_ids = []
    for allocation in plan.allocations:
        row, slot = by_id[allocation.request_id], slot_by_id[allocation.slot_id]
        assignment_id = uuid5(NAMESPACE_URL, f"sih26262:evc:proposal:{command.run_id}:{row.id}")
        session.add(Assignment(id=assignment_id, evc_request_id=row.id, slot_id=slot.id, expert_ids=list(allocation.expert_ids),
            panel_role="DEMO_PANEL", published=False, schedule_run_id=command.run_id))
        row.status = "PROPOSED"
        session.flush()
        port(LedgerPort).append(uow, EventIn(aggregate_type="application", aggregate_id=row.application_id,
            event_type="evc.assignment_proposed", ruleset_rev=row.ruleset_key,
            payload=dict(application_id=row.application_id, request_id=row.id, assignment_id=assignment_id,
                run_id=command.run_id, slot_id=slot.id, date=slot.date.isoformat(), slot_part=slot.slot_part,
                expert_ids=list(allocation.expert_ids), ruleset_key=row.ruleset_key, request_status="PROPOSED",
                simulation_status="SIMULATED", selector_policy_version="DEMO_SELECTOR_V1", source_status="DEMO_ASSUMPTION")))
        assignment_ids.append(assignment_id)
    return ProposedSchedule(command.run_id, plan, tuple(assignment_ids))


def propose_edf(principal: Principal, command: ScheduleCommand) -> ProposedSchedule:
    with unit_of_work(principal) as uow:
        return handle(uow, command)
