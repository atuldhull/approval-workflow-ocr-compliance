"""EVC propose/publish over real workflow entry, ledger, policy and database (fictional DEMO data only)."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
import json
from pathlib import Path
from threading import Barrier
from uuid import UUID, NAMESPACE_URL, uuid5

from jsonschema import Draft202012Validator
import pytest
from sqlalchemy import func, select, text

from app.evc.models import Assignment, AssignmentExpert, EvcRequest, ScheduleRun
from app.platform.db import new_session
from app.platform.models import DomainEvent
from app.platform.registry import port, provide
from contracts.ports import ClockPort, EvcPort
from generator.cases.scale_generator import LogicalClock
from acceptance.runtime_support import SUNRISE, headers
from acceptance.test_evc_queue import NORTH, action, enter, request_row

ROOT = Path(__file__).resolve().parents[2]
DAY = date(2026, 7, 1)  # IST date of the logical EPOCH; requests are due DAY + 7 (DEMO ASSUMPTION)
BUREAU = headers("BUREAU_OFFICER")
RO_SOUTH = dict(headers("RO_OFFICER"), **{"X-Demo-Region": "Southern"})


@pytest.fixture
def env(acceptance_env):
    acceptance_env.clock = LogicalClock()
    provide(ClockPort, acceptance_env.clock)
    yield acceptance_env
    with new_session() as session, session.begin():
        session.execute(text("TRUNCATE evc.assignment_expert, evc.assignment, evc.availability, evc.coi, "
                             "evc.slot, evc.schedule_run, evc.evc_request, evc.expert"))


def experts(env, region="SOUTHERN", count=3, days=range(8), token="s", active=True):
    created = []
    for index in range(count):
        response = env.client.post("/api/evc/experts", headers=BUREAU, json=dict(
            user_ref=str(uuid5(NAMESPACE_URL, f"DEMO:schedule:{token}:{index}")), region=region,
            expertise_tags=["DEMO"], active=active))
        assert response.status_code == 201, response.text
        expert = response.json()["id"]
        items = [dict(date=(DAY + timedelta(days=d)).isoformat(), slot_part=p, available=True) for d in days for p in ("AM", "PM")]
        assert env.client.post(f"/api/evc/experts/{expert}/availability", headers=BUREAU, json=dict(items=items)).status_code == 200
        created.append(expert)
    return created


def propose(env, algorithm="CPSAT", actor=BUREAU, key=None, **body):
    extra = {"Idempotency-Key": key} if key else {}
    return env.client.post("/api/evc/schedule:propose", headers={**actor, **extra}, json=dict(algorithm=algorithm, **body))


def publish(env, run_id, actor=BUREAU, key=None):
    extra = {"Idempotency-Key": key} if key else {}
    return env.client.post("/api/evc/schedule:publish", headers={**actor, **extra}, json=dict(run_id=str(run_id)))


def status(app):
    with new_session() as session:
        return port(EvcPort).status(session, UUID(app))


def ledger(event_type):
    with new_session() as session:
        return [row.payload for row in session.scalars(select(DomainEvent).where(DomainEvent.event_type == event_type)
                                                       .order_by(DomainEvent.seq))]


def schema(name):
    return Draft202012Validator(json.loads((ROOT / "contracts" / "events" / "evc" / f"{name}.v1.json").read_text(encoding="utf-8")),
                                format_checker=Draft202012Validator.FORMAT_CHECKER)


@pytest.mark.parametrize("algorithm", ["EDF", "CPSAT"])
def test_propose_publish_then_complete_with_coi_and_inactive_experts_excluded(env, algorithm):
    pool = experts(env, count=4)
    inactive = experts(env, count=1, token="off", active=False)
    assert env.client.post("/api/evc/coi", headers=BUREAU, json=dict(expert_id=pool[0], institution_ref=str(SUNRISE),
                           source="RECUSAL", reason_code="RECUSAL")).status_code == 200
    apps = [enter(env), enter(env)]
    proposed = propose(env, algorithm)
    assert proposed.status_code == 201, proposed.text
    body = proposed.json()
    assert body["selector_label"] == "SIMULATED authorised selector (stand-in)" and body["status"] == "PROPOSED"
    assert len(body["proposals"]) == 2 and body["unscheduled"] == []
    for row in body["proposals"]:
        assert pool[0] not in row["expert_ids"] and inactive[0] not in row["expert_ids"] and len(row["expert_ids"]) == 3
        assert DAY.isoformat() <= row["date"] <= row["due_by"] and row["lateness_days"] == 0
    # One visit per expert per day (DEMO capacity) and only three non-conflicted experts: two different days.
    assert len({row["date"] for row in body["proposals"]}) == 2
    assert [status(app) for app in apps] == ["PROPOSED", "PROPOSED"]
    with new_session() as session:
        run = session.get(ScheduleRun, UUID(body["run_id"]))
        assert run.algorithm == algorithm and run.status == "PROPOSED" and run.metrics["scheduled_count"] == 2
        assert all(isinstance(value, (int, float)) for value in run.parameters.values())
        assert session.scalar(select(func.count()).select_from(AssignmentExpert).where(AssignmentExpert.published)) == 0
    [event] = ledger("evc.schedule_proposed")
    assert not list(schema("schedule_proposed").iter_errors(event)) and event["scheduled_count"] == 2
    published = publish(env, body["run_id"])
    assert published.status_code == 200, published.text
    assert published.json()["published_count"] == 2
    assert [status(app) for app in apps] == ["PUBLISHED", "PUBLISHED"]
    events = ledger("evc.assignment_published")
    assert len(events) == 2 and all(not list(schema("assignment_published").iter_errors(e)) for e in events)
    assert {e["application_id"] for e in events} == set(apps)
    timeline = env.client.get(f"/api/cases/{apps[0]}/timeline", headers=headers("AUDITOR")).json()
    assert [e["event_type"] for e in timeline].count("evc.assignment_published") == 1
    with new_session() as session:
        assert session.scalar(select(func.count()).select_from(AssignmentExpert).where(AssignmentExpert.published)) == 6
        assert session.get(ScheduleRun, UUID(body["run_id"])).status == "PUBLISHED"
    completed = action(env, apps[0], "complete_evc", 3)
    assert completed.status_code == 200, completed.text
    assert status(apps[0]) == "DONE"


def test_unschedulable_requests_are_explained(env):
    experts(env, count=2)
    app = enter(env)
    north = enter(env, NORTH)
    body = propose(env).json()
    reasons = {row["request_id"]: row for row in body["unscheduled"]}
    south_row, north_row = (reasons[str(request_row(a).id)] for a in (app, north))
    assert south_row["reason_code"] == "PANEL_INCOMPLETE" and south_row["best_qualified_count"] == 2
    assert north_row["reason_code"] == "NO_AVAILABILITY" and north_row["slot_reasons"]["NO_AVAILABILITY"] == 16
    assert body["metrics"]["reason_panel_incomplete"] == 1 and body["metrics"]["reason_no_availability"] == 1
    assert status(app) == status(north) == "QUEUED"
    [event] = ledger("evc.schedule_proposed")
    assert sorted(u["reason_code"] for u in event["unscheduled"]) == ["NO_AVAILABILITY", "PANEL_INCOMPLETE"]


def test_region_scope_per_role_with_upper_case_expert_regions(env):
    experts(env, "SOUTHERN")
    experts(env, "NORTHERN", token="n")
    south, north = enter(env), enter(env, NORTH)
    south_id, north_id = str(request_row(south).id), str(request_row(north).id)
    for region in (None, "SOUTHERN", "southern"):
        body = propose(env, actor=RO_SOUTH, **({} if region is None else dict(region=region))).json()
        assert [p["request_id"] for p in body["proposals"]] == [south_id] and body["unscheduled"] == []
        assert body["region_scope"] == "SOUTHERN"
    assert status(north) == "QUEUED"
    assert propose(env, actor=RO_SOUTH, region="Northern").status_code == 403
    assert propose(env, actor=headers("INSTITUTION", SUNRISE)).status_code == 403
    assert propose(env, actor=headers("AUDITOR")).status_code == 403
    assert publish(env, body["run_id"], actor=RO_SOUTH).status_code == 403
    northern = propose(env, region="northern").json()
    assert [p["request_id"] for p in northern["proposals"]] == [north_id]
    assert status(south) == "PROPOSED"  # the bureau's Northern run leaves Southern drafts alone
    assert publish(env, body["run_id"], actor=headers("BUREAU_HEAD")).status_code == 200


def test_idempotent_replay_of_propose_and_publish(env):
    experts(env)
    enter(env)
    first = propose(env, key="evc-propose-0001")
    again = propose(env, key="evc-propose-0001")
    assert first.status_code == again.status_code == 201 and first.json() == again.json()
    assert again.headers.get("Idempotent-Replayed") == "true"
    with new_session() as session:
        assert session.scalar(select(func.count()).select_from(ScheduleRun)) == 1
    run_id = first.json()["run_id"]
    done = publish(env, run_id, key="evc-publish-0001")
    replay = publish(env, run_id, key="evc-publish-0001")
    assert done.status_code == replay.status_code == 200 and done.json() == replay.json()
    assert len(ledger("evc.assignment_published")) == 1
    retry = publish(env, run_id)
    assert retry.status_code == 409 and retry.json()["detail"] == "EVC_RUN_NOT_PUBLISHABLE"


def foreign_booking(run_id, expert, day, part):
    """A published commitment from another run, written as the storage layer would hold it."""
    with new_session() as session, session.begin():
        other = uuid5(NAMESPACE_URL, f"DEMO:schedule:foreign:{run_id}")
        session.add(ScheduleRun(run_id=other, algorithm="EDF", parameters={}, created_at=port(ClockPort).now(),
                                status="PUBLISHED", metrics={}))
        session.flush()
        slot = session.scalar(text("SELECT id FROM evc.slot WHERE date = :d AND slot_part = :p"), dict(d=day, p=part))
        request = session.scalar(select(EvcRequest.id).limit(1))
        session.add(Assignment(id=uuid5(NAMESPACE_URL, f"DEMO:schedule:foreign-a:{run_id}"), evc_request_id=request,
                               slot_id=slot, expert_ids=[UUID(expert)], panel_role="DEMO_MEMBER", published=True,
                               schedule_run_id=other))


def test_publish_is_atomic_when_one_panel_became_double_booked(env):
    experts(env)
    apps = [enter(env), enter(env)]
    body = propose(env).json()
    late = max(body["proposals"], key=lambda p: p["date"])
    foreign_booking(body["run_id"], late["expert_ids"][0], late["date"], late["slot_part"])
    refused = publish(env, body["run_id"])
    assert refused.status_code == 409 and refused.json()["detail"] == "EVC_EXPERT_DOUBLE_BOOKED"
    assert [status(app) for app in apps] == ["PROPOSED", "PROPOSED"]
    assert ledger("evc.assignment_published") == []
    with new_session() as session:
        drafts = session.scalars(select(Assignment).where(Assignment.schedule_run_id == UUID(body["run_id"]))).all()
        assert len(drafts) == 2 and not any(d.published for d in drafts)
        assert session.get(ScheduleRun, UUID(body["run_id"])).status == "PROPOSED"


def test_concurrent_publishes_never_double_book(env):
    experts(env)
    first_app, second_app = enter(env), enter(env)
    run = propose(env).json()
    # A second live run holding the same experts on the same slot for the other request (only possible by
    # direct storage writes, since proposing supersedes drafts): the database must still allow one winner.
    target = next(p for p in run["proposals"] if p["request_id"] == str(request_row(first_app).id))
    other = uuid5(NAMESPACE_URL, "DEMO:schedule:rival")
    with new_session() as session, session.begin():
        session.execute(text("DELETE FROM evc.assignment WHERE evc_request_id = :r"), dict(r=request_row(second_app).id))
        session.add(ScheduleRun(run_id=other, algorithm="EDF", parameters=run["parameters"], created_at=port(ClockPort).now(),
                                status="PROPOSED", metrics={}))
        session.flush()
        session.add(Assignment(id=uuid5(NAMESPACE_URL, "DEMO:schedule:rival-a"), evc_request_id=request_row(second_app).id,
                               slot_id=UUID(target["slot_id"]), expert_ids=[UUID(e) for e in target["expert_ids"]],
                               panel_role="EVC_PANEL", published=False, schedule_run_id=other))
    barrier = Barrier(3)

    def go(run_id):
        barrier.wait()
        return publish(env, run_id).status_code

    with ThreadPoolExecutor(3) as pool:
        codes = list(pool.map(go, [run["run_id"], other, run["run_id"]]))
    assert sorted(codes) == [200, 409, 409]
    with new_session() as session:
        rows = session.execute(select(AssignmentExpert.expert_id, AssignmentExpert.date, AssignmentExpert.slot_part)
                               .where(AssignmentExpert.published)).all()
        assert len(rows) == len(set(rows)) == 3
    assert len(ledger("evc.assignment_published")) == 1


def test_reproposal_supersedes_drafts_and_proposed_cases_can_still_be_rejected(env):
    experts(env)
    app = enter(env)
    first = propose(env, "EDF").json()
    second = propose(env, "CPSAT").json()
    with new_session() as session:
        assert session.get(ScheduleRun, UUID(first["run_id"])).status == "SUPERSEDED"
        assert session.scalar(select(func.count()).select_from(Assignment)) == 1
    stale = publish(env, first["run_id"])
    assert stale.status_code == 409 and stale.json()["detail"] == "EVC_RUN_NOT_PUBLISHABLE"
    rejected = action(env, app, "reject", 3, reason_code="DEMO_REASON")
    assert rejected.status_code == 200, rejected.text
    assert status(app) == "CANCELLED"
    with new_session() as session:
        assert session.scalar(select(func.count()).select_from(Assignment)) == 0
    assert publish(env, second["run_id"]).json()["detail"] == "EVC_RUN_EMPTY"


def test_published_request_still_fails_closed_on_cancellation(env):
    experts(env)
    app = enter(env)
    assert publish(env, propose(env).json()["run_id"]).status_code == 200
    rejected = action(env, app, "reject", 3, reason_code="DEMO_REASON")
    assert rejected.status_code == 409 and rejected.json()["detail"] == "EVC_SCHEDULE_CANCELLATION_REQUIRED"
    assert status(app) == "PUBLISHED"


def test_database_index_still_refuses_double_booking_if_the_recheck_misses_it(env, monkeypatch):
    from app.evc import schedule_service

    experts(env)
    apps = [enter(env), enter(env)]
    body = propose(env).json()
    late = max(body["proposals"], key=lambda p: p["date"])
    foreign_booking(body["run_id"], late["expert_ids"][0], late["date"], late["slot_part"])
    monkeypatch.setattr(schedule_service, "_memberships", lambda *args, **kwargs: [])
    refused = publish(env, body["run_id"])
    assert refused.status_code == 409 and refused.json()["detail"] == "EVC_EXPERT_DOUBLE_BOOKED"
    assert [status(app) for app in apps] == ["PROPOSED", "PROPOSED"] and ledger("evc.assignment_published") == []
    with new_session() as session:
        assert not any(session.scalars(select(Assignment.published).where(Assignment.schedule_run_id == UUID(body["run_id"]))))
