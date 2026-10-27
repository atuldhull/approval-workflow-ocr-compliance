"""EVC scheduling commands behind the HTTP API: propose a run (EDF or CP-SAT) and publish it.

Proposal is scheduler_edf.handle (one SchedulingProblem, plan_edf or solve_cpsat,
persisted as unpublished DEMO_PANEL assignments). Publication rechecks every
draft of one run with the shared metrics against published commitments and
publishes all of them or none. Panels come only from the SIMULATED authorised
selector (stand-in). No commits here: the caller owns the unit of work.
"""
from collections import Counter
from dataclasses import replace
from datetime import date
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.evc.metrics import evaluate_schedule
from app.evc.models import Assignment, AssignmentExpert, EvcRequest, ScheduleRun, Slot
from app.evc.pool import policy
from app.evc.scheduler_edf import ScheduleCommand, _scheduler_policy, handle
from app.evc.scheduling import Allocation, SchedulingProblem, SchedulingRequest, SchedulingSlot
from app.evc.selector import SELECTOR_LABEL
from app.evc.selector_service import selector_request
from app.platform.registry import port
from contracts.errors import Conflict, NotFound, ValidationFailed
from contracts.ports import AuthzPort, CasePort, ClockPort, LedgerPort, UnitOfWork
from contracts.types import EventIn, ResourceRef

LABELS = dict(selector_label=SELECTOR_LABEL, simulation_status="SIMULATED", source_status="DEMO_ASSUMPTION",
              assumption_code="EDF_PLANNING_UNCONFIRMED")
SELECTOR_POLICY_VERSION = "DEMO_SELECTOR_V1"


def propose(uow: UnitOfWork, command: ScheduleCommand) -> dict:
    """Run the propose command and describe what it persisted."""
    result = handle(uow, command)
    session, plan = uow.session, result.plan
    rows = {row.id: row for row in session.scalars(select(EvcRequest).where(
        EvcRequest.id.in_([a.request_id for a in plan.allocations])))}
    slots = {slot.id: slot for slot in session.scalars(select(Slot).where(Slot.id.in_({a.slot_id for a in plan.allocations})))}
    proposals = []
    for assignment_id, allocation in zip(result.assignment_ids, plan.allocations):
        row, slot = rows[allocation.request_id], slots[allocation.slot_id]
        proposals.append(dict(application_id=row.application_id, request_id=row.id, assignment_id=assignment_id,
                              slot_id=slot.id, date=slot.date, slot_part=slot.slot_part, expert_ids=list(allocation.expert_ids),
                              due_by=row.due_by, lateness_days=max(0, (slot.date - row.due_by).days)))
    run = session.get(ScheduleRun, result.run_id)
    solver = {key.removeprefix("cpsat_"): value for key, value in run.parameters.items() if key.startswith("cpsat_")}
    return dict(run_id=result.run_id, algorithm=plan.algorithm, status=result.status,
                region_scope=command.region.upper() if command.region else None,
                horizon_start=date.fromordinal(run.parameters["horizon_start_ordinal"]), horizon_end=command.horizon_end,
                input_fingerprint=plan.input_fingerprint, metrics=plan.metrics.numeric_json(), proposals=proposals,
                unscheduled=[dict(request_id=request_id, reason_code=plan.unscheduled_reason) for request_id in plan.unscheduled],
                solver=solver or None, created_at=run.created_at, **LABELS)


def _memberships(session, *, exclude_run: UUID):
    """Published commitments of other runs as (membership, request id); the published-only index is the final guard."""
    return list(session.execute(select(AssignmentExpert, Assignment.evc_request_id)
                                .join(Assignment, Assignment.id == AssignmentExpert.assignment_id)
                                .where(AssignmentExpert.published.is_(True), Assignment.schedule_run_id != exclude_run)
                                .order_by(AssignmentExpert.assignment_id, AssignmentExpert.expert_id)))


def publish(uow: UnitOfWork, run_id: UUID) -> dict:
    """Atomically publish every draft of one run after rechecking it; any failure publishes nothing."""
    session, principal = uow.session, uow.principal
    port(AuthzPort).check(principal, "evc.schedule.publish", ResourceRef("evc", run_id))
    now = port(ClockPort).now()
    run = session.get(ScheduleRun, run_id, with_for_update=True)
    if run is None:
        raise NotFound("EVC_RUN_NOT_FOUND")
    if run.status != "PROPOSED":
        raise Conflict("EVC_RUN_NOT_PUBLISHABLE")
    drafts = list(session.scalars(select(Assignment).where(Assignment.schedule_run_id == run_id,
                                                           Assignment.published.is_(False)).order_by(Assignment.id)))
    if not drafts:
        raise Conflict("EVC_RUN_EMPTY")
    slots = {s.id: s for s in session.scalars(select(Slot).where(Slot.id.in_({a.slot_id for a in drafts}))
                                              .order_by(Slot.id).with_for_update())}
    rows = {r.id: r for r in session.scalars(select(EvcRequest).where(EvcRequest.id.in_({a.evc_request_id for a in drafts}))
                                             .order_by(EvcRequest.id).with_for_update())}
    start, end = (date.fromordinal(run.parameters[key]) for key in ("horizon_start_ordinal", "horizon_end_ordinal"))
    published = _memberships(session, exclude_run=run_id)
    taken = frozenset((m.expert_id, m.date, m.slot_part) for m, _ in published)
    existing = {}
    for m, request_id in published:
        if m.slot_id in slots:
            existing.setdefault(m.assignment_id, (request_id, m.slot_id, []))[2].append(m.expert_id)
    requests = []
    for row in rows.values():
        if row.status != "PROPOSED":
            raise Conflict("EVC_REQUEST_NOT_PROPOSED")
        case = port(CasePort).lookup(session, row.application_id)
        port(AuthzPort).check(principal, "evc.schedule.publish", ResourceRef("application", case.application_id,
                              case.institution_id, case.region))
        if row.region != case.region or row.institution_ref != case.institution_id:
            raise Conflict("SCHEDULE_CASE_REFERENCE_CHANGED")
        rules, _ = policy(row.ruleset_key)
        snapshot = selector_request(session, row.id, planning_until=end)
        # Recheck against published commitments only: this run's own drafts must not block themselves.
        facts = replace(snapshot.eligibility, reservations=frozenset(r for r in taken if row.earliest_date <= r[1] <= end))
        requests.append(SchedulingRequest(replace(snapshot, eligibility=facts), row.requested_at,
                                          _scheduler_policy(rules.expert_pool.get("scheduler"))))
    for draft in drafts:
        slot = slots[draft.slot_id]
        if any((expert, slot.date, slot.slot_part) in taken for expert in draft.expert_ids):
            raise Conflict("EVC_EXPERT_DOUBLE_BOOKED")
    use = Counter(slot_id for _, slot_id, _ in existing.values()) + Counter(draft.slot_id for draft in drafts)
    if any(use[slot_id] > slot.capacity for slot_id, slot in slots.items()):
        raise Conflict("EVC_SLOT_CAPACITY_EXHAUSTED")
    try:
        problem = SchedulingProblem(tuple(requests), tuple(SchedulingSlot(s.id, s.date, s.slot_part, s.capacity) for s in slots.values()),
                                    tuple(Allocation(request_id, slot_id, tuple(experts)) for request_id, slot_id, experts in existing.values()),
                                    start, end, now)
    except ValidationFailed:
        raise Conflict("EVC_PUBLISH_RECHECK_FAILED") from None
    check = evaluate_schedule(problem, tuple(Allocation(d.evc_request_id, d.slot_id, tuple(d.expert_ids)) for d in drafts))
    if check.metrics.hard_constraint_violations:
        raise Conflict("EVC_PUBLISH_RECHECK_FAILED")
    try:
        session.execute(update(Assignment).where(Assignment.id.in_([d.id for d in drafts])).values(published=True))
        session.flush()
    except IntegrityError as exc:
        if getattr(getattr(exc.orig, "diag", None), "constraint_name", None) == "uq_evc_published_expert_time":
            raise Conflict("EVC_EXPERT_DOUBLE_BOOKED") from None
        raise
    for row in rows.values():
        row.status = "PUBLISHED"
    run.status = "PUBLISHED"
    session.flush()
    result = []
    for draft in drafts:
        slot, row = slots[draft.slot_id], rows[draft.evc_request_id]
        entry = dict(application_id=row.application_id, request_id=row.id, assignment_id=draft.id, run_id=run_id,
                     algorithm=run.algorithm, slot_id=slot.id, date=slot.date.isoformat(), slot_part=slot.slot_part,
                     due_by=row.due_by.isoformat(), lateness_days=max(0, (slot.date - row.due_by).days),
                     expert_ids=list(draft.expert_ids), panel_role=draft.panel_role, ruleset_key=row.ruleset_key,
                     request_status="PUBLISHED", simulation_status="SIMULATED",
                     selector_policy_version=SELECTOR_POLICY_VERSION, source_status="DEMO_ASSUMPTION")
        port(LedgerPort).append(uow, EventIn(aggregate_type="application", aggregate_id=row.application_id,
            event_type="evc.assignment_published", ruleset_rev=row.ruleset_key, payload=entry))
        result.append(entry)
    return dict(run_id=run_id, algorithm=run.algorithm, status="PUBLISHED", published_count=len(result),
                assignments=result, **LABELS)
