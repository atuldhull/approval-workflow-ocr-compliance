"""Hand-calculated EDF placement and an independent forty-request DEMO fixture."""
from collections import Counter
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID

import pytest

from app.evc.eligibility import AvailabilityFact, EligibilityRequest, ExpertCandidate, ExpertPolicy
from app.evc.metrics import compare_plans, comparison_key, evaluate_schedule
from app.evc.scheduler_edf import plan_edf
from app.evc.scheduling import Allocation, SchedulingProblem, SchedulingRequest, SchedulingSlot
from app.evc.selector import AssignmentFact, SelectorPolicy, SelectorRequest, select_panel
from app.workflow.scheduler_config import validate_scheduler
from contracts.errors import ValidationFailed

DAY = date(2026, 7, 20)


def uid(number):
    return UUID(int=number)


def instant(day):
    return datetime.combine(day, time(4, 30), timezone.utc)


def make_request(number, due_offset=0, requested_offset=-3, *, pool=3, panel=1, days=3, allow_late=True):
    experts = tuple(ExpertCandidate(uid(i), uid(1000 + i), "SOUTHERN", ("DEMO",), True) for i in range(1, pool + 1))
    eligibility = EligibilityRequest(uid(100 + number), uid(1000 + number % 2), "Southern", "aph-2024-27@r1",
        DAY, DAY + timedelta(days=due_offset), ExpertPolicy("SAME_REGION", ("AM", "PM")), experts,
        tuple(AvailabilityFact(e.id, DAY + timedelta(days=day), part, True) for e in experts for day in range(days) for part in ("AM", "PM")),
        frozenset(), frozenset())
    selector = SelectorRequest(eligibility, "NEW_PROGRAMME", SelectorPolicy(panel, ("DEMO",)))
    return SchedulingRequest(selector, instant(DAY + timedelta(days=requested_offset)), allow_late)


def small_problem():
    # C requested first but has the later deadline. A wins the A/B requested_at tie-break.
    requests = (make_request(3, 1, -4), make_request(2, 0, -2), make_request(1, 0, -3))
    slots = (SchedulingSlot(uid(200), DAY, "AM", 1), SchedulingSlot(uid(201), DAY + timedelta(days=1), "AM", 2))
    return SchedulingProblem(requests, tuple(reversed(slots)), (), DAY, DAY + timedelta(days=1), instant(DAY))


def forty_problem():
    requests = []
    for index in range(40):
        row = make_request(index, index % 4, -(index % 5 + 1), pool=24, panel=3, days=6)
        facts = row.selector.eligibility
        facts = replace(facts, conflicts=frozenset({(uid(1), facts.institution_ref), (uid(2), facts.institution_ref)}),
            experts=tuple(replace(expert, active=False) if expert.id == uid(24) else expert for expert in facts.experts),
            availability=tuple(replace(av, available=(av.expert_id.int + (av.date - DAY).days) % 7 != 0) for av in facts.availability))
        history = tuple(AssignmentFact(uid(8000), uid(i), DAY, "AM") for i in (3, 4, 5))
        requests.append(replace(row, selector=replace(row.selector, eligibility=facts, assignments=history)))
    slots = tuple(SchedulingSlot(uid(2000 + day * 2 + part), DAY + timedelta(days=day), token, 4)
                  for day in range(6) for part, token in enumerate(("AM", "PM")))
    existing = (Allocation(uid(7999), slots[0].id, (uid(3), uid(4), uid(5))),)
    return SchedulingProblem(tuple(reversed(requests)), tuple(reversed(slots)), existing, DAY, DAY + timedelta(days=5), instant(DAY))


def test_hand_verified_edf_case_and_exact_metrics():
    problem = small_problem()
    plan = plan_edf(problem)
    assert [(row.request_id, row.slot_id, row.expert_ids) for row in plan.allocations] == [
        (uid(101), uid(200), (uid(1),)), (uid(102), uid(201), (uid(2),)), (uid(103), uid(201), (uid(3),))]
    assert plan.metrics.numeric_json() == dict(queue_count=3, scheduled=3, unscheduled=0, late_count=1,
        total_lateness=1, max_lateness=1, total_waiting=11, hard_constraint_violations=0, lateness_days=[0, 1, 0])
    assert plan.metrics == evaluate_schedule(problem, plan.allocations).metrics
    assert problem.requests[1].selector.eligibility.due_by == DAY  # Never repin or move a deadline.
    assert plan.simulation_status == "SIMULATED" and plan.selector_label == "SIMULATED authorised selector (stand-in)"


def test_late_planning_is_explicit_and_default_selector_cutoff_is_preserved():
    problem = small_problem()
    row = next(request for request in problem.requests if request.id == uid(102))
    assert select_panel(row.selector, DAY + timedelta(days=1), "AM").panel == ()
    assert uid(102) in {allocation.request_id for allocation in plan_edf(problem).allocations}
    hard = replace(problem, requests=tuple(replace(request, allow_late=False) for request in problem.requests))
    plan = plan_edf(hard)
    assert plan.metrics.scheduled == 2 and plan.unscheduled == (uid(102),)
    assert plan.metrics.total_lateness == 0 and plan.unscheduled_reason == "NO_FEASIBLE_SLOT"
    assert comparison_key(plan_edf(problem).metrics) < comparison_key(plan.metrics)  # Cardinality before lateness.


def test_forty_requests_capacity_availability_coi_and_expert_booking_independently_checked():
    problem = forty_problem()
    plan = plan_edf(problem)
    assert plan.metrics.scheduled == 40 and plan.metrics.unscheduled == 0 and plan.metrics.hard_constraint_violations == 0
    assert len({row.request_id for row in plan.allocations}) == 40
    slots = {slot.id: slot for slot in problem.slots}
    requests = {request.id: request for request in problem.requests}
    capacity, booked = Counter(), Counter()
    late, waits = [], []
    for allocation in (*problem.existing, *plan.allocations):
        slot = slots[allocation.slot_id]
        capacity[slot.id] += 1
        for expert in allocation.expert_ids:
            booked[(expert, slot.date, slot.slot_part)] += 1
    assert all(capacity[key] <= slots[key].capacity for key in capacity)
    assert max(booked.values()) == 1
    for allocation in plan.allocations:
        row, slot = requests[allocation.request_id], slots[allocation.slot_id]
        assert len(allocation.expert_ids) == len(set(allocation.expert_ids)) == 3
        facts = row.selector.eligibility
        available = {(av.expert_id, av.date, av.slot_part) for av in facts.availability if av.available}
        assert not set(allocation.expert_ids) & {uid(1), uid(2), uid(24)}
        assert all((expert, slot.date, slot.slot_part) in available for expert in allocation.expert_ids)
        late.append(max(0, (slot.date - facts.due_by).days))
        waits.append((slot.date - row.requested_at.date()).days)
    assert plan.metrics.total_lateness == sum(late) and plan.metrics.max_lateness == max(late)
    assert plan.metrics.total_waiting == sum(waits)


def test_deterministic_queue_and_slot_ties_and_order_insensitive_fingerprint():
    problem = small_problem()
    shuffled = replace(problem, requests=tuple(reversed(problem.requests)), slots=tuple(reversed(problem.slots)))
    assert problem.fingerprint == shuffled.fingerprint
    assert plan_edf(problem) == plan_edf(shuffled)
    same = tuple(replace(row, requested_at=instant(DAY - timedelta(days=3))) for row in problem.requests[:2])
    tied = replace(problem, requests=tuple(replace(row, selector=replace(row.selector, eligibility=replace(row.selector.eligibility, due_by=DAY))) for row in same))
    assert [row.request_id for row in plan_edf(tied).allocations] == sorted(row.id for row in tied.requests)


def test_am_before_pm_and_no_scheduling_before_clock_or_request_window():
    request = make_request(1, due_offset=2)
    slots = (SchedulingSlot(uid(300), DAY + timedelta(days=1), "PM", 1),
             SchedulingSlot(uid(302), DAY, "AM", 1), SchedulingSlot(uid(301), DAY + timedelta(days=1), "AM", 1))
    problem = SchedulingProblem((request,), slots, (), DAY, DAY + timedelta(days=2), instant(DAY + timedelta(days=1)))
    assert plan_edf(problem).allocations[0].slot_id == uid(301)


def test_capacity_is_panels_not_expert_seats_and_no_partial_panel():
    requests = (make_request(1, panel=2, pool=4), make_request(2, panel=2, pool=4))
    slot = SchedulingSlot(uid(300), DAY, "AM", 1)
    problem = SchedulingProblem(requests, (slot,), (), DAY, DAY, instant(DAY))
    plan = plan_edf(problem)
    assert plan.metrics.scheduled == 1 and len(plan.allocations[0].expert_ids) == 2
    assert plan.metrics.hard_constraint_violations == 0
    insufficient = replace(problem, requests=(make_request(1, panel=5, pool=4),))
    assert plan_edf(insufficient).metrics.scheduled == 0


def test_same_time_across_distinct_slots_still_excludes_already_assigned_experts():
    request = make_request(1, pool=3, panel=2)
    slots = (SchedulingSlot(uid(300), DAY, "AM", 2), SchedulingSlot(uid(301), DAY, "AM", 2))
    baseline = (Allocation(uid(999), uid(300), (uid(1), uid(2))),)
    problem = SchedulingProblem((request,), slots, baseline, DAY, DAY, instant(DAY))
    assert plan_edf(problem).metrics.scheduled == 0
    assert plan_edf(problem).metrics.hard_constraint_violations == 0


@pytest.mark.parametrize("bad", ["CAPACITY", "DOUBLE_BOOK", "UNKNOWN_REQUEST", "UNKNOWN_SLOT", "PANEL", "DUPLICATE", "EXPERTISE", "COI", "EARLY"])
def test_shared_metrics_detect_invalid_plans_without_calling_edf(bad):
    problem = small_problem()
    plan = (Allocation(uid(101), uid(200), (uid(1),)),)
    if bad in {"CAPACITY", "DOUBLE_BOOK"}:
        plan += (Allocation(uid(102), uid(200), (uid(1) if bad == "DOUBLE_BOOK" else uid(2),)),)
    elif bad == "UNKNOWN_REQUEST":
        plan = (replace(plan[0], request_id=uid(999)),)
    elif bad == "UNKNOWN_SLOT":
        plan = (replace(plan[0], slot_id=uid(999)),)
    elif bad == "PANEL":
        plan = (replace(plan[0], expert_ids=()),)
    elif bad == "DUPLICATE":
        plan *= 2
    elif bad == "EXPERTISE":
        problem = replace(problem, requests=tuple(replace(row, selector=replace(row.selector, policy=SelectorPolicy(1, ("DEMO_UNKNOWN",)))) for row in problem.requests))
    elif bad == "COI":
        problem = replace(problem, requests=tuple(replace(row, selector=replace(row.selector, eligibility=replace(row.selector.eligibility,
            conflicts=frozenset({(uid(1), row.selector.eligibility.institution_ref)})))) for row in problem.requests))
    else:
        problem = replace(problem, clock_at=instant(DAY + timedelta(days=1)))
    result = evaluate_schedule(problem, plan)
    assert result.metrics.hard_constraint_violations > 0 and result.violation_counts


def test_empty_input_all_unscheduled_and_bad_baseline():
    problem = small_problem()
    assert plan_edf(replace(problem, requests=())).metrics.queue_count == 0
    assert plan_edf(replace(problem, slots=())).metrics.lateness_days == (None, None, None)
    bad = replace(problem, existing=(Allocation(uid(900), uid(200), (uid(1),)), Allocation(uid(901), uid(200), (uid(2),))))
    with pytest.raises(ValidationFailed, match="BASELINE_INVALID"):
        plan_edf(bad)


def test_comparison_requires_identical_inputs_and_recomputed_metrics():
    problem = small_problem()
    edf = plan_edf(problem)
    cpsat = replace(edf, algorithm="CPSAT")  # Same allocation is a legitimate equal-score comparison.
    scores = dict(compare_plans(problem, (edf, cpsat)))
    assert scores["EDF"] == scores["CPSAT"]
    with pytest.raises(ValidationFailed, match="COMPARISON_INPUT_MISMATCH"):
        compare_plans(problem, (edf, replace(cpsat, input_fingerprint="0" * 64)))
    with pytest.raises(ValidationFailed, match="METRICS_MISMATCH"):
        compare_plans(problem, (edf, replace(cpsat, metrics=replace(cpsat.metrics, total_lateness=0))))
    with pytest.raises(ValidationFailed, match="DUPLICATE_ALGORITHM"):
        compare_plans(problem, (edf, edf))


def test_input_fingerprint_preserves_expert_institution_pair_roles():
    problem = small_problem()
    original = problem.requests[0]
    facts = original.selector.eligibility
    left = replace(original, selector=replace(original.selector, eligibility=replace(facts,
        conflicts=frozenset({(uid(1), facts.institution_ref)}))))
    right = replace(original, selector=replace(original.selector, eligibility=replace(facts,
        conflicts=frozenset({(facts.institution_ref, uid(1))}))))
    assert replace(problem, requests=(left,)).fingerprint != replace(problem, requests=(right,)).fingerprint


@pytest.mark.parametrize("key,value", [("capacity_unit", "EXPERTS"), ("allow_late", 1), ("source_status", "OFFICIAL"), ("assumption_code", "VERIFIED")])
def test_demo_scheduler_policy_is_explicit_and_validated(key, value):
    raw = dict(capacity_unit="PANELS", allow_late=True, source_status="DEMO_ASSUMPTION", assumption_code="EDF_PLANNING_UNCONFIRMED")
    assert validate_scheduler(raw)["allow_late"] is True
    with pytest.raises(ValidationFailed):
        validate_scheduler(dict(raw, **{key: value}))
