"""Expert daily cap, unscheduled explanations and the pinned CP-SAT candidate window (pure, fictional DEMO data)."""
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
import yaml

from app.evc.explanations import REASONS, explain_unscheduled
from app.evc.metrics import evaluate_schedule
from app.evc.scheduler_cpsat import CpSatParameters, plan_cpsat, solve_cpsat
from app.evc.scheduler_edf import SchedulerPolicy, combined_policy, plan_edf, scheduler_policy
from app.evc.scheduling import Allocation, SchedulingProblem, SchedulingSlot
from app.workflow.expert_pool_config import validate_config
from app.workflow.scheduler_config import validate_scheduler
from contracts.errors import ValidationFailed
from test_scheduler_edf import DAY, instant, make_request, uid

ROOT = Path(__file__).resolve().parents[2]
RAW = dict(capacity_unit="PANELS", allow_late=True, source_status="DEMO_ASSUMPTION", assumption_code="EDF_PLANNING_UNCONFIRMED")
PLANNERS = [plan_edf, plan_cpsat]


def one_day(cap, requests=2, pool=3, panel=3, capacity=1):
    """Same pool, AM and PM of one day: two panels need the same experts twice that day."""
    rows = tuple(make_request(n, pool=pool, panel=panel, days=1) for n in range(1, requests + 1))
    slots = (SchedulingSlot(uid(300), DAY, "AM", capacity), SchedulingSlot(uid(301), DAY, "PM", capacity))
    return SchedulingProblem(rows, slots, (), DAY, DAY, instant(DAY), cap)


@pytest.mark.parametrize("planner", PLANNERS)
def test_daily_cap_limits_visits_per_expert_per_date_in_both_planners(planner):
    assert planner(one_day(None)).metrics.scheduled == 2  # uncapped: AM and PM with the same three experts
    assert planner(one_day(2)).metrics.scheduled == 2
    capped = planner(one_day(1))
    assert capped.metrics.scheduled == 1 and capped.metrics.hard_constraint_violations == 0
    assert explain_unscheduled(one_day(1), capped) == ((capped.unscheduled[0], "EXPERT_DAILY_CAP"),)


@pytest.mark.parametrize("planner", PLANNERS)
def test_daily_cap_spreads_panels_over_dates_and_counts_existing_commitments(planner):
    rows = tuple(make_request(n, due_offset=1, pool=3, panel=3, days=2) for n in (1, 2))
    slots = tuple(SchedulingSlot(uid(300 + i), DAY + timedelta(days=i // 2), part, 2) for i, part in enumerate(["AM", "PM"] * 2))
    plan = planner(SchedulingProblem(rows, slots, (), DAY, DAY + timedelta(days=1), instant(DAY), 1))
    assert sorted({s.date for a in plan.allocations for s in slots if s.id == a.slot_id}) == [DAY, DAY + timedelta(days=1)]
    # A published AM visit on day 0 uses the cap of every pool member that day.
    busy = (Allocation(uid(999), uid(300), (uid(1), uid(2), uid(3))),)
    single = SchedulingProblem(rows[:1], slots, busy, DAY, DAY + timedelta(days=1), instant(DAY), 1)
    [allocation] = planner(single).allocations
    assert allocation.slot_id in (uid(302), uid(303))  # day 1; AM and PM tie on the shared key


def test_shared_metrics_report_the_daily_cap_as_its_own_violation():
    problem = one_day(1)
    uncapped = plan_edf(one_day(None)).allocations
    result = evaluate_schedule(problem, uncapped)
    assert dict(result.violation_counts) == {"EXPERT_DAILY_CAP": 3}
    assert evaluate_schedule(one_day(None), uncapped).metrics.hard_constraint_violations == 0
    # Earlier commitments above the cap are the baseline; only new visits count.
    existing = (Allocation(uid(998), uid(300), (uid(1), uid(2), uid(3))),)
    baseline = replace(problem, existing=existing, slots=tuple(replace(s, capacity=2) for s in problem.slots))
    assert evaluate_schedule(baseline, ()).metrics.hard_constraint_violations == 0
    with pytest.raises(ValidationFailed, match="SCHEDULER_DAILY_CAP_INVALID"):
        one_day(0)


def test_cpsat_reports_the_pinned_candidate_window():
    problem = one_day(1)
    assert solve_cpsat(problem).numeric()["cpsat_candidate_slots"] == 12
    solved = solve_cpsat(problem, CpSatParameters(max_candidate_slots=1))
    assert solved.numeric()["cpsat_candidate_slots"] == 1 and solved.candidate_slots == 1
    assert all(isinstance(value, (int, bool)) for value in solved.numeric().values())


def explain(problem, planner=plan_edf):
    return dict(explain_unscheduled(problem, planner(problem)))


@pytest.mark.parametrize("planner", PLANNERS)
def test_explanation_codes_follow_the_problem_facts(planner):
    def single(request, slots=None, existing=(), cap=1):
        slots = slots if slots is not None else (SchedulingSlot(uid(300), DAY, "AM", 1),)
        return SchedulingProblem((request,), slots, existing, DAY, DAY, instant(DAY), cap)

    nobody = make_request(1, panel=3, days=0)
    assert explain(single(nobody), planner) == {uid(101): "NO_AVAILABILITY"}
    assert explain(single(make_request(1, pool=2, panel=3)), planner) == {uid(101): "PANEL_INCOMPLETE"}
    coi = make_request(1, pool=3, panel=3)
    facts = coi.selector.eligibility
    coi = replace(coi, selector=replace(coi.selector, eligibility=replace(facts,
        conflicts=frozenset({(uid(1), facts.institution_ref)}))))
    assert explain(single(coi), planner) == {uid(101): "COI_ONLY"}
    full = (Allocation(uid(999), uid(300), (uid(7),)),)
    assert explain(single(make_request(1, pool=3, panel=3), existing=full), planner) == {uid(101): "CAPACITY_EXHAUSTED"}
    taken = (Allocation(uid(999), uid(301), (uid(1),)),)
    slots = (SchedulingSlot(uid(300), DAY, "AM", 1), SchedulingSlot(uid(301), DAY, "AM", 1))
    assert explain(single(make_request(1, pool=3, panel=3), slots, taken), planner) == {uid(101): "CAPACITY_EXHAUSTED"}
    assert explain(single(make_request(1), slots=()), planner) == {uid(101): "NO_FEASIBLE_SLOT"}
    two = one_day(1, capacity=2)
    assert set(explain(two, planner).values()) == {"EXPERT_DAILY_CAP"}
    assert set(REASONS) == {"NO_AVAILABILITY", "PANEL_INCOMPLETE", "COI_ONLY", "CAPACITY_EXHAUSTED", "EXPERT_DAILY_CAP",
                            "NO_FEASIBLE_SLOT"}


def test_explanations_keep_the_umbrella_reason_and_plan_order():
    problem = one_day(1, requests=3)
    plan = plan_edf(problem)
    assert plan.unscheduled_reason == "NO_FEASIBLE_SLOT"
    assert [request_id for request_id, _ in explain_unscheduled(problem, plan)] == list(plan.unscheduled)
    assert explain_unscheduled(problem, replace(plan, unscheduled=())) == ()


def test_scheduler_policy_pins_daily_cap_and_candidate_window_with_defaults():
    assert validate_scheduler(RAW) == dict(RAW, expert_daily_cap=1, cpsat_candidate_slots=12)
    assert scheduler_policy(RAW) == SchedulerPolicy(True, 1, 12)
    assert scheduler_policy(dict(RAW, expert_daily_cap=2, cpsat_candidate_slots=30)) == SchedulerPolicy(True, 2, 30)
    for key, value in [("expert_daily_cap", 0), ("expert_daily_cap", "1"), ("expert_daily_cap", 11), ("expert_daily_cap", True),
                       ("cpsat_candidate_slots", 0), ("cpsat_candidate_slots", 201), ("unknown_key", 1)]:
        with pytest.raises(ValidationFailed):
            validate_scheduler(dict(RAW, **{key: value}))
        with pytest.raises(ValidationFailed):
            scheduler_policy(dict(RAW, **{key: value}))
    assert combined_policy([]) is None
    assert combined_policy([SchedulerPolicy(True, 2, 12), SchedulerPolicy(False, 1, 20)]) == SchedulerPolicy(False, 1, 20)


def test_r1_ruleset_pins_one_visit_per_day_and_twelve_candidate_slots():
    raw = yaml.safe_load((ROOT / "rulesets" / "aph-2024-27" / "r1" / "routes.yaml").read_text(encoding="utf-8"))
    pinned = raw["expert_pool"]["scheduler"]
    assert pinned["expert_daily_cap"] == 1 and pinned["cpsat_candidate_slots"] == 12
    assert scheduler_policy(pinned) == SchedulerPolicy(True, 1, 12)
    assert validate_config(raw)["scheduler"]["expert_daily_cap"] == 1
