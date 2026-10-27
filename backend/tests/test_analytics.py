"""Dashboards reconcile with what was actually filed, and are scoped by role and region."""
import json

from app.deadlines.wiring import clock
from backend.tests.intake_test_helpers import ensure_intake_rules, provide_fixture_items
from conftest import NORTHFIELD, SUNRISE, headers

SUNRISE_H = headers("INSTITUTION", SUNRISE)
NORTHFIELD_H = headers("INSTITUTION", NORTHFIELD, user="00000000-0000-4000-9000-000000000004")
BUREAU = headers("BUREAU_HEAD", user="00000000-0000-4000-9000-000000000007")
RO_SOUTH = {**headers("RO_OFFICER", user="00000000-0000-4000-9000-000000000005"), "X-Demo-Region": "Southern"}


def file(client, h, inst, submit=True, category="NEW_PROGRAMME"):
    ensure_intake_rules(client)
    app_id = client.post("/api/applications", headers=h, json={
        "institution_id": str(inst), "category": category, "academic_year": "2027-28"}).json()["id"]
    if submit:
        provide_fixture_items(app_id)
        assert client.post(f"/api/applications/{app_id}/submit", headers=h, json={"dsc_present": True}).status_code == 200
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
    for key in ("routing", "ocr", "alerts", "document_scanning", "four_eyes"):
        assert items[key]["kind"] == "NOT_EVALUATED" and items[key]["result"] is None, key
        assert items[key]["note"] and items[key]["method"] and items[key]["outcome"] is None, key
    assert "answer key" in items["routing"]["note"]


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


# ---- correctness under bad data, and caching (P3-17) ----

def _insert_event(payload_sql, event_type="wf.application_created"):
    from sqlalchemy import text
    from app.platform.db import get_engine
    with get_engine().begin() as c:
        c.execute(text("INSERT INTO plat.domain_event (id, at, aggregate_type, aggregate_id, event_type, event_version, "
                       f"actor_id, role, payload) VALUES (gen_random_uuid(), now(), 'application', gen_random_uuid(), "
                       f"'{event_type}', 1, gen_random_uuid(), 'SYSTEM', {payload_sql})"))


ORPHAN = ("jsonb_build_object('application_id', gen_random_uuid(), 'institution_id', gen_random_uuid(), "
          "'category', 'NEW_PROGRAMME', 'academic_year', '2027-28')")


def test_an_event_without_a_case_record_does_not_break_the_dashboard(client):
    file(client, SUNRISE_H, SUNRISE)
    _insert_event(ORPHAN)
    body = client.get("/api/analytics/dashboard", headers=BUREAU)
    assert body.status_code == 200
    apps = section(body.json(), "applications")
    assert apps["status"] == "PARTIAL" and "1 without a case record" in apps["note"]
    assert apps["data"]["by_region"] == {"Southern": 1, "Unknown (no case record)": 1}
    # a regional view never counts a case whose region it cannot confirm
    south = section(client.get("/api/analytics/dashboard", headers=RO_SOUTH).json(), "applications")
    assert south["data"]["total"] == 1 and "Unknown (no case record)" not in south["data"]["by_region"]


def test_an_unreadable_event_is_reported_not_a_crash(client):
    file(client, SUNRISE_H, SUNRISE)
    _insert_event("'{}'::jsonb")
    apps = section(client.get("/api/analytics/dashboard", headers=BUREAU).json(), "applications")
    assert apps["status"] == "PARTIAL" and "1 unreadable" in apps["note"]
    from app.platform import replay
    r = replay.replay()
    assert r["verdict"] == "MISMATCH" and r["ok"] is False
    assert any(g["kind"] == "UNREADABLE_EVENT" and g["error"] == "KeyError" for g in r["gaps"])
    items = {i["key"]: i for i in client.get("/api/analytics/scorecard", headers=BUREAU).json()["items"]}
    assert items["replay_consistency"]["result"]["verdict"] == "MISMATCH"


def test_dashboard_projections_are_reused_until_the_log_changes(client, monkeypatch):
    from app.analytics import service
    calls = []
    real = service.stored_events
    monkeypatch.setattr(service, "stored_events", lambda s: calls.append(1) or real(s))
    file(client, SUNRISE_H, SUNRISE)
    client.get("/api/analytics/dashboard", headers=BUREAU)
    client.get("/api/analytics/dashboard", headers=BUREAU)
    assert len(calls) == 1
    file(client, NORTHFIELD_H, NORTHFIELD)
    body = client.get("/api/analytics/dashboard", headers=BUREAU).json()
    assert len(calls) == 2 and section(body, "applications")["data"]["total"] == 2


def test_ageing_is_recomputed_from_cached_projections(client):
    file(client, SUNRISE_H, SUNRISE)
    client.get("/api/analytics/dashboard", headers=BUREAU)
    clock.advance(40)
    buckets = section(client.get("/api/analytics/dashboard", headers=BUREAU).json(), "ageing")["data"]["buckets"]
    assert buckets["31-60 days"] == 1


def test_scorecard_reports_assurance_with_the_ledger_result(client):
    file(client, SUNRISE_H, SUNRISE)
    items = {i["key"]: i for i in client.get("/api/analytics/scorecard", headers=BUREAU).json()["items"]}
    assert items["ledger_integrity"]["result"]["assurance"] == "CHAIN_ONLY"


# ---- cache correctness and scale (P3-21) ----

def test_a_region_change_reaches_regional_dashboards_immediately(client):
    """A case moved to another regional office must not stay visible to its old office from a cache."""
    from sqlalchemy import text
    from app.platform.db import get_engine
    file(client, SUNRISE_H, SUNRISE)
    assert section(client.get("/api/analytics/dashboard", headers=RO_SOUTH).json(), "applications")["data"]["total"] == 1
    with get_engine().begin() as c:   # test-only: simulate the workflow module moving the institution
        c.execute(text(f"UPDATE wf.institution SET ro_region = 'Northern' WHERE id = '{SUNRISE}'"))
    assert section(client.get("/api/analytics/dashboard", headers=RO_SOUTH).json(), "applications")["data"]["total"] == 0
    north = {**headers("RO_OFFICER", user="00000000-0000-4000-9000-000000000008"), "X-Demo-Region": "Northern"}
    assert section(client.get("/api/analytics/dashboard", headers=north).json(), "applications")["data"]["total"] == 1


def test_an_empty_system_shows_zero_applications_and_no_invented_figures(client):
    body = client.get("/api/analytics/dashboard", headers=BUREAU).json()
    apps = section(body, "applications")
    assert apps["data"]["total"] == 0 and apps["data"]["by_stage"] == {}
    for key in ("workload", "evc", "compliance"):
        assert "data" not in section(body, key)


def test_concurrent_requests_while_events_arrive_stay_consistent(client):
    import threading
    file(client, SUNRISE_H, SUNRISE)
    totals, errors = [], []

    def read():
        try:
            totals.append(section(client.get("/api/analytics/dashboard", headers=BUREAU).json(),
                                  "applications")["data"]["total"])
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=read) for _ in range(6)]
    for t in threads:
        t.start()
    file(client, NORTHFIELD_H, NORTHFIELD)
    for t in threads:
        t.join()
    assert errors == [] and set(totals) <= {1, 2}
    assert section(client.get("/api/analytics/dashboard", headers=BUREAU).json(), "applications")["data"]["total"] == 2


def test_dashboard_scale_with_synthetic_events(client, monkeypatch):
    """300 applications from 3 institutions: one rebuild, then cached; region lookups are per institution."""
    import time
    from app.analytics import service
    from app.intake import service as intake
    from app.platform.db import unit_of_work
    from app.platform.registry import port
    from contracts.enums import Role
    from contracts.ports import CasePort
    from contracts.types import Principal
    from uuid import UUID
    riverbend = UUID("00000000-0000-4000-8000-000000000003")
    for i in range(300):
        inst = (SUNRISE, NORTHFIELD, riverbend)[i % 3]
        with unit_of_work(Principal(UUID(int=i + 1), Role.INSTITUTION, None, inst)) as uow:
            intake.create_application(uow, inst, "NEW_PROGRAMME", "2027-28")

    lookups = []
    real = port(CasePort)

    class Counting:
        def lookup(self, session, application_id):
            lookups.append(application_id)
            return real.lookup(session, application_id)

    monkeypatch.setattr(service, "port", lambda p: Counting() if p is CasePort else port(p))
    t0 = time.perf_counter()
    first = client.get("/api/analytics/dashboard", headers=BUREAU).json()
    t1 = time.perf_counter()
    rebuild_lookups = len(lookups)
    lookups.clear()
    second = client.get("/api/analytics/dashboard", headers=BUREAU).json()
    t2 = time.perf_counter()
    assert section(first, "applications")["data"]["total"] == 300 == section(second, "applications")["data"]["total"]
    assert section(second, "applications")["data"]["by_region"] == {"Southern": 100, "Northern": 100, "Western": 100}
    assert rebuild_lookups == 300 + 3          # existence check once per application, regions once per institution
    assert len(lookups) == 3                   # cached: regions only, one per institution
    print(f"\n[observed] 300 applications: rebuild {t1 - t0:.3f}s, cached {t2 - t1:.3f}s")
