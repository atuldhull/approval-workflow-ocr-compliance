"""Fictional DEMO selection facts and a controlled 100-request fairness comparison."""
from collections import Counter
from dataclasses import asdict, replace
from datetime import date, timedelta
import json
from uuid import UUID

import pytest

from app.evc.eligibility import AvailabilityFact, EligibilityRequest, ExpertCandidate, ExpertPolicy, eligible_experts
from app.evc.selector import AssignmentFact, CRITERIA, SELECTOR_LABEL, SelectorPolicy, SelectorRequest, select_panel
from app.workflow.expert_pool_config import validate_config
from app.workflow.selector_config import validate_selector
from contracts.errors import ValidationFailed

DAY = date(2026, 7, 20)
RAW_POLICY = dict(version="DEMO_SELECTOR_V1", panel_size=3, required_expertise_tags=["DEMO"],
                  category_expertise_tags={}, minimum_expertise_matches=1, source_status="DEMO_ASSUMPTION",
                  assumption_code="SELECTOR_POLICY_UNCONFIRMED")


def uid(number):
    return UUID(int=number)


def request(size=1, count=3):
    experts = tuple(ExpertCandidate(uid(i), uid(i + 100), "SOUTHERN", ("DEMO",), True) for i in range(1, count + 1))
    facts = EligibilityRequest(uid(1000), uid(1001), "Southern", "aph-2024-27@r1", DAY, DAY + timedelta(days=200),
        ExpertPolicy("SAME_REGION", ("AM", "PM")), experts,
        tuple(AvailabilityFact(expert.id, DAY, "AM", True) for expert in experts), frozenset(), frozenset())
    return SelectorRequest(facts, "NEW_PROGRAMME", SelectorPolicy(size, ("DEMO",)))


def fact(expert, days_ago=10, token=0):
    return AssignmentFact(uid(2000 + token), uid(expert), DAY - timedelta(days=days_ago), "AM")


def test_same_input_and_permutations_are_byte_identical_without_mutation():
    base = replace(request(size=2), assignments=(fact(1, token=1), fact(2, token=2)))
    before = asdict(base)
    expected = select_panel(base, DAY, "AM")
    shuffled = replace(base, eligibility=replace(base.eligibility, experts=tuple(reversed(base.eligibility.experts)),
                       availability=tuple(reversed(base.eligibility.availability))), assignments=tuple(reversed(base.assignments)))
    encode = lambda result: json.dumps(asdict(result), default=str, sort_keys=True)
    assert encode(select_panel(base, DAY, "AM")) == encode(expected) == encode(select_panel(shuffled, DAY, "AM"))
    assert asdict(base) == before
    assert expected.selector_label == SELECTOR_LABEL == "SIMULATED authorised selector (stand-in)"
    assert expected.criteria_order == CRITERIA and expected.simulation_status == "SIMULATED"


@pytest.mark.parametrize("exclusion", ["COI", "UNAVAILABLE", "MISSING", "RESERVED", "INACTIVE", "REGION"])
def test_hard_eligibility_always_precedes_ranking(exclusion):
    base = request(count=2)
    data = base.eligibility
    if exclusion == "COI":
        data = replace(data, conflicts=frozenset({(uid(1), data.institution_ref)}))
    elif exclusion == "UNAVAILABLE":
        data = replace(data, availability=(replace(data.availability[0], available=False), data.availability[1]))
    elif exclusion == "MISSING":
        data = replace(data, availability=(data.availability[1],))
    elif exclusion == "RESERVED":
        data = replace(data, reservations=frozenset({(uid(1), DAY, "AM")}))
    else:
        altered = replace(data.experts[0], active=False) if exclusion == "INACTIVE" else replace(data.experts[0], region="NORTHERN")
        data = replace(data, experts=(altered, data.experts[1]))
    result = select_panel(replace(base, eligibility=data), DAY, "AM")
    assert result.panel == (uid(2),)
    assert uid(1) not in [row.expert_id for row in result.ranked_experts]


def test_coi_with_best_expertise_and_lightest_workload_never_selected():
    base = request(count=2)
    experts = (replace(base.eligibility.experts[0], expertise_tags=("DEMO_A", "DEMO_B")),
               replace(base.eligibility.experts[1], expertise_tags=("DEMO_A",)))
    data = replace(base.eligibility, experts=experts, conflicts=frozenset({(uid(1), base.eligibility.institution_ref)}))
    result = select_panel(replace(base, eligibility=data, policy=SelectorPolicy(1, ("DEMO_A", "DEMO_B")),
                                  assignments=(fact(2),)), DAY, "AM")
    assert result.panel == (uid(2),)


def test_expertise_match_precedes_workload_and_explains_scores():
    base = request(count=2)
    experts = (replace(base.eligibility.experts[0], expertise_tags=("DEMO_A", "DEMO_B")),
               replace(base.eligibility.experts[1], expertise_tags=("DEMO_A",)))
    base = replace(base, eligibility=replace(base.eligibility, experts=experts), policy=SelectorPolicy(1, ("DEMO_B", "DEMO_A")),
                   assignments=tuple(fact(1, days_ago=i + 1, token=i) for i in range(20)))
    result = select_panel(base, DAY, "AM")
    assert result.panel == (uid(1),)
    first, second = result.ranked_experts
    assert first.matched_expertise_tags == ("DEMO_A", "DEMO_B")
    assert (first.criterion_scores.expertise_matches, first.criterion_scores.workload_assignments) == (2, 20)
    assert (second.criterion_scores.expertise_matches, second.criterion_scores.workload_assignments) == (1, 0)


def test_workload_precedes_rotation():
    base = replace(request(count=2), assignments=(fact(1, 15, 1), fact(1, 10, 2), fact(2, 1, 3)))
    assert select_panel(base, DAY, "AM").panel == (uid(2),)


def test_rotation_uses_oldest_prior_date_before_uuid():
    base = replace(request(count=2), assignments=(fact(1, 1, 1), fact(2, 10, 2)))
    result = select_panel(base, DAY, "AM")
    assert result.panel == (uid(2),)
    assert result.ranked_experts[0].criterion_scores.rotation_days == 10
    assert result.ranked_experts[0].criterion_scores.rotation_ordinal == (DAY - timedelta(days=10)).toordinal()


def test_future_and_same_day_workload_counts_without_fabricating_prior_rotation():
    base = replace(request(), assignments=(fact(1, 2, 1), fact(2, -20, 2), fact(3, 0, 3)))
    result = select_panel(base, DAY, "AM")
    assert result.panel == (uid(2),)  # Same load; no prior date for 2/3, then UUID tie-break.
    assert result.ranked_experts[0].criterion_scores.last_assignment_date is None
    assert result.ranked_experts[0].criterion_scores.rotation_days is None
    assert result.ranked_experts[0].criterion_scores.workload_assignments == 1


def test_distinct_assignment_memberships_are_counted_once_and_conflicts_rejected():
    same = fact(1, 10, 1)
    base = replace(request(count=2), assignments=(same, same, fact(2, 10, 2)))
    result = select_panel(base, DAY, "AM")
    assert result.panel == (uid(1),) and result.ranked_experts[0].criterion_scores.workload_assignments == 1
    with pytest.raises(ValidationFailed, match="SELECTOR_HISTORY_CONFLICT"):
        select_panel(replace(base, assignments=(same, replace(same, date=DAY))), DAY, "AM")


def test_exact_n_shortage_minimum_expertise_and_no_partial_panel():
    base = request(size=4)
    result = select_panel(base, DAY, "AM")
    assert result.status == "INSUFFICIENT_CANDIDATES" and result.panel == () and result.eligible_count == 3
    assert not any(row.selected for row in result.ranked_experts)
    assert result.selector_label == SELECTOR_LABEL
    result = select_panel(replace(base, policy=SelectorPolicy(1, ("DEMO_UNKNOWN",))), DAY, "AM")
    assert result.eligible_count == 0 and result.panel == ()
    result = select_panel(replace(base, policy=SelectorPolicy(3, ("DEMO",))), DAY, "AM")
    assert result.status == "SELECTED" and result.panel == (uid(1), uid(2), uid(3))
    assert sum(row.selected for row in result.ranked_experts) == 3
    assert select_panel(base, DAY - timedelta(days=1), "AM").panel == ()


def test_duplicate_experts_and_unknown_slot_are_clean_errors():
    base = request()
    with pytest.raises(ValidationFailed, match="SELECTOR_DUPLICATE_EXPERT"):
        select_panel(replace(base, eligibility=replace(base.eligibility, experts=base.eligibility.experts * 2)), DAY, "AM")
    with pytest.raises(ValidationFailed, match="SLOT_PART"):
        select_panel(base, DAY, "EVENING")


def test_category_override_and_tag_order_are_explicit_and_deterministic():
    raw = dict(RAW_POLICY, required_expertise_tags=["DEMO_Z", "DEMO"],
               category_expertise_tags={"NEW_PROGRAMME": ["DEMO_B", "DEMO_A"]})
    policy = SelectorPolicy.from_mapping(raw)
    assert policy.tags_for("NEW_PROGRAMME") == ("DEMO_A", "DEMO_B")
    assert policy.tags_for("NEW_INSTITUTION") == ("DEMO", "DEMO_Z")
    assert validate_selector(raw, {"NEW_PROGRAMME"})["category_expertise_tags"] == {"NEW_PROGRAMME": ["DEMO_A", "DEMO_B"]}
    with pytest.raises(ValidationFailed, match="SELECTOR_CATEGORY_POLICY_INVALID"):
        validate_selector(raw, {"NEW_INSTITUTION"})


@pytest.mark.parametrize("field,value", [("version", "OFFICIAL"), ("panel_size", 0), ("panel_size", True),
    ("required_expertise_tags", []), ("required_expertise_tags", ["DEMO", "DEMO"]),
    ("required_expertise_tags", ["not a code"]), ("required_expertise_tags", [1]),
    ("minimum_expertise_matches", 0), ("minimum_expertise_matches", 2),
    ("category_expertise_tags", {"NEW_PROGRAMME": []}), ("category_expertise_tags", []),
    ("source_status", "VERIFIED"), ("assumption_code", "OFFICIAL")])
def test_malformed_or_unlabelled_policies_fail_closed(field, value):
    raw = dict(RAW_POLICY, **{field: value})
    with pytest.raises(ValidationFailed):
        SelectorPolicy.from_mapping(raw)
    with pytest.raises(ValidationFailed):
        validate_selector(raw)


def test_missing_or_unknown_policy_fields_fail_closed_and_legacy_pool_still_valid():
    for raw in (None, {}, dict(RAW_POLICY, extra=True)):
        with pytest.raises(ValidationFailed):
            SelectorPolicy.from_mapping(raw)
    pool = dict(region_rule="SAME_REGION", slot_parts=["AM", "PM"],
        coi_reasons={key: key for key in ("INSTITUTION_LINK", "PRIOR_ENGAGEMENT", "RECUSAL")},
        source_status="DEMO_ASSUMPTION", assumption_code="EXPERT_POLICY_UNCONFIRMED")
    assert "selector" not in validate_config(dict(expert_pool=pool))
    assert validate_config(dict(expert_pool=dict(pool, selector=RAW_POLICY)))["selector"]["panel_size"] == 3


def workload_benchmark():
    """Same 10 equally qualified DEMO experts, same dates/eligibility, 100 requests, N=3."""
    base = request(size=3, count=10)
    results = {}
    for algorithm in ("SIMULATED_SELECTOR", "NAIVE_FIRST_FIT"):
        history = ()
        loads = Counter({expert.id: 0 for expert in base.eligibility.experts})
        for index in range(100):
            day = DAY + timedelta(days=index)
            facts = replace(base.eligibility, id=uid(10000 + index), earliest_date=day, due_by=day,
                availability=tuple(AvailabilityFact(e.id, day, "AM", True) for e in base.eligibility.experts),
                reservations=frozenset((a.expert_id, a.date, a.slot_part) for a in history))
            snapshot = replace(base, eligibility=facts, assignments=history)
            panel = select_panel(snapshot, day, "AM").panel if algorithm == "SIMULATED_SELECTOR" else tuple(e.id for e in eligible_experts(facts, day, "AM")[:3])
            assert len(panel) == len(set(panel)) == 3
            loads.update(panel)
            history += tuple(AssignmentFact(uid(20000 + index), expert, day, "AM") for expert in panel)
        values = list(loads.values())
        results[algorithm] = dict(assignments=sum(values), loads=values, spread=max(values) - min(values),
            variance_numerator=len(values) * sum(value * value for value in values) - sum(values) ** 2)
    return results


def test_workload_balance_improves_over_100_requests_against_first_fit():
    measured = workload_benchmark()
    selector, naive = measured["SIMULATED_SELECTOR"], measured["NAIVE_FIRST_FIT"]
    assert selector["assignments"] == naive["assignments"] == 300
    assert selector["loads"] == [30] * 10 and selector["spread"] == 0
    assert naive["spread"] == 100 and selector["variance_numerator"] < naive["variance_numerator"]
