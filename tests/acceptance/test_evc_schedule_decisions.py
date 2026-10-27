"""EVC daily cap, explanations, discard and region handling over the real API, ledger and database (fictional DEMO data)."""
from uuid import UUID

from sqlalchemy import func, select

from app.evc.models import Assignment, ScheduleRun
from app.platform.db import new_session
from acceptance.runtime_support import headers
from acceptance.test_evc_queue import NORTH, request_row
from acceptance.test_evc_schedule import (BUREAU, DAY, RO_SOUTH, enter, env, experts, foreign_booking, ledger, propose,  # noqa: F401
                                          publish, run_id, schema, status)


def discard(env, run, actor=BUREAU, key=None):
    extra = {"Idempotency-Key": key} if key else {}
    return env.client.post("/api/evc/schedule:discard", headers={**actor, **extra}, json=dict(run_id=str(run)))


def test_daily_cap_keeps_a_second_same_day_visit_queued_with_its_reason(env):
    experts(env, days=range(1))  # three experts, available on DAY only
    apps = [enter(env), enter(env)]
    for algorithm, run in (("EDF", "cap-edf"), ("CPSAT", "cap-cpsat")):
        body = propose(env, algorithm, run=run).json()
        assert body["expert_daily_cap"] == 1 and body["metrics"]["scheduled"] == (1 if run == "cap-edf" else 0)
        if run == "cap-edf":
            [proposal] = body["proposals"]
            [waiting] = body["unscheduled"]
            assert waiting == dict(request_id=str(request_row(apps[1]).id) if proposal["request_id"] == str(request_row(apps[0]).id)
                                   else str(request_row(apps[0]).id), reason_code="NO_FEASIBLE_SLOT", explanation_code="EXPERT_DAILY_CAP")
            with new_session() as session:
                assert session.get(ScheduleRun, UUID(body["run_id"])).parameters["expert_daily_cap"] == 1
        else:
            assert body["solver"]["candidate_slots"] == 12
            assert [row["explanation_code"] for row in body["unscheduled"]] == ["EXPERT_DAILY_CAP"]
    assert sorted(status(app) for app in apps) == ["PROPOSED", "QUEUED"]


def test_publish_recheck_refuses_a_second_visit_on_the_same_day(env):
    experts(env)
    app = enter(env)
    body = propose(env, "EDF").json()
    [row] = body["proposals"]
    other = "PM" if row["slot_part"] == "AM" else "AM"
    foreign_booking(body["run_id"], row["expert_ids"][0], row["date"], other)
    refused = publish(env, body["run_id"])
    assert refused.status_code == 409 and refused.json()["detail"] == "EVC_EXPERT_DAILY_CAP_EXCEEDED"
    assert status(app) == "PROPOSED" and ledger("evc.assignment_published") == []


def test_unscheduled_requests_carry_specific_explanations(env):
    experts(env, count=2)
    app = enter(env)
    north = enter(env, NORTH)
    body = propose(env).json()
    assert {row["request_id"]: (row["reason_code"], row["explanation_code"]) for row in body["unscheduled"]} == {
        str(request_row(app).id): ("NO_FEASIBLE_SLOT", "PANEL_INCOMPLETE"),
        str(request_row(north).id): ("NO_FEASIBLE_SLOT", "NO_AVAILABILITY")}
    [event] = ledger("evc.schedule_proposed")
    assert not list(schema("schedule_proposed").iter_errors(event))  # the approved event payload is unchanged


def test_discard_withdraws_an_unpublished_run_so_its_requests_can_be_replanned(env):
    experts(env)
    apps = [enter(env), enter(env)]
    body = propose(env, "EDF").json()
    assert discard(env, body["run_id"], actor=RO_SOUTH).status_code == 403
    assert discard(env, body["run_id"], actor=headers("AUDITOR")).status_code == 403
    assert discard(env, run_id("missing")).status_code == 404
    done = discard(env, body["run_id"], key="evc-discard-0001")
    replay = discard(env, body["run_id"], key="evc-discard-0001")
    assert done.status_code == replay.status_code == 200 and done.json() == replay.json()
    result = done.json()
    assert result["status"] == "DISCARDED" and result["discarded_count"] == 2
    assert {row["assignment_id"] for row in result["withdrawn"]} == {p["assignment_id"] for p in body["proposals"]}
    assert [status(app) for app in apps] == ["QUEUED", "QUEUED"]
    with new_session() as session:
        assert session.get(ScheduleRun, UUID(body["run_id"])).status == "DISCARDED"
        assert session.scalar(select(func.count()).select_from(Assignment)) == 0
    [event] = ledger("evc.schedule_discarded")
    assert not list(schema("schedule_discarded").iter_errors(event)) and event["discarded_count"] == 2
    again = discard(env, body["run_id"])
    assert again.status_code == 409 and again.json()["detail"] == "EVC_RUN_NOT_DISCARDABLE"
    assert publish(env, body["run_id"]).json()["detail"] == "EVC_RUN_NOT_PUBLISHABLE"
    replanned = propose(env, "CPSAT", run="replanned").json()
    assert replanned["metrics"]["scheduled"] == 2
    assert publish(env, replanned["run_id"]).status_code == 200
    published = discard(env, replanned["run_id"])
    assert published.status_code == 409 and published.json()["detail"] == "EVC_RUN_NOT_DISCARDABLE"
    assert [status(app) for app in apps] == ["PUBLISHED", "PUBLISHED"]


def test_region_names_match_case_insensitively_and_unknown_bureau_regions_are_422(env):
    experts(env, "SOUTHERN")
    south = enter(env)
    unknown = propose(env, region="Atlantis", run="unknown")
    assert unknown.status_code == 422 and unknown.json()["detail"] == "SCHEDULE_REGION_UNKNOWN"
    assert propose(env, actor=RO_SOUTH, region="Northern", run="ro-north").status_code == 403
    body = propose(env, region="sOuThErN", run="mixed").json()
    assert [p["request_id"] for p in body["proposals"]] == [str(request_row(south).id)]
    with new_session() as session:
        assert session.scalar(select(func.count()).select_from(ScheduleRun)) == 1
