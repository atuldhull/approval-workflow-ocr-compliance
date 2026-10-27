"""The eligibility core consumes explicit facts; it never reads clocks, registries or DBs."""
from dataclasses import replace
from datetime import date, timedelta
from itertools import permutations
from uuid import UUID

import pytest

from app.evc.eligibility import AvailabilityFact, EligibilityRequest, ExpertCandidate, ExpertPolicy, eligible_experts
from app.workflow.expert_pool_config import validate_config
from contracts.errors import ValidationFailed
from contracts.fakes import FakePersonalData

DAY = date(2026, 7, 1)
POLICY = dict(region_rule="SAME_REGION", slot_parts=["AM", "PM"],
              coi_reasons={key: key for key in ("INSTITUTION_LINK", "PRIOR_ENGAGEMENT", "RECUSAL")},
              source_status="DEMO_ASSUMPTION", assumption_code="EXPERT_POLICY_UNCONFIRMED")


def uid(value):
    return UUID(int=value)


def snapshot():
    experts = tuple(ExpertCandidate(uid(i), uid(i + 100), "SOUTHERN" if i != 6 else "NORTHERN", ("DEMO",), i != 7)
                    for i in range(1, 8))
    available = tuple(AvailabilityFact(uid(i), DAY, "AM", i != 3) for i in range(1, 8) if i != 4)
    return EligibilityRequest(uid(99), uid(98), "Southern", "aph-2024-27@r1", DAY, DAY + timedelta(days=7),
        ExpertPolicy.from_mapping(POLICY), experts, available, frozenset({(uid(2), uid(98))}), frozenset({(uid(5), DAY, "AM")}))


def ids(request, day=DAY, part="AM"):
    return [row.id.int for row in eligible_experts(request, day, part)]


def test_all_hard_exclusions_in_one_snapshot():
    assert ids(snapshot()) == [1]  # COI / false / missing availability / booked / region / inactive.


@pytest.mark.parametrize("mode,expected", [("SAME_REGION", [1]), ("ANY_REGION", [1, 6]), ("OTHER_REGION", [6])])
def test_region_rule_is_configurable_and_case_insensitive(mode, expected):
    request = snapshot()
    assert ids(replace(request, policy=replace(request.policy, region_rule=mode))) == expected


def test_coi_is_institution_specific_and_legacy_source_independent():
    assert ids(replace(snapshot(), conflicts=frozenset({(uid(2), uid(97))}))) == [1, 2]


@pytest.mark.parametrize("field", ["availability", "reservations"])
def test_availability_and_reservations_are_date_and_part_specific(field):
    request = snapshot()
    if field == "availability":
        request = replace(request, availability=tuple(replace(a, slot_part="PM") for a in request.availability))
        assert ids(request) == []
    else:
        request = replace(request, reservations=frozenset({(uid(5), DAY, "PM"), (uid(5), DAY + timedelta(days=1), "AM")}))
        assert ids(request) == [1, 5]


def test_determinism_under_permuted_inputs_and_no_mutation():
    request = replace(snapshot(), conflicts=frozenset(), reservations=frozenset())
    original = request
    expected = ids(request)
    for prefix in permutations(request.experts[:3]):
        shuffled = replace(request, experts=request.experts[3:] + prefix, availability=tuple(reversed(request.availability)))
        assert ids(shuffled) == expected
    assert request == original


def test_conflicting_availability_fails_closed_and_request_window_is_respected():
    request = snapshot()
    assert ids(replace(request, availability=request.availability + (AvailabilityFact(uid(1), DAY, "AM", False),))) == []
    assert ids(request, DAY - timedelta(days=1)) == []
    assert ids(request, request.due_by + timedelta(days=1)) == []
    with pytest.raises(ValidationFailed, match="SLOT_PART"):
        ids(request, part="EVENING")


@pytest.mark.parametrize("key,value", [("region_rule", "UNVERIFIED"), ("slot_parts", ["AM"]),
    ("coi_reasons", {}), ("source_status", "VERIFIED"), ("assumption_code", "OFFICIAL")])
def test_yaml_policy_rejects_unknown_or_unlabelled_values(key, value):
    raw = dict(POLICY, **{key: value})
    with pytest.raises(ValidationFailed):
        validate_config(dict(expert_pool=raw))
    with pytest.raises(ValidationFailed):
        ExpertPolicy.from_mapping(raw)


def test_yaml_policy_missing_versus_explicit_empty_and_unknown_keys():
    assert validate_config({}) == {}
    for raw in ({}, [], dict(POLICY, extra=True)):
        with pytest.raises(ValidationFailed):
            validate_config(dict(expert_pool=raw))
    with pytest.raises(ValidationFailed):
        ExpertPolicy.from_mapping({})


def test_personal_fake_can_supply_reproducible_opaque_references():
    fake = FakePersonalData(reference_factory=lambda: uid(1))
    assert fake.store(None, dict(name="DEMO"), "EVC_EXPERT_CONTACT") == uid(1)
    assert fake.rows == {uid(1): dict(name="DEMO")}
