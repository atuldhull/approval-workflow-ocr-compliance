"""Coded reasons for unscheduled EVC requests, derived from the same immutable SchedulingProblem.

Pure: no database, clock or random source. Every unscheduled request keeps the shared
umbrella reason NO_FEASIBLE_SLOT; this adds one more specific code per request, judged
over the request's own window against the final plan (existing commitments plus the plan's
allocations), in this order:

- NO_AVAILABILITY: no qualified expert (active, region rule, expertise minimum) declared any slot in the window.
- PANEL_INCOMPLETE: some qualified experts are available, but never a full panel at one date/part.
- COI_ONLY: a full panel is available somewhere, but conflicts of interest always leave it short.
- CAPACITY_EXHAUSTED: a conflict-free panel exists, but slot capacity or the experts' time is taken by other visits.
- EXPERT_DAILY_CAP: a free panel exists at some date/part only if experts exceeded the pinned per-day visit cap.
- NO_FEASIBLE_SLOT: no slot row exists in the window, or none of the above applies.
"""
from collections import Counter
from uuid import UUID

from app.evc.scheduling import (SchedulingPlan, SchedulingProblem, commitments, earliest_date, slot_order,
                                visits_per_day)

REASONS = ("NO_AVAILABILITY", "PANEL_INCOMPLETE", "COI_ONLY", "CAPACITY_EXHAUSTED", "EXPERT_DAILY_CAP", "NO_FEASIBLE_SLOT")


def _region_ok(rule: str, expert_region: str, request_region: str) -> bool:
    same = expert_region.upper() == request_region.upper()
    return rule == "ANY_REGION" or (rule == "SAME_REGION" and same) or (rule == "OTHER_REGION" and not same)


def explain_unscheduled(problem: SchedulingProblem, plan: SchedulingPlan) -> tuple[tuple[UUID, str], ...]:
    """(request_id, code) for every unscheduled request of `plan`, in the plan's unscheduled order."""
    requests = {request.id: request for request in problem.requests}
    slots = sorted(problem.slots, key=slot_order)
    occupancy = Counter(allocation.slot_id for allocation in (*problem.existing, *plan.allocations))
    taken = commitments(problem, plan.allocations)
    cap = problem.expert_daily_cap
    result = []
    for request_id in plan.unscheduled:
        request = requests[request_id]
        facts, policy = request.selector.eligibility, request.selector.policy
        end = problem.horizon_end if request.allow_late else min(problem.horizon_end, facts.due_by)
        start = earliest_date(problem, request)
        window = [slot for slot in slots if start <= slot.date <= end and slot.slot_part in facts.policy.slot_parts]
        tags = set(policy.tags_for(request.selector.category))
        qualified = {expert.id for expert in facts.experts
                     if expert.active and _region_ok(facts.policy.region_rule, expert.region, facts.region)
                     and len(set(expert.expertise_tags) & tags) >= policy.minimum_expertise_matches}
        refused = {(row.expert_id, row.date, row.slot_part) for row in facts.availability if not row.available}
        declared = {(row.expert_id, row.date, row.slot_part) for row in facts.availability
                    if row.available and row.expert_id in qualified}
        reserved = taken | set(facts.reservations)
        busy_days = visits_per_day(reserved)
        conflicted = {expert for expert, institution in facts.conflicts if institution == facts.institution_ref}
        size = policy.panel_size
        best = dict(available=0, clear=0)
        free_slots, capped_slots, open_slots = False, False, False
        for slot in window:
            available = {expert for expert in qualified if (expert, slot.date, slot.slot_part) in declared
                         and (expert, slot.date, slot.slot_part) not in refused}
            clear = available - conflicted
            best["available"] = max(best["available"], len(available))
            best["clear"] = max(best["clear"], len(clear))
            if len(clear) < size:
                continue
            free = {expert for expert in clear if (expert, slot.date, slot.slot_part) not in reserved}
            uncapped = {expert for expert in free
                        if cap is None or len(busy_days.get((expert, slot.date), ())) < cap}
            if len(uncapped) >= size:
                free_slots = True
                open_slots = open_slots or occupancy[slot.id] < slot.capacity
            elif len(free) >= size:
                capped_slots = True
        if not window:
            code = "NO_FEASIBLE_SLOT"
        elif best["available"] == 0:
            code = "NO_AVAILABILITY"
        elif best["available"] < size:
            code = "PANEL_INCOMPLETE"
        elif best["clear"] < size:
            code = "COI_ONLY"
        elif open_slots:
            code = "NO_FEASIBLE_SLOT"
        elif free_slots:
            code = "CAPACITY_EXHAUSTED"
        elif capped_slots:
            code = "EXPERT_DAILY_CAP"
        else:
            code = "CAPACITY_EXHAUSTED"
        result.append((request_id, code))
    return tuple(result)
