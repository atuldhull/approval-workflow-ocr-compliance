"""Stored EVC runs and one case's visit, read back over the real API and database (fictional DEMO data only)."""
from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.evc.models import ScheduleRun
from app.platform.db import new_session
from acceptance.runtime_support import SUNRISE, headers
from acceptance.test_evc_queue import NORTH, request_row
from acceptance.test_evc_schedule import (BUREAU, RO_SOUTH, enter, env, experts, propose, publish,  # noqa: F401
                                          run_id)
from acceptance.test_evc_schedule_decisions import discard

RO_NORTH = dict(headers("RO_OFFICER"), **{"X-Demo-Region": "Northern"})


def runs(env, actor=BUREAU, **params):
    return env.client.get("/api/evc/schedule/runs", headers=actor, params=params)


def run(env, run, actor=BUREAU):
    return env.client.get(f"/api/evc/schedule/runs/{run}", headers=actor)


def case_evc(env, app, actor=BUREAU):
    return env.client.get(f"/api/applications/{app}/evc", headers=actor)


def test_runs_are_listed_and_read_back_with_outcomes_and_explanations(env):
    experts(env, count=3, days=range(1))  # one day, one visit per expert per day: the second request must wait
    apps = [enter(env), enter(env)]
    first = propose(env, "EDF", run="first").json()
    assert first["metrics"]["scheduled"] == 1 and len(first["unscheduled"]) == 1  # one visit per expert per day
    listed = runs(env)
    assert listed.status_code == 200, listed.text
    page = listed.json()
    assert page["total"] == 1 and page["items"][0]["run_id"] == first["run_id"]
    summary = page["items"][0]
    assert summary["status"] == "PROPOSED" and summary["expert_daily_cap"] == 1 and summary["slot_capacity"] == 4
    assert summary["candidate_slots"] is None and summary["outcomes_recorded"] is True
    assert summary["input_fingerprint"] == first["input_fingerprint"] and summary["metrics"] == first["metrics"]
    assert summary["selector_label"] == "SIMULATED authorised selector (stand-in)" and summary["region_scope"] is None
    detail = run(env, first["run_id"]).json()
    [proposal] = detail["proposals"]
    assert proposal["published"] is False and proposal["assignment_id"] == first["proposals"][0]["assignment_id"]
    assert proposal["expert_ids"] == first["proposals"][0]["expert_ids"] and detail["solver"] is None
    [waiting] = detail["unscheduled"]
    assert waiting["request_id"] == first["unscheduled"][0]["request_id"]
    assert waiting["explanation_code"] == first["unscheduled"][0]["explanation_code"] == "EXPERT_DAILY_CAP"
    assert waiting["reason_code"] == "NO_FEASIBLE_SLOT" and waiting["application_id"] in apps
    assert detail["withdrawn"] == []
    # discard, re-plan with CP-SAT and publish: every run keeps its own story
    assert discard(env, first["run_id"]).status_code == 200
    gone = run(env, first["run_id"]).json()
    assert gone["status"] == "DISCARDED" and gone["proposals"] == []
    assert gone["withdrawn"] == [dict(request_id=proposal["request_id"], application_id=proposal["application_id"])]
    assert [row["request_id"] for row in gone["unscheduled"]] == [waiting["request_id"]]
    second = propose(env, "CPSAT", run="second").json()
    assert publish(env, second["run_id"]).status_code == 200
    held = run(env, second["run_id"]).json()
    assert held["status"] == "PUBLISHED" and all(p["published"] for p in held["proposals"])
    assert held["candidate_slots"] == 12 and held["solver"]["candidate_slots"] == 12
    assert {r["run_id"] for r in runs(env).json()["items"]} == {first["run_id"], second["run_id"]}
    assert [r["run_id"] for r in runs(env, status="DISCARDED").json()["items"]] == [first["run_id"]]
    assert [r["run_id"] for r in runs(env, algorithm="CPSAT").json()["items"]] == [second["run_id"]]
    one = runs(env, limit=1, offset=1).json()
    assert one["total"] == 2 and len(one["items"]) == 1
    assert runs(env, status="DONE").status_code == 422
    assert run(env, run_id("missing")).status_code == 404 and run(env, run_id("missing")).json()["detail"] == "EVC_RUN_NOT_FOUND"


def test_runs_are_read_by_pool_readers_and_regional_officers_see_their_region_only(env):
    experts(env, "SOUTHERN")
    experts(env, "NORTHERN", token="n")
    enter(env), enter(env, NORTH)
    own = propose(env, "EDF", actor=RO_SOUTH, run="ro-south").json()
    north = propose(env, "EDF", region="northern", run="bureau-north").json()
    everywhere = propose(env, "EDF", run="bureau-all").json()
    assert own["region_scope"] == "SOUTHERN" and north["region_scope"] == "NORTHERN" and everywhere["region_scope"] is None
    assert [r["run_id"] for r in runs(env, RO_SOUTH).json()["items"]] == [own["run_id"]]
    assert [r["run_id"] for r in runs(env, RO_SOUTH, region="southern").json()["items"]] == [own["run_id"]]
    assert runs(env, RO_SOUTH, region="Northern").status_code == 403
    assert [r["run_id"] for r in runs(env, RO_NORTH).json()["items"]] == [north["run_id"]]
    assert run(env, own["run_id"], RO_SOUTH).status_code == 200
    assert run(env, north["run_id"], RO_SOUTH).status_code == 403
    assert run(env, everywhere["run_id"], RO_SOUTH).status_code == 403
    assert [r["run_id"] for r in runs(env, region="NORTHERN").json()["items"]] == [north["run_id"]]
    for reader in (headers("AUDITOR"), headers("SCRUTINY_COMMITTEE"), headers("BUREAU_HEAD")):
        assert runs(env, reader).json()["total"] == 3
        assert run(env, everywhere["run_id"], reader).status_code == 200
    institution = headers("INSTITUTION", SUNRISE)
    assert runs(env, institution).status_code == 403 and run(env, own["run_id"], institution).status_code == 403


def test_runs_made_before_outcomes_were_stored_say_so(env):
    legacy = uuid4()
    with new_session() as session, session.begin():
        session.add(ScheduleRun(run_id=legacy, algorithm="EDF", status="PROPOSED", created_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
            parameters=dict(horizon_start_ordinal=740000, horizon_end_ordinal=740007, input_fingerprint_bytes=[1, 2]),
            metrics=dict(queue_count=0, scheduled=0, unscheduled=0, late_count=0, total_lateness=0, max_lateness=0,
                         total_waiting=0, hard_constraint_violations=0, lateness_days=[])))
    body = run(env, legacy).json()
    assert body["outcomes_recorded"] is False and body["unscheduled"] == [] and body["expert_daily_cap"] is None
    assert body["input_fingerprint"] == "0102" and body["region_scope"] is None


def test_case_evc_read_shows_the_request_and_only_its_published_visit(env):
    experts(env, count=3)
    app = enter(env)
    other = enter(env, NORTH)
    body = case_evc(env, app).json()
    assert body["application_id"] == app and body["region"] == "Southern"
    [current] = body["requests"]
    assert body["current"] == current and current["status"] == "QUEUED" and current["visit"] is None
    assert current["id"] == str(request_row(app).id) and current["duration_days"] == 7
    assert current["source_status"] == "DEMO_ASSUMPTION" and current["assumption_code"] == "EVC_DURATION_UNCONFIRMED"
    proposed = propose(env, "EDF", region="Southern").json()
    after = case_evc(env, app).json()["current"]
    assert after["status"] == "PROPOSED" and after["visit"] is None  # unpublished drafts are not shown on the case
    assert publish(env, proposed["run_id"]).status_code == 200
    [proposal] = proposed["proposals"]
    visit = case_evc(env, app, headers("INSTITUTION", SUNRISE)).json()["current"]["visit"]
    assert visit == dict(assignment_id=proposal["assignment_id"], run_id=proposed["run_id"], algorithm="EDF",
                         date=proposal["date"], slot_part=proposal["slot_part"], panel_role="DEMO_PANEL",
                         expert_ids=proposal["expert_ids"], simulation_status="SIMULATED",
                         selector_label="SIMULATED authorised selector (stand-in)")
    assert case_evc(env, app, RO_SOUTH).status_code == 200
    assert case_evc(env, app, RO_NORTH).status_code == 403
    assert case_evc(env, app, headers("INSTITUTION", NORTH)).status_code == 403
    assert case_evc(env, other, RO_NORTH).json()["current"]["status"] == "QUEUED"
    assert case_evc(env, str(uuid4())).status_code == 404
    queue = env.client.get("/api/evc/queue", headers=BUREAU, params=dict(application_id=app)).json()
    assert queue["total"] == 1 and [row["application_id"] for row in queue["items"]] == [app]


def test_case_without_requests_has_no_current_request(env):
    created = env.client.post("/api/applications", headers=headers("INSTITUTION", SUNRISE), json=dict(
        institution_id=str(SUNRISE), category="NEW_PROGRAMME", academic_year="2027-28"))
    body = case_evc(env, created.json()["id"], headers("INSTITUTION", SUNRISE)).json()
    assert body["current"] is None and body["requests"] == []
    assert UUID(body["application_id"])
