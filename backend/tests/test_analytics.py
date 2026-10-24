"""Dashboards reconcile with what was actually filed, and are scoped by role and region."""
import json

from app.deadlines.wiring import clock
from conftest import NORTHFIELD, SUNRISE, headers

SUNRISE_H = headers("INSTITUTION", SUNRISE)
NORTHFIELD_H = headers("INSTITUTION", NORTHFIELD, user="00000000-0000-4000-9000-000000000004")
BUREAU = headers("BUREAU_HEAD", user="00000000-0000-4000-9000-000000000007")
RO_SOUTH = {**headers("RO_OFFICER", user="00000000-0000-4000-9000-000000000005"), "X-Demo-Region": "Southern"}


def file(client, h, inst, submit=True, category="NEW_PROGRAMME"):
    app_id = client.post("/api/applications", headers=h, json={
        "institution_id": str(inst), "category": category, "academic_year": "2027-28"}).json()["id"]
    if submit:
        assert client.post(f"/api/applications/{app_id}/submit", headers=h).status_code == 200
    return app_id


def section(body, key):
    return next(s for s in body["sections"] if s["key"] == key)


def test_national_dashboard_reconciles_with_filed_applications(client):
    file(client, SUNRISE_H, SUNRISE)
    file(client, SUNRISE_H, SUNRISE, submit=False)
    file(client, NORTHFIELD_H, NORTHFIELD)
    body = client.get("/api/analytics/dashboard", headers=BUREAU).json()
    apps = section(body, "applications")["data"]
    assert apps["total"] == 3
    assert apps["by_status"] == {"IN_PROCESS": 2, "DRAFT": 1}
    assert apps["by_stage"] == {"SCRUTINY": 2}
    assert apps["by_region"] == {"Southern": 2, "Northern": 1}
    assert section(body, "deadlines")["data"]["opened"] == 2
    assert section(body, "alerts")["status"] == "AVAILABLE"


def test_missing_data_is_labelled_not_invented(client):
    body = client.get("/api/analytics/dashboard", headers=BUREAU).json()
    for key in ("workload", "evc", "compliance"):
        s = section(body, key)
        assert s["status"] == "NOT_AVAILABLE" and s["depends_on"] and "data" not in s


def test_regional_officer_sees_only_their_region(client):
    file(client, SUNRISE_H, SUNRISE)
    file(client, NORTHFIELD_H, NORTHFIELD)
    body = client.get("/api/analytics/dashboard", headers=RO_SOUTH).json()
    assert body["scope"]["region"] == "Southern"
    assert section(body, "applications")["data"]["by_region"] == {"Southern": 1}
    assert section(body, "alerts")["status"] == "NOT_AVAILABLE"
    assert client.get("/api/analytics/dashboard?region=Northern", headers=RO_SOUTH).status_code == 403


def test_institutions_have_no_dashboard(client):
    assert client.get("/api/analytics/dashboard", headers=SUNRISE_H).status_code == 403
    assert client.get("/api/analytics/scorecard", headers=SUNRISE_H).status_code == 403


def test_ageing_follows_the_system_clock(client):
    file(client, SUNRISE_H, SUNRISE)
    clock.advance(10)
    buckets = section(client.get("/api/analytics/dashboard", headers=BUREAU).json(), "ageing")["data"]["buckets"]
    assert buckets["8-30 days"] == 1 and buckets["0-7 days"] == 0
    clock.advance(25)
    deadlines = section(client.get("/api/analytics/dashboard", headers=BUREAU).json(), "deadlines")["data"]
    assert deadlines["due_date_passed"] == 1           # 30-day processing clock


def test_scorecard_without_answer_keys_shows_no_accuracy(client, tmp_path, monkeypatch):
    monkeypatch.setenv("ANSWER_KEYS_DIR", str(tmp_path))
    file(client, SUNRISE_H, SUNRISE)
    items = {i["key"]: i for i in client.get("/api/analytics/scorecard", headers=BUREAU).json()["items"]}
    assert items["ledger_integrity"]["kind"] == "VERIFIED_NOW" and items["ledger_integrity"]["result"]["ok"]
    assert items["replay_consistency"]["result"]["ok"] is True
    for key in ("routing", "ocr", "alerts"):
        assert items[key]["kind"] == "NOT_EVALUATED" and "result" not in items[key]


def test_scorecard_evaluates_answer_keys_when_present(client, tmp_path, monkeypatch):
    monkeypatch.setenv("ANSWER_KEYS_DIR", str(tmp_path))
    (tmp_path / "routing.json").write_text(json.dumps({"source": "test fixture", "cases": [
        {"category": "NEW_PROGRAMME", "expected_stages": ["SCRUTINY", "EVC", "SHC"]},
        {"category": "EOA_SELF_DISCLOSURE", "expected_stages": ["SCRUTINY"]},      # deliberately wrong
    ]}))
    (tmp_path / "ocr.json").write_text(json.dumps({"source": "test fixture", "cases": [
        {"id": "1", "field": "lease_end", "expected": "2030-03-31", "predicted": "2030-03-31"},
        {"id": "2", "field": "lease_end", "expected": "2031-01-01", "predicted": "2031-07-01"},
    ]}))
    items = {i["key"]: i for i in client.get("/api/analytics/scorecard", headers=BUREAU).json()["items"]}
    routing = items["routing"]["result"]
    assert (routing["cases"], routing["correct"], routing["accuracy"]) == (2, 1, 0.5)
    assert routing["mismatches"][0]["got"] == ["SELF_DISCLOSURE"]
    assert items["ocr"]["result"] == {"lease_end": {"cases": 2, "exact_match": 0.5}}


def test_events_the_dashboard_does_not_understand_make_it_partial(client):
    """If Person 1 stores a new kind of workflow event, stage counts must not silently go stale."""
    from sqlalchemy import text
    from app.platform.db import get_engine
    file(client, SUNRISE_H, SUNRISE)
    with get_engine().begin() as c:   # simulate a future event type; test-only direct insert
        c.execute(text("INSERT INTO plat.domain_event (id, at, aggregate_type, aggregate_id, event_type, event_version, "
                       "actor_id, role, payload) VALUES (gen_random_uuid(), now(), 'application', gen_random_uuid(), "
                       "'wf.stage_changed', 1, gen_random_uuid(), 'SYSTEM', '{}')"))
    apps = section(client.get("/api/analytics/dashboard", headers=BUREAU).json(), "applications")
    assert apps["status"] == "PARTIAL" and "1 wf.stage_changed event(s)" in apps["note"]
    assert apps["data"]["total"] == 1
