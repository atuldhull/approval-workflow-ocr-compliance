"""Demo step 1: an institution submits; the route, the first clock and the audit trail appear together."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.platform.registry import provide
from conftest import NORTHFIELD, SUNRISE, headers
from backend.tests.intake_test_helpers import ensure_intake_rules, provide_fixture_items
from contracts.errors import Conflict
from contracts.ports import DeadlinePort

INST = headers("INSTITUTION", SUNRISE)
OFFICER = headers("SCRUTINY_COMMITTEE", user="00000000-0000-4000-9000-000000000002")
AUDITOR = headers("AUDITOR", user="00000000-0000-4000-9000-000000000003")


def create(client, category="NEW_PROGRAMME", h=INST, institution=SUNRISE):
    ensure_intake_rules(client)
    response = client.post("/api/applications", headers=h,
                       json={"institution_id": str(institution), "category": category, "academic_year": "2027-28"})
    if response.status_code == 201:
        provide_fixture_items(response.json()["id"])
    return response


def test_submission_routes_opens_clock_and_records_everything(client):
    draft = create(client)
    assert draft.status_code == 201 and draft.json()["status"] == "DRAFT"
    app_id = draft.json()["id"]

    r = client.post(f"/api/applications/{app_id}/submit", headers=INST, json={"dsc_present": True})
    assert r.status_code == 200, r.text
    app = r.json()
    assert app["status"] == "IN_PROCESS"
    assert app["current_stage"] == "SCRUTINY"
    assert app["ruleset_rev"] == "aph-2024-27@r1"
    assert [s["stage"] for s in app["route"]] == ["SCRUTINY", "EVC", "SHC"]

    deadlines = client.get(f"/api/deadlines?subject_id={app_id}", headers=OFFICER).json()
    assert len(deadlines) == 1
    d = deadlines[0]
    assert (d["rule_id"], d["clock_kind"], d["clock_owner"], d["status"]) == \
        ("AICTE_PROCESSING", "INTERNAL", "AICTE", "RUNNING")
    submitted_ist = datetime.fromisoformat(app["submitted_at"]).astimezone(ZoneInfo("Asia/Kolkata")).date()
    assert date.fromisoformat(d["due_date"]) == submitted_ist + timedelta(days=30)
    assert "demo assumption" in d["explanation"]

    timeline = client.get(f"/api/cases/{app_id}/timeline", headers=INST).json()
    assert [e["event_type"] for e in timeline] == \
        ["wf.application_created", "wf.application_submitted", "dl.deadline_opened"]

    assert client.get("/api/ledger/verify", headers=AUDITOR).json()["ok"] is True


def test_a_failure_anywhere_rolls_back_the_whole_submission(client):
    app_id = create(client).json()["id"]

    class FailingDeadlines:
        def open(self, *a, **k):
            raise Conflict("simulated failure while opening the clock")

        def close(self, *a, **k): ...
        def pause_internal(self, *a, **k): ...
        def resume_internal(self, *a, **k): ...

    provide(DeadlinePort, FailingDeadlines())
    assert client.post(f"/api/applications/{app_id}/submit", headers=INST, json={"dsc_present": True}).status_code == 409

    app = client.get(f"/api/applications/{app_id}", headers=INST).json()
    assert app["status"] == "DRAFT" and app["ruleset_rev"] is None
    events = [e["event_type"] for e in client.get(f"/api/cases/{app_id}/timeline", headers=INST).json()]
    assert events == ["wf.application_created"]
    assert client.get("/api/ledger/verify", headers=AUDITOR).json()["ok"] is True


def test_submitting_twice_is_refused(client):
    app_id = create(client).json()["id"]
    assert client.post(f"/api/applications/{app_id}/submit", headers=INST, json={"dsc_present": True}).status_code == 200
    assert client.post(f"/api/applications/{app_id}/submit", headers=INST, json={"dsc_present": True}).status_code == 409


def test_an_institution_cannot_touch_another_institutions_application(client):
    app_id = create(client).json()["id"]
    other = headers("INSTITUTION", NORTHFIELD, user="00000000-0000-4000-9000-000000000009")
    assert client.post(f"/api/applications/{app_id}/submit", headers=other, json={"dsc_present": True}).status_code == 403
    assert client.get(f"/api/cases/{app_id}/timeline", headers=other).status_code == 403
    assert create(client, h=other, institution=SUNRISE).status_code == 403


def test_officers_cannot_file_applications(client):
    assert create(client, h=OFFICER).status_code == 403


def test_categories_without_a_route_are_rejected(client):
    assert create(client, category="NOT_IN_TABLE").status_code == 422


def test_self_disclosure_route_has_a_single_stage(client):
    app_id = create(client, category="EOA_SELF_DISCLOSURE").json()["id"]
    app = client.post(f"/api/applications/{app_id}/submit", headers=INST, json={"dsc_present": True}).json()
    assert app["current_stage"] == "SELF_DISCLOSURE"
    assert [s["stage"] for s in app["route"]] == ["SELF_DISCLOSURE"]
