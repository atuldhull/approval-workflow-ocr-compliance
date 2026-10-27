"""Optional Idempotency-Key on Person 1's POST endpoints: replay, 422 on a changed body, 409 behind a held key."""
from datetime import date, timedelta
from uuid import UUID, NAMESPACE_URL, uuid5

import pytest
from sqlalchemy import func, select, text

from app.platform import idempotency
from app.platform.db import new_session, unit_of_work
from app.platform.models import DomainEvent
from conftest import SUNRISE, headers
from contracts.enums import Role
from contracts.types import Principal

INST = headers("INSTITUTION", SUNRISE)
OFFICER_USER = "00000000-0000-4000-9000-0000000000c1"
OFFICER = headers("SCRUTINY_COMMITTEE", user=OFFICER_USER)
BUREAU = headers("BUREAU_OFFICER")
REF = "00000000-0000-4000-8000-000000000099"
DRAFT = {"institution_id": str(SUNRISE), "category": "NEW_PROGRAMME", "academic_year": "2027-28"}


@pytest.fixture
def api(client):
    with client:
        yield client
    with new_session() as session, session.begin():
        session.execute(text("TRUNCATE evc.assignment_expert, evc.assignment, evc.availability, evc.coi, "
                             "evc.slot, evc.schedule_run_request, evc.schedule_run, evc.evc_request, evc.expert"))


def keyed(base, key):
    return {**base, "Idempotency-Key": key}


def events(kind):
    with new_session() as session:
        return session.scalar(select(func.count()).select_from(DomainEvent).where(DomainEvent.event_type == kind))


def check(api, path, actor, body, key, other_body, *, status=200, event=None):
    """First call runs; a retry replays the stored body; a different body under the same key is 422."""
    before = events(event) if event else None
    first = api.post(path, headers=keyed(actor, key), json=body)
    assert first.status_code == status, first.text
    assert "Idempotent-Replayed" not in first.headers
    again = api.post(path, headers=keyed(actor, key), json=body)
    assert again.status_code == status and again.headers["Idempotent-Replayed"] == "true"
    assert again.json() == first.json()
    changed = api.post(path, headers=keyed(actor, key), json=other_body)
    assert changed.status_code == 422 and "different request" in changed.json()["detail"]
    if event:
        assert events(event) == before + 1
    return first.json()


def submitted(api):
    created = api.post("/api/applications", headers=INST, json={**DRAFT, "submit": True, "dsc_present": True,
        "items": [{"item_key": "DEMO_CORE_REFERENCE", "state": "PROVIDED", "document_ref": REF}]})
    assert created.status_code == 201, created.text
    return created.json()["id"]


def test_intake_create_items_and_submit(api):
    draft = check(api, "/api/applications", INST, DRAFT, "intake-create-0001",
                  {**DRAFT, "academic_year": "2028-29"}, status=201, event="wf.application_created")
    items = {"items": [{"item_key": "DEMO_CORE_REFERENCE", "state": "PROVIDED", "document_ref": REF}]}
    check(api, f"/api/applications/{draft['id']}/items", INST, items, "intake-items-0001",
          {"items": [{"item_key": "DEMO_CORE_REFERENCE", "state": "MISSING"}]})
    check(api, f"/api/applications/{draft['id']}/submit", INST, {"dsc_present": True}, "intake-submit-0001",
          {"dsc_present": False}, event="wf.application_submitted")
    # A blocked submission is not stored: after fixing the items the same key runs the command.
    other = api.post("/api/applications", headers=INST, json=DRAFT).json()["id"]
    blocked = api.post(f"/api/applications/{other}/submit", headers=keyed(INST, "intake-submit-0002"), json={"dsc_present": True})
    assert blocked.status_code == 422 and blocked.json()["reason_code"] == "MANDATORY_ITEMS_MISSING"
    api.post(f"/api/applications/{other}/items", headers=INST, json=items)
    retried = api.post(f"/api/applications/{other}/submit", headers=keyed(INST, "intake-submit-0002"), json={"dsc_present": True})
    assert retried.status_code == 200 and "Idempotent-Replayed" not in retried.headers


def test_case_actions_keep_expected_version_and_replay(api):
    case_id = submitted(api)
    committee = check(api, f"/api/cases/{case_id}/committees", OFFICER,
        {"type": "SCRUTINY", "members": [{"user_ref": OFFICER_USER, "role": "CHAIR"}]}, "committee-form-0001",
        {"type": "EVC", "members": [{"user_ref": OFFICER_USER, "role": "CHAIR"}]}, status=201, event="wf.committee_formed")
    body = {"action": "record_deficiency", "expected_version": 1, "reason_code": "DEMO_MISSING_EVIDENCE",
            "payload": {"item_keys": ["DEMO_CORE_REFERENCE"]}}
    result = check(api, f"/api/cases/{case_id}/actions", OFFICER, body, "case-action-0001",
                   {**body, "payload": {"item_keys": ["DEMO_ADDITIONAL_REFERENCE"]}}, event="wf.deficiency_recorded")
    assert result["stage"] == "DEFICIENT" and result["version"] == 2
    # A new key with the consumed version is still an optimistic-concurrency conflict.
    stale = api.post(f"/api/cases/{case_id}/actions", headers=keyed(OFFICER, "case-action-0002"), json=body)
    assert stale.status_code == 409 and stale.json()["detail"] == "VERSION_CONFLICT"
    # A refused action is not stored, so the same key can run once the guard passes.
    rounds = api.get(f"/api/cases/{case_id}/deficiencies", headers=INST).json()
    item = rounds["rounds"][-1]["items"][0]["id"]
    comply = {"action": "submit_compliance", "expected_version": 2, "payload": {"responses": []}}
    refused = api.post(f"/api/cases/{case_id}/actions", headers=keyed(INST, "case-comply-0001"), json=comply)
    assert refused.status_code == 422
    comply["payload"]["responses"] = [{"item_id": item, "response_ref": REF}]
    refused = api.post(f"/api/cases/{case_id}/actions", headers=keyed(INST, "case-comply-0001"), json=comply)
    assert refused.status_code == 200, refused.text

    # Committee task, observation and report writes.
    task = check(api, f"/api/committees/{committee['id']}/tasks", OFFICER,
                 {"title_key": "REVIEW_RESPONSES", "assignee_user_ref": OFFICER_USER}, "committee-task-0001",
                 {"title_key": "PREPARE_REPORT", "assignee_user_ref": OFFICER_USER}, status=201, event="wf.task_assigned")
    check(api, f"/api/tasks/{task['id']}/observations", OFFICER, {"body": "Fictional DEMO observation."},
          "committee-note-0001", {"body": "Another fictional note."}, status=201, event="wf.observation_added")
    report = check(api, f"/api/committees/{committee['id']}/reports", OFFICER, {"content": "Fictional DEMO report."},
                   "committee-report-01", {"content": "Changed."}, status=201, event="wf.report_version_added")
    assert report["version_no"] == 1


def test_deficiency_review_replays(api):
    case_id = submitted(api)
    api.post(f"/api/cases/{case_id}/committees", headers=OFFICER,
             json={"type": "SCRUTINY", "members": [{"user_ref": OFFICER_USER, "role": "CHAIR"}]})
    record = api.post(f"/api/cases/{case_id}/actions", headers=OFFICER, json={"action": "record_deficiency",
        "expected_version": 1, "reason_code": "DEMO_MISSING_EVIDENCE", "payload": {"item_keys": ["DEMO_CORE_REFERENCE"]}})
    assert record.status_code == 200, record.text
    rounds = api.get(f"/api/cases/{case_id}/deficiencies", headers=INST).json()
    item = rounds["rounds"][-1]["items"][0]["id"]
    assert api.post(f"/api/cases/{case_id}/actions", headers=INST, json={"action": "submit_compliance",
        "expected_version": 2, "payload": {"responses": [{"item_id": item, "response_ref": REF}]}}).status_code == 200
    assert api.post(f"/api/cases/{case_id}/actions", headers=OFFICER,
                    json={"action": "start_rescrutiny", "expected_version": 3}).status_code == 200
    review = {"expected_version": 4, "decisions": [{"item_id": item, "state": "REJECTED",
                                                    "reason_code": "DEMO_RESPONSE_REJECTED"}]}
    other = {**review, "decisions": [{**review["decisions"][0], "state": "ACCEPTED", "reason_code": "DEMO_RESPONSE_ACCEPTED"}]}
    check(api, f"/api/cases/{case_id}/deficiencies/{rounds['rounds'][-1]['id']}/review", OFFICER, review,
          "deficiency-review-01", other, event="wf.deficiency_item_decided")


def test_evc_pool_writes(api):
    body = {"user_ref": str(uuid5(NAMESPACE_URL, "DEMO:idem-expert")), "region": "SOUTHERN", "expertise_tags": ["DEMO"]}
    expert = check(api, "/api/evc/experts", BUREAU, body, "evc-expert-0001", {**body, "expertise_tags": ["DEMO", "DEMO_DOMAIN_01"]},
                   status=201, event="evc.expert_registered")
    day = date(2026, 7, 1)
    slots = {"items": [{"date": (day + timedelta(days=d)).isoformat(), "slot_part": "AM", "available": True} for d in range(3)]}
    check(api, f"/api/evc/experts/{expert['id']}/availability", BUREAU, slots, "evc-avail-0001",
          {"items": slots["items"][:1]})
    coi = {"expert_id": expert["id"], "institution_ref": str(SUNRISE), "source": "RECUSAL", "reason_code": "RECUSAL"}
    check(api, "/api/evc/coi", BUREAU, coi, "evc-coi-00001", {**coi, "source": "INSTITUTION_LINK", "reason_code": "INSTITUTION_LINK"})


def test_a_case_action_stuck_behind_a_held_key_gets_409(api, monkeypatch):
    case_id = submitted(api)
    body = {"action": "scrutinise", "expected_version": 1}
    monkeypatch.setattr(idempotency.store, "lock_timeout_ms", 200)
    officer = Principal(UUID(OFFICER_USER), Role.SCRUTINY_COMMITTEE)
    with unit_of_work(officer) as uow:
        holder = idempotency.IdempotencyStore()
        assert holder.claim(uow, "held-action-0001", "POST", "/cases/{application_id}/actions",
                            idempotency.fingerprint({"application_id": case_id}, body)) is None
        response = api.post(f"/api/cases/{case_id}/actions", headers=keyed(OFFICER, "held-action-0001"), json=body)
        uow.session.rollback()
    assert response.status_code == 409 and "still being processed" in response.json()["detail"]
