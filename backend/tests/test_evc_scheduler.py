"""Pure EDF/CP-SAT date scheduling over fictional DEMO facts; panels always from the selector stand-in."""
from dataclasses import asdict, replace
from datetime import date, timedelta
import json
from uuid import UUID

import pytest

from app.evc.eligibility import AvailabilityFact, EligibilityRequest, ExpertCandidate, ExpertPolicy, eligible_experts
from app.evc.scheduler import Calendar, ScheduleItem, SchedulerParameters, explain, schedule
from app.evc.selector import SelectorPolicy, SelectorRequest
from contracts.errors import ValidationFailed
from generator.cases.evc_benchmark import scenario

DAY = date(2026, 7, 20)
INSTITUTION = UUID(int=900)
PARAMS = SchedulerParameters()


def uid(number):
    return UUID(int=number)


def experts(count=4, region="SOUTHERN", inactive=()):
    return tuple(ExpertCandidate(uid(i), uid(i + 100), region, ("DEMO",), i not in inactive) for i in range(1, count + 1))


def open_days(pool, days, parts=("AM", "PM"), skip=()):
    return tuple(AvailabilityFact(e.id, DAY + timedelta(days=d), part, True)
                 for e in pool for d in days for part in parts if (e.id.int, d, part) not in skip)


def item(number, pool, availability, *, earliest=0, window=2, conflicts=(), size=3, institution=INSTITUTION):
    facts = EligibilityRequest(uid(number), institution, "Southern", "aph-2024-27@r1", DAY + timedelta(days=earliest),
        DAY + timedelta(days=earliest + window), ExpertPolicy("SAME_REGION", ("AM", "PM")), pool, availability,
        frozenset((uid(e), institution) for e in conflicts), frozenset())
    return ScheduleItem(SelectorRequest(facts, "NEW_PROGRAMME", SelectorPolicy(size, ("DEMO",))), f"{number:04d}")


def panels(result):
    return {p.request_id: p for p in result.proposals}


@pytest.mark.parametrize("algorithm", ["EDF", "CPSAT"])
def test_coi_inactive_and_unavailable_experts_never_reach_a_panel(algorithm):
    pool = experts(6, inactive={2})
    availability = open_days(pool, range(3), skip={(3, 0, "AM"), (3, 0, "PM")})
    items = [item(10, pool, availability, conflicts=(1,)), item(11, pool, availability)]
    result = schedule(algorithm, items, Calendar(), PARAMS)
    chosen = panels(result)
    assert set(chosen) == {uid(10), uid(11)}
    for proposal in result.proposals:
        assert uid(2) not in proposal.panel and len(proposal.panel) == 3
        assert proposal.selection.selector_label == "SIMULATED authorised selector (stand-in)"
        for expert in proposal.panel:
            assert AvailabilityFact(expert, proposal.date, proposal.slot_part, True) in availability
    assert uid(1) not in chosen[uid(10)].panel


@pytest.mark.parametrize("algorithm", ["EDF", "CPSAT"])
def test_no_expert_is_booked_twice_and_daily_capacity_holds(algorithm):
    pool = experts(6)
    availability = open_days(pool, range(3))
    items = [item(n, pool, availability) for n in range(10, 16)]
    result = schedule(algorithm, items, Calendar(), PARAMS)
    seen, per_day = set(), {}
    for p in result.proposals:
        for expert in p.panel:
            assert (expert, p.date, p.slot_part) not in seen
            seen.add((expert, p.date, p.slot_part))
            per_day[(expert, p.date)] = per_day.get((expert, p.date), 0) + 1
    assert max(per_day.values()) <= PARAMS.expert_daily_capacity
    # Six experts, one visit each per day, panels of three, three days: at most six visits.
    assert result.metrics["scheduled_count"] == 6 and result.metrics["unscheduled_count"] == 0


def test_published_commitments_and_slot_capacity_are_consumed():
    pool = experts(3)
    availability = open_days(pool, range(2))
    first, second = item(10, pool, availability, window=1), item(11, pool, availability, window=1)
    booked = Calendar(expert_day_load=tuple(((e.id, DAY), 1) for e in pool))
    result = schedule("EDF", [first, second], booked, PARAMS)
    assert [(p.date, len(p.panel)) for p in result.proposals] == [(DAY + timedelta(days=1), 3)]
    full = Calendar(slot_capacity=(((DAY, "AM"), 1),), slot_used=(((DAY, "AM"), 1),))
    shifted = schedule("EDF", [first], full, PARAMS)
    assert (shifted.proposals[0].date, shifted.proposals[0].slot_part) == (DAY, "PM")


@pytest.mark.parametrize("case, reason", [
    ("none", "NO_AVAILABILITY"), ("two", "PANEL_INCOMPLETE"), ("coi", "COI_ONLY"), ("taken", "CAPACITY_EXHAUSTED")])
def test_unscheduled_requests_are_explained_with_codes(case, reason):
    pool = experts(3)
    availability = open_days(pool, range(2))
    if case == "none":
        target = item(10, pool, ())
    elif case == "two":
        target = item(10, pool, open_days(pool[:2], range(2)))
    elif case == "coi":
        target = item(10, pool, availability, conflicts=(1,))
    else:
        target = item(10, pool, availability, window=0)
    items = [target] + ([item(5, pool, availability, window=0, institution=uid(901))] if case == "taken" else [])
    for algorithm in ("EDF", "CPSAT"):
        result = schedule(algorithm, items, Calendar(), PARAMS)
        # Two equally urgent one-day requests compete for one panel: either may be the one explained.
        assert len(result.unscheduled) == 1
        explained = result.unscheduled[0]
        assert explained.reason_code == reason and dict(explained.slot_reasons)[reason] > 0
        assert explained.panel_size == 3 and explained.slots_considered == (6 if case != "taken" else 2)
        assert result.metrics[f"reason_{reason.lower()}"] == 1


def test_lateness_is_only_allowed_inside_the_configured_allowance():
    pool = experts(3)
    late_only = open_days(pool, [4])
    strict = schedule("CPSAT", [item(10, pool, late_only, window=2)], Calendar(), PARAMS)
    assert strict.metrics["scheduled_count"] == 0 and strict.unscheduled[0].reason_code == "NO_AVAILABILITY"
    relaxed = schedule("CPSAT", [item(10, pool, late_only, window=2)], Calendar(), replace(PARAMS, max_lateness_days=2))
    assert relaxed.proposals[0].lateness_days == 2 and relaxed.metrics["total_lateness_days"] == 2


def test_cpsat_beats_greedy_when_an_early_flexible_request_takes_a_constrained_day():
    # Request 10 (due first) can use any day; request 11's COI leaves it only day 0. EDF hands day 0 to request 10.
    pool = experts(4)
    availability = open_days(pool, [0]) + open_days(pool[:3], [1])
    flexible = item(10, pool, availability, window=1)
    constrained = item(11, pool, availability, window=1, conflicts=(1,), institution=uid(902))
    edf = schedule("EDF", [flexible, constrained], Calendar(), PARAMS)
    cpsat = schedule("CPSAT", [flexible, constrained], Calendar(), PARAMS)
    assert edf.metrics["scheduled_count"] == 1 and cpsat.metrics["scheduled_count"] == 2
    assert cpsat.metrics["fallback_to_edf"] is False and cpsat.metrics["edf_scheduled_count"] == 1


def test_cpsat_schedules_at_least_as_many_as_edf_on_the_seeded_demo_scenario():
    items = scenario(arrival_days=14, regions=4)
    edf = schedule("EDF", items, Calendar(), PARAMS)
    cpsat = schedule("CPSAT", items, Calendar(), PARAMS)
    assert cpsat.metrics["scheduled_count"] >= edf.metrics["scheduled_count"] > 0
    assert cpsat.metrics["requests_considered"] == edf.metrics["requests_considered"] == len(items)
    for result in (edf, cpsat):
        booked = [(e, p.date, p.slot_part) for p in result.proposals for e in p.panel]
        assert len(booked) == len(set(booked))


def test_runs_are_deterministic_and_do_not_mutate_inputs():
    items = scenario(arrival_days=6, regions=3)
    before = [asdict(i) for i in items]
    encode = lambda r: json.dumps([asdict(p) for p in r.proposals] + [asdict(u) for u in r.unscheduled], default=str)
    first = schedule("CPSAT", items, Calendar(), PARAMS)
    second = schedule("CPSAT", list(reversed(items)), Calendar(), PARAMS)
    assert encode(first) == encode(second) and first.metrics == second.metrics
    assert [asdict(i) for i in items] == before


def test_parameters_and_algorithm_are_validated():
    with pytest.raises(ValidationFailed):
        SchedulerParameters(workers=2)
    with pytest.raises(ValidationFailed):
        SchedulerParameters(expert_daily_capacity=0)
    with pytest.raises(ValidationFailed):
        schedule("RANDOM", [], Calendar(), PARAMS)
    pool = experts(3)
    duplicate = item(10, pool, open_days(pool, [0]))
    with pytest.raises(ValidationFailed):
        schedule("EDF", [duplicate, duplicate], Calendar(), PARAMS)
    assert all(isinstance(v, (int, float)) for v in PARAMS.numeric().values())


def test_explanations_never_admit_ineligible_experts():
    pool = experts(3, inactive={3})
    target = item(10, pool, open_days(pool, range(2)))
    assert explain(target, Calendar(), PARAMS).reason_code == "PANEL_INCOMPLETE"
    assert all(uid(3) not in [e.id for e in eligible_experts(target.selector.eligibility, DAY, part)] for part in ("AM", "PM"))
