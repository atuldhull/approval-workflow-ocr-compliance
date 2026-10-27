"""Who may upload documents and read, review and confirm their extracted facts.

The document endpoints belong to Person 2; these pin the policy they call, so the endpoints can rely on it.
"""
from uuid import uuid4

import pytest

from app.platform import policy
from conftest import NORTHFIELD, SUNRISE
from contracts.enums import Role
from contracts.types import Principal, ResourceRef

R = Role
DOC = ResourceRef("document", id=uuid4(), owner_institution_id=SUNRISE, region="Southern")


def who(role, institution=None, region=None):
    return Principal(user_id=uuid4(), role=role, institution_id=institution, region=region)


SUNRISE_INST = who(R.INSTITUTION, SUNRISE)
NORTH_INST = who(R.INSTITUTION, NORTHFIELD)
COMMITTEE = who(R.SCRUTINY_COMMITTEE)
RO_SOUTH = who(R.RO_OFFICER, region="Southern")
RO_NORTH = who(R.RO_OFFICER, region="Northern")
BUREAU_OFFICER = who(R.BUREAU_OFFICER)
BUREAU_HEAD = who(R.BUREAU_HEAD)
AUDITOR = who(R.AUDITOR)


def allowed(principal, action, resource=DOC, require_assignment=False):
    return policy.decide(principal, action, resource, demo_mode=False, require_assignment=require_assignment) is None


@pytest.mark.parametrize("action, yes, no", [
    ("document.upload", [SUNRISE_INST], [COMMITTEE, RO_SOUTH, BUREAU_OFFICER, BUREAU_HEAD, AUDITOR]),
    ("document.facts.read", [SUNRISE_INST, COMMITTEE, RO_SOUTH, BUREAU_OFFICER, BUREAU_HEAD, AUDITOR], []),
    ("document.fact.review", [COMMITTEE, RO_SOUTH], [SUNRISE_INST, BUREAU_OFFICER, BUREAU_HEAD, AUDITOR]),
    ("document.fact.confirm", [COMMITTEE, RO_SOUTH, BUREAU_OFFICER, BUREAU_HEAD], [SUNRISE_INST, AUDITOR]),
])
def test_document_roles(action, yes, no):
    assert all(allowed(p, action) for p in yes)
    assert not any(allowed(p, action) for p in no)


def test_institutions_never_confirm_their_own_facts():
    assert not allowed(SUNRISE_INST, "document.fact.confirm")


def test_an_institution_only_reaches_its_own_documents():
    assert not allowed(NORTH_INST, "document.upload")
    assert not allowed(NORTH_INST, "document.facts.read")


def test_a_document_whose_owner_is_unknown_is_refused_to_institutions():
    unknown = ResourceRef("document", id=uuid4(), region="Southern")
    assert not allowed(SUNRISE_INST, "document.facts.read", unknown)


def test_regional_officers_stay_in_their_region_and_must_state_it():
    assert allowed(RO_SOUTH, "document.fact.review")
    assert not allowed(RO_NORTH, "document.fact.review")
    assert not allowed(RO_SOUTH, "document.facts.read", ResourceRef("document", id=uuid4(), owner_institution_id=SUNRISE))


def test_committee_document_access_follows_case_assignment():
    assert not allowed(COMMITTEE, "document.fact.review", require_assignment=True)
