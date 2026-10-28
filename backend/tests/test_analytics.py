"""Dashboards reconcile with what was actually filed, and are scoped by role and region."""
import json

from app.deadlines.wiring import clock
from backend.tests.intake_test_helpers import ensure_intake_rules, provide_fixture_items
from backend.tests.test_document_validity import env  # noqa: F401
from conftest import NORTHFIELD, SUNRISE, headers

SUNRISE_H = headers("INSTITUTION", SUNRISE)
NORTHFIELD_H = headers("INSTITUTION", NORTHFIELD, user="00000000-0000-4000-9000-000000000004")
BUREAU = headers("BUREAU_HEAD", user="00000000-0000-4000-9000-000000000007")
RO_SOUTH = {**headers("RO_OFFICER", user="00000000-0000-4000-9000-000000000005"), "X-Demo-Region": "Southern"}
RO_NORTH = {**headers("RO_OFFICER", user="00000000-0000-4000-9000-000000000008"), "X-Demo-Region": "Northern"}
BUREAU_OFFICER = "00000000-0000-4000-9000-000000000006"


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


def test_every_section_is_computed_and_names_no_team(client):
    file(client, SUNRISE_H, SUNRISE)
    body = client.get("/api/analytics/dashboard", headers=BUREAU).json()
    assert [s["key"] for s in body["sections"]] == [
        "applications", "ageing", "flow", "institutions", "deadlines", "workload", "evc", "compliance", "alerts"]
    for s in body["sections"]:
        assert s["status"] == "AVAILABLE" and "data" in s and "depends_on" not in s, s
    assert "Person" not in json.dumps(body) and "entered at submission" not in json.dumps(body)


def test_workload_counts_committees_and_tasks_by_officer_within_the_region(client):
    alice, bob = "00000000-0000-4000-9000-000000000001", "00000000-0000-4000-9000-000000000002"
    committee_h = headers("SCRUTINY_COMMITTEE", user=alice)
    south = file(client, SUNRISE_H, SUNRISE)
    file(client, NORTHFIELD_H, NORTHFIELD)
    formed = client.post(f"/api/cases/{south}/committees", headers=committee_h, json={"type": "SCRUTINY", "members": [
        {"user_ref": alice, "role": "CHAIR"}, {"user_ref": bob, "role": "MEMBER"}]})
    assert formed.status_code == 201, formed.text
    for title in ("REVIEW_DOCUMENTS", "PREPARE_REPORT"):
        assert client.post(f"/api/committees/{formed.json()['id']}/tasks", headers=committee_h,
                           json={"title_key": title, "assignee_user_ref": bob}).status_code == 201
    work = section(client.get("/api/analytics/dashboard", headers=BUREAU).json(), "workload")["data"]
    assert (work["committees"], work["open_tasks"], work["officers"]) == (1, 2, 2)
    assert work["by_officer"] == [{"user_ref": bob, "open_tasks": 2, "committees": 1},
                                  {"user_ref": alice, "open_tasks": 0, "committees": 1}]
    assert work["by_committee"] == {"SCRUTINY": {"committees": 1, "open_tasks": 2, "cases": 1}}
    assert section(client.get("/api/analytics/dashboard", headers=RO_SOUTH).json(), "workload")["data"]["open_tasks"] == 2
    north = section(client.get("/api/analytics/dashboard", headers=RO_NORTH).json(), "workload")["data"]
    assert (north["committees"], north["open_tasks"], north["by_officer"]) == (0, 0, [])


def test_compliance_counts_obligations_overdue_and_evidence_awaiting_an_officer(client):
    app_id = file(client, SUNRISE_H, SUNRISE)
    letter = client.post("/api/compliance/letters", headers=headers("BUREAU_OFFICER", user=BUREAU_OFFICER), json={
        "application_id": app_id, "institution_id": str(SUNRISE), "letter_type": "LOA", "academic_year": "2025-26",
        "issue_date": "2025-08-31", "issue_date_source": "PORTAL_EVENT", "lists_deficiencies": False,
        "f_no": "F.No. DEMO/SOUTH/2025/00042"})
    assert letter.status_code == 201, letter.text
    body = client.get("/api/analytics/dashboard", headers=BUREAU).json()
    cmp = section(body, "compliance")["data"]
    obligations = len(letter.json()["obligation_ids"])
    assert cmp["obligations"] == obligations and cmp["by_status"] == {"OPEN": obligations}
    assert cmp["overdue"] == obligations          # issued in 2025: every 15-day clock has run out
    assert cmp["letters"] == {"LOA": 1} and cmp["awaiting_verification"] == 0
    assert section(body, "deadlines")["data"]["overdue"] >= obligations
    north = section(client.get("/api/analytics/dashboard", headers=RO_NORTH).json(), "compliance")["data"]
    assert north["obligations"] == 0 and north["letters"] == {}


def test_compliance_counts_document_validity_records_by_state(env):
    from datetime import timedelta

    from backend.tests.test_document_validity import application, record, today, upload
    c = env.client
    app_id = application(c)
    record(c, upload(env, app_id, "FIRE_NOC", "dash-fire"), valid_until=(today() + timedelta(days=20)).isoformat())
    record(c, upload(env, app_id, "BUILDING_COMPLETION", "dash-oc"),
           valid_until=(today() + timedelta(days=400)).isoformat())
    cmp = section(c.get("/api/analytics/dashboard", headers=BUREAU).json(), "compliance")["data"]
    assert cmp["document_validity"] == {"records": 2, "valid": 1, "expiring_soon": 1, "expired": 0,
                                        "renewal_under_review": 0, "renewed": 0}
    assert cmp["by_kind"] == {"DOCUMENT_VALIDITY": 2}
    clock.advance(30)                                   # the fire certificate has expired
    cmp = section(c.get("/api/analytics/dashboard", headers=BUREAU).json(), "compliance")["data"]
    assert (cmp["document_validity"]["expired"], cmp["document_validity"]["valid"], cmp["overdue"]) == (1, 1, 1)
    north = section(c.get("/api/analytics/dashboard", headers=RO_NORTH).json(), "compliance")["data"]
    assert north["document_validity"]["records"] == 0


def test_regional_officer_sees_only_their_region(client):
    file(client, SUNRISE_H, SUNRISE)
    file(client, NORTHFIELD_H, NORTHFIELD)
    body = client.get("/api/analytics/dashboard", headers=RO_SOUTH).json()
    assert body["scope"]["region"] == "Southern"
    assert section(body, "applications")["data"]["by_region"] == {"Southern": 1}
    alerts = section(body, "alerts")
    assert alerts["status"] == "AVAILABLE" and "Southern" in alerts["source"]
    assert alerts["data"]["by_status"] == {"PENDING": 0, "SENDING": 0, "DELIVERED": 0, "DEAD": 0}
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
    assert deadlines["overdue"] == 1                   # 30-day processing clock


def test_time_in_stage_and_bottlenecks_follow_stage_entries(client):
    file(client, SUNRISE_H, SUNRISE)
    clock.advance(10)
    file(client, NORTHFIELD_H, NORTHFIELD)
    file(client, SUNRISE_H, SUNRISE, submit=False)
    flow = section(client.get("/api/analytics/dashboard", headers=BUREAU).json(), "flow")
    assert flow["status"] == "AVAILABLE"
    assert flow["data"]["by_stage"] == [{"stage": "SCRUTINY", "cases": 2, "median_days": 5, "max_days": 10}]
    assert flow["data"]["bottleneck"] == flow["data"]["slowest"] == "SCRUTINY"
    assert flow["data"]["buckets"] == {"0-7 days": 1, "8-30 days": 1, "31-60 days": 0, "over 60 days": 0}
    assert flow["data"]["not_timed"] == 0
    south = section(client.get("/api/analytics/dashboard", headers=RO_SOUTH).json(), "flow")["data"]
    assert south["by_stage"] == [{"stage": "SCRUTINY", "cases": 1, "median_days": 10, "max_days": 10}]


def test_institutions_are_listed_with_their_cases_and_overdue_clocks(client):
    file(client, SUNRISE_H, SUNRISE)
    file(client, SUNRISE_H, SUNRISE, submit=False)
    file(client, NORTHFIELD_H, NORTHFIELD)
    clock.advance(35)                                   # the 30-day processing clocks have run out
    data = section(client.get("/api/analytics/dashboard", headers=BUREAU).json(), "institutions")["data"]
    assert data["institutions"] == 2
    assert {r["institution_id"]: (r["cases"], r["in_process"], r["overdue"]) for r in data["rows"]} == {
        str(SUNRISE): (2, 1, 1), str(NORTHFIELD): (1, 1, 1)}
    south = section(client.get("/api/analytics/dashboard", headers=RO_SOUTH).json(), "institutions")["data"]
    assert [r["institution_id"] for r in south["rows"]] == [str(SUNRISE)]


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
    """If a new kind of workflow event is stored, stage counts must not silently go stale."""
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
    # an empty system has real zeros, never estimates
    assert section(body, "workload")["data"]["by_officer"] == [] and section(body, "evc")["data"]["requests"] == 0
    assert section(body, "compliance")["data"]["obligations"] == 0 and section(body, "deadlines")["data"]["opened"] == 0


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


# ---- replay covers the case lifecycle ----

def test_a_case_moved_through_deficiency_into_evc_replays_completely(client, monkeypatch):
    """Stage moves, a deficiency round, clock pauses and closures and the EVC request all replay with nothing
    unhandled, so the applications card is not partial just because a case moved."""
    from app.platform import replay
    from backend.tests.test_workflow_case_api import ITEM, RESPONSE, act, create
    from app.workflow import guards
    from app.workflow.commands import GuardFacts

    facts = GuardFacts(open_item_count=0, checklist_complete=True, has_assignment=True,
                       reason_codes=frozenset({"DEMO_MISSING_EVIDENCE"}), item_refs=frozenset({ITEM}),
                       response_refs=frozenset({RESPONSE}), applicability={"SHC": False},
                       live_clock_rules=frozenset({"AICTE_PROCESSING"}), second_approval_required=False)
    monkeypatch.setattr(guards, "_fact_loader", lambda uow, case, cmd: facts)
    ensure_intake_rules(client)
    case_id = create(client)
    assert act(client, case_id, "submit", 1).status_code == 200
    assert act(client, case_id, "record_deficiency", 2, "SCRUTINY_COMMITTEE", reason_code="DEMO_MISSING_EVIDENCE",
               payload={"item_keys": ["DEMO_CORE_REFERENCE"]}).status_code == 200
    rounds = client.get(f"/api/cases/{case_id}/deficiencies", headers=SUNRISE_H).json()["rounds"]
    item = rounds[0]["items"][0]
    assert act(client, case_id, "submit_compliance", 3,
               payload={"responses": [{"item_id": item["id"], "response_ref": str(RESPONSE)}]}).status_code == 200
    assert client.post(f"/api/cases/{case_id}/deficiencies/{rounds[0]['id']}/review",
                       headers=headers("SCRUTINY_COMMITTEE"), json={"expected_version": 4, "decisions": [
                           {"item_id": item["id"], "state": "ACCEPTED", "reason_code": "DEMO_RESPONSE_ACCEPTED"}]}
                       ).status_code == 200

    report = replay.replay()
    assert report["verdict"] == "VERIFIED_COMPLETE", report
    assert report["unhandled_event_types"] == {}
    assert {p["name"]: p["status"] for p in report["projections"]} == dict.fromkeys(
        ("applications", "deadlines", "deficiencies", "committees", "evc", "compliance", "alerts"), "MATCH")
    body = client.get("/api/analytics/dashboard", headers=BUREAU).json()
    apps = section(body, "applications")
    assert apps["status"] == "AVAILABLE" and apps["data"]["by_stage"] == {"EVC": 1}
    evc = section(body, "evc")["data"]
    assert (evc["requests"], evc["open"], evc["by_status"]) == (1, 1, {"QUEUED": 1})
