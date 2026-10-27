"""Who may read deadlines and alerts by region: a regional officer sees its own region's and is refused others."""
from uuid import UUID

import pytest
from sqlalchemy import select

from app.deadlines.models import Deadline
from app.platform import policy
from app.platform.db import new_session
from app.platform.demo_seed import seed_directory
from backend.tests.intake_test_helpers import ensure_intake_rules, provide_fixture_items
from conftest import NORTHFIELD, SUNRISE, headers
from contracts.enums import Role
from contracts.types import Principal, ResourceRef

INST = headers("INSTITUTION", SUNRISE)
NORTH_INST = headers("INSTITUTION", NORTHFIELD, user="00000000-0000-4000-9000-000000000004")
SOUTH_RO = {**headers("RO_OFFICER", user="00000000-0000-4000-9000-000000000005"), "X-Demo-Region": "Southern"}
NORTH_RO = {**headers("RO_OFFICER", user="00000000-0000-4000-9000-000000000008"), "X-Demo-Region": "Northern"}
BUREAU_HEAD = headers("BUREAU_HEAD", user="00000000-0000-4000-9000-000000000007")


@pytest.fixture
def env(client):
    seed_directory()
    return client


def submit(client, inst=SUNRISE, h=INST):
    ensure_intake_rules(client)
    app_id = client.post("/api/applications", headers=h, json={
        "institution_id": str(inst), "category": "NEW_PROGRAMME", "academic_year": "2027-28"}).json()["id"]
    provide_fixture_items(app_id)
    assert client.post(f"/api/applications/{app_id}/submit", headers=h, json={"dsc_present": True}).status_code == 200
    return UUID(app_id)


def deadline_ids(app_id) -> list[str]:
    with new_session() as s:
        return [str(i) for i in s.scalars(select(Deadline.id).where(Deadline.subject_id == app_id))]


def test_a_regional_officer_explains_its_own_regions_deadlines_only(env):
    south = deadline_ids(submit(env))[0]
    assert env.get(f"/api/deadlines/{south}/explain", headers=SOUTH_RO).status_code == 200
    assert env.get(f"/api/deadlines/{south}/explain", headers=NORTH_RO).status_code == 403
    assert env.get(f"/api/deadlines/{south}/explain", headers=BUREAU_HEAD).status_code == 200


def test_a_regional_officers_deadline_list_is_its_own_region(env):
    south_app, north_app = submit(env), submit(env, NORTHFIELD, NORTH_INST)
    listed = {d["id"] for d in env.get("/api/deadlines", headers=SOUTH_RO).json()}
    assert set(deadline_ids(south_app)) <= listed
    assert not listed & set(deadline_ids(north_app))
    everything = {d["id"] for d in env.get("/api/deadlines", headers=BUREAU_HEAD).json()}
    assert set(deadline_ids(south_app)) | set(deadline_ids(north_app)) <= everything


def test_asking_for_another_regions_alerts_is_refused_not_rewritten(env):
    assert env.get("/api/alerts", headers=SOUTH_RO, params={"region": "Southern"}).status_code == 200
    assert env.get("/api/alerts", headers=SOUTH_RO, params={"region": "Northern"}).status_code == 403
    assert env.get("/api/alerts", headers=BUREAU_HEAD, params={"region": "Northern"}).status_code == 200


@pytest.mark.parametrize("role, region, allowed", [
    (Role.INSTITUTION, None, True), (Role.RO_OFFICER, "Southern", True), (Role.BUREAU_OFFICER, None, True),
    (Role.BUREAU_HEAD, None, True), (Role.SCRUTINY_COMMITTEE, None, False), (Role.AUDITOR, None, False),
    (Role.RO_OFFICER, "Northern", False),
])
def test_case_officers_may_retry_a_scan(role, region, allowed):
    who = Principal(user_id=UUID(int=9), role=role, region=region,
                    institution_id=SUNRISE if role == Role.INSTITUTION else None)
    doc = ResourceRef("document", UUID(int=1), SUNRISE, "Southern")
    assert (policy.decide(who, "document.rescan", doc, demo_mode=False) is None) == allowed
