"""Algorithm-independent EVC feasibility, lateness and waiting evaluation."""
from collections import Counter, defaultdict
from dataclasses import dataclass
from uuid import UUID

from app.evc.eligibility import eligible_experts
from app.evc.scheduling import Allocation, SchedulingMetrics, SchedulingPlan, SchedulingProblem, earliest_date, logical_date, selector_at, slot_order
from contracts.errors import ValidationFailed


@dataclass(frozen=True)
class Evaluation:
    metrics: SchedulingMetrics
    violation_counts: tuple[tuple[str, int], ...]


def evaluate_schedule(problem: SchedulingProblem, allocations: tuple[Allocation, ...]) -> Evaluation:
    """Same function/inputs for EDF and CP-SAT; unscheduled is explicit, never zero lateness."""
    violations = Counter()
    slots = {slot.id: slot for slot in problem.slots}
    requests = {request.id: request for request in problem.requests}
    occupancy = Counter()
    booked = Counter()
    by_request = defaultdict(list)
    for allocation in (*problem.existing, *allocations):
        slot = slots.get(allocation.slot_id)
        if slot is None:
            violations["UNKNOWN_SLOT"] += 1
            continue
        occupancy[slot.id] += 1
        for expert in set(allocation.expert_ids):
            booked[(expert, slot.date, slot.slot_part)] += 1
    for slot_id, count in occupancy.items():
        violations["CAPACITY_EXCEEDED"] += max(0, count - slots[slot_id].capacity)
    violations["EXPERT_DOUBLE_BOOKED"] += sum(max(0, count - 1) for count in booked.values())
    for allocation in allocations:
        if allocation.request_id not in requests:
            violations["UNKNOWN_REQUEST"] += 1
            continue
        by_request[allocation.request_id].append(allocation)
        request = requests[allocation.request_id]
        slot = slots.get(allocation.slot_id)
        if slot is None:
            continue
        if (slot.date < earliest_date(problem, request) or slot.date > problem.horizon_end
            or (not request.allow_late and slot.date > request.selector.eligibility.due_by)):
            violations["WINDOW"] += 1
        if len(allocation.expert_ids) != request.selector.policy.panel_size:
            violations["PANEL_SIZE"] += 1
        violations["DUPLICATE_EXPERT"] += len(allocation.expert_ids) - len(set(allocation.expert_ids))
        snapshot = selector_at(problem, request, ())
        eligible = {expert.id: expert for expert in eligible_experts(snapshot.eligibility, slot.date, slot.slot_part)}
        tags = set(snapshot.policy.tags_for(snapshot.category))
        for expert_id in set(allocation.expert_ids):
            expert = eligible.get(expert_id)
            if expert is None:
                violations["EXPERT_ELIGIBILITY"] += 1
            elif len(set(expert.expertise_tags) & tags) < snapshot.policy.minimum_expertise_matches:
                violations["EXPERTISE"] += 1
    violations["DUPLICATE_REQUEST"] += sum(max(0, len(values) - 1) for values in by_request.values())
    # A queued request cannot already have an assignment in the baseline snapshot.
    existing_requests = {row.request_id for row in problem.existing}
    violations["ALREADY_ASSIGNED_REQUEST"] += len(existing_requests & set(by_request))
    lateness = []
    waits = []
    for request in problem.ordered_requests:
        known = [row for row in by_request.get(request.id, ()) if row.slot_id in slots]
        if not known:
            lateness.append(None)
            continue
        chosen = min(known, key=lambda row: (slot_order(slots[row.slot_id]), tuple(str(v) for v in row.expert_ids)))
        assigned = slots[chosen.slot_id].date
        lateness.append(max(0, (assigned - request.selector.eligibility.due_by).days))
        waits.append(max(0, (assigned - logical_date(request.requested_at)).days))
    scheduled = sum(value is not None for value in lateness)
    values = [value for value in lateness if value is not None]
    counts = tuple(sorted((key, value) for key, value in violations.items() if value))
    metrics = SchedulingMetrics(len(problem.requests), scheduled, len(problem.requests) - scheduled,
        sum(value > 0 for value in values), sum(values), max(values, default=0), sum(waits), sum(value for _, value in counts), tuple(lateness))
    return Evaluation(metrics, counts)


def comparison_key(metrics: SchedulingMetrics) -> tuple[int, ...]:
    """Minimise: violations, unscheduled count, total/max lateness, then waiting."""
    return (metrics.hard_constraint_violations, metrics.unscheduled, metrics.total_lateness, metrics.max_lateness, metrics.total_waiting)


def compare_plans(problem: SchedulingProblem, plans: tuple[SchedulingPlan, ...]) -> tuple[tuple[str, tuple[int, ...]], ...]:
    """Reject mixed snapshots/self-reported metrics before comparing EDF with CP-SAT."""
    if len({plan.algorithm for plan in plans}) != len(plans):
        raise ValidationFailed("SCHEDULER_DUPLICATE_ALGORITHM")
    fingerprint = problem.fingerprint
    results = []
    for plan in plans:
        if plan.input_fingerprint != fingerprint:
            raise ValidationFailed("SCHEDULER_COMPARISON_INPUT_MISMATCH")
        actual = evaluate_schedule(problem, plan.allocations).metrics
        if actual != plan.metrics:
            raise ValidationFailed("SCHEDULER_METRICS_MISMATCH")
        results.append((plan.algorithm, comparison_key(actual)))
    return tuple(sorted(results))
