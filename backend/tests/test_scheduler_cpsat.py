"""CP-SAT planner over the EDF baseline's SchedulingProblem, selector and shared metrics (fictional DEMO data)."""
from dataclasses import replace
from datetime import timedelta

import pytest

from app.evc.metrics import compare_plans, comparison_key, evaluate_schedule
from app.evc.scheduler_cpsat import CpSatParameters, plan_cpsat, solve_cpsat
from app.evc.scheduler_edf import plan_edf
from app.evc.scheduling import Allocation, SchedulingProblem, SchedulingSlot
from contracts.errors import ValidationFailed
from generator.cases.evc_benchmark import scenario
from test_scheduler_edf import DAY, forty_problem, instant, make_request, small_problem, uid


def greedy_trap():
    """Request 101 is first in EDF order and can use either day; 102's COI leaves it only day 0."""
    flexible = make_request(1, due_offset=1, requested_offset=-3, pool=4, panel=3, days=2, allow_late=False)
    constrained = make_request(2, due_offset=1, requested_offset=-2, pool=4, panel=3, days=2, allow_late=False)
    facts = flexible.selector.eligibility
    day_one = tuple(av for av in facts.availability if av.date == DAY or av.expert_id != uid(4))
    flexible = replace(flexible, selector=replace(flexible.selector, eligibility=replace(facts, availability=day_one)))
    facts = constrained.selector.eligibility
    constrained = replace(constrained, selector=replace(constrained.selector, eligibility=replace(facts, availability=day_one,
        conflicts=frozenset({(uid(1), facts.institution_ref)}))))
    slots = (SchedulingSlot(uid(300), DAY, "AM", 1), SchedulingSlot(uid(301), DAY + timedelta(days=1), "AM", 1))
    return SchedulingProblem((flexible, constrained), slots, (), DAY, DAY + timedelta(days=1), instant(DAY))


def test_cpsat_beats_the_greedy_baseline_when_an_early_flexible_request_takes_a_constrained_day():
    problem = greedy_trap()
    edf, solved = plan_edf(problem), solve_cpsat(problem)
    assert edf.metrics.scheduled == 1 and solved.plan.metrics.scheduled == 2
    assert solved.plan.algorithm == "CPSAT" and not solved.fallback_to_edf and solved.edf_scheduled == 1
    assert {(a.request_id, a.slot_id) for a in solved.plan.allocations} == {(uid(101), uid(301)), (uid(102), uid(300))}
    scores = dict(compare_plans(problem, (edf, solved.plan)))
    assert scores["CPSAT"] < scores["EDF"]


def test_forty_requests_respect_every_hard_constraint_and_never_score_below_edf():
    problem = forty_problem()
    plan, edf = plan_cpsat(problem), plan_edf(problem)
    assert plan.metrics.hard_constraint_violations == 0 and plan.metrics == evaluate_schedule(problem, plan.allocations).metrics
    assert comparison_key(plan.metrics) <= comparison_key(edf.metrics)
    booked = [(e, slot.date, slot.slot_part) for a in (*problem.existing, *plan.allocations)
              for slot in problem.slots if slot.id == a.slot_id for e in a.expert_ids]
    assert len(booked) == len(set(booked))
    assert all(not set(a.expert_ids) & {uid(1), uid(2), uid(24)} for a in plan.allocations)


def test_hand_verified_case_keeps_lateness_and_metrics_identical_to_edf():
    problem = small_problem()
    plan = plan_cpsat(problem)
    assert plan.metrics.scheduled == 3 and plan.metrics.total_lateness == 1 and plan.metrics.total_waiting == 11
    assert dict(compare_plans(problem, (plan_edf(problem), plan)))["CPSAT"] == comparison_key(plan_edf(problem).metrics)
    assert problem.requests[1].selector.eligibility.due_by == DAY


def test_late_planning_off_leaves_requests_unscheduled_with_the_shared_reason():
    problem = small_problem()
    hard = replace(problem, requests=tuple(replace(request, allow_late=False) for request in problem.requests))
    plan = plan_cpsat(hard)
    assert plan.metrics.scheduled == 2 and plan.metrics.total_lateness == 0
    assert len(plan.unscheduled) == 1 and plan.unscheduled_reason == "NO_FEASIBLE_SLOT"


def test_capacity_counts_panels_and_same_time_slots_share_experts():
    requests = (make_request(1, panel=2, pool=4), make_request(2, panel=2, pool=4))
    problem = SchedulingProblem(requests, (SchedulingSlot(uid(300), DAY, "AM", 1),), (), DAY, DAY, instant(DAY))
    assert plan_cpsat(problem).metrics.scheduled == 1
    request = make_request(1, pool=3, panel=2)
    slots = (SchedulingSlot(uid(300), DAY, "AM", 2), SchedulingSlot(uid(301), DAY, "AM", 2))
    taken = SchedulingProblem((request,), slots, (Allocation(uid(999), uid(300), (uid(1), uid(2))),), DAY, DAY, instant(DAY))
    assert plan_cpsat(taken).metrics.scheduled == 0 and plan_cpsat(taken).metrics.hard_constraint_violations == 0


def test_deterministic_order_insensitive_and_baseline_validated():
    problem = forty_problem()
    shuffled = replace(problem, requests=tuple(reversed(problem.requests)), slots=tuple(reversed(problem.slots)))
    assert plan_cpsat(problem) == plan_cpsat(shuffled)
    small = small_problem()
    bad = replace(small, existing=(Allocation(uid(900), uid(200), (uid(1),)), Allocation(uid(901), uid(200), (uid(2),))))
    with pytest.raises(ValidationFailed, match="BASELINE_INVALID"):
        plan_cpsat(bad)
    assert plan_cpsat(replace(small, requests=())).metrics.queue_count == 0
    assert plan_cpsat(replace(small, slots=())).metrics.lateness_days == (None, None, None)


@pytest.mark.parametrize("field,value", [("random_seed", -1), ("max_repair_rounds", 21), ("deterministic_time_limit", 0),
                                         ("time_limit_seconds", 500)])
def test_solver_parameters_are_validated(field, value):
    with pytest.raises(ValidationFailed):
        CpSatParameters(**{field: value})


def test_seeded_demo_slice_is_no_worse_than_edf_on_the_shared_key():
    problem = scenario(arrival_days=8, regions=3, allow_late=True)
    edf, solved = plan_edf(problem), solve_cpsat(problem)
    scores = dict(compare_plans(problem, (edf, solved.plan)))
    assert scores["CPSAT"] <= scores["EDF"] and edf.metrics.scheduled > 0
    assert all(isinstance(value, (int, bool)) for value in solved.numeric().values())
