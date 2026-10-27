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

from app.evc.models import Assignment, AssignmentExpert, EvcRequest, ScheduleRun, Slot
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
                             "evc.slot, evc.schedule_run_request, evc.schedule_run, evc.evc_request, evc.expert"))


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


def run_id(token):
    return str(uuid5(NAMESPACE_URL, f"DEMO:schedule:run:{token}"))


def propose(env, algorithm="CPSAT", actor=BUREAU, key=None, run="run", **body):
    extra = {"Idempotency-Key": key} if key else {}
    payload = dict(run_id=run_id(run), algorithm=algorithm, horizon_start=DAY.isoformat(),
                   horizon_end=(DAY + timedelta(days=7)).isoformat(), slot_capacity=4)
    return env.client.post("/api/evc/schedule:propose", headers={**actor, **extra}, json={**payload, **body})


def publish(env, run, actor=BUREAU, key=None):
    extra = {"Idempotency-Key": key} if key else {}
    return env.client.post("/api/evc/schedule:publish", headers={**actor, **extra}, json=dict(run_id=str(run)))


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
    assert body["algorithm"] == algorithm and (body["solver"] is not None) == (algorithm == "CPSAT")
    assert len(body["proposals"]) == 2 and body["unscheduled"] == [] and body["metrics"]["scheduled"] == 2
    for row in body["proposals"]:
        assert pool[0] not in row["expert_ids"] and inactive[0] not in row["expert_ids"] and len(row["expert_ids"]) == 3
        assert DAY.isoformat() <= row["date"] <= row["due_by"] and row["lateness_days"] == 0
    # Only three non-conflicted experts: the two panels never share a date/part.
    assert len({(row["date"], row["slot_part"]) for row in body["proposals"]}) == 2
    assert [status(app) for app in apps] == ["PROPOSED", "PROPOSED"]
    with new_session() as session:
        run = session.get(ScheduleRun, UUID(body["run_id"]))
        assert run.algorithm == algorithm and run.status == "PROPOSED" and run.metrics == body["metrics"]
        assert bytes(run.parameters["input_fingerprint_bytes"]).hex() == body["input_fingerprint"]
        assert session.scalar(select(func.count()).select_from(Slot)) == 16
        assert session.scalar(select(func.count()).select_from(AssignmentExpert).where(AssignmentExpert.published)) == 0
    [event] = ledger("evc.schedule_proposed")
    assert not list(schema("schedule_proposed").iter_errors(event)) and event["algorithm"] == algorithm
    proposals = ledger("evc.assignment_proposed")
    assert len(proposals) == 2 and all(not list(schema("assignment_proposed").iter_errors(e)) for e in proposals)
    published = publish(env, body["run_id"])
    assert published.status_code == 200, published.text
    assert published.json()["published_count"] == 2
    assert [status(app) for app in apps] == ["PUBLISHED", "PUBLISHED"]
    events = ledger("evc.assignment_published")
    assert len(events) == 2 and all(not list(schema("assignment_published").iter_errors(e)) for e in events)
    assert {e["application_id"] for e in events} == set(apps) and {e["algorithm"] for e in events} == {algorithm}
    timeline = env.client.get(f"/api/cases/{apps[0]}/timeline", headers=headers("AUDITOR")).json()
    kinds = [e["event_type"] for e in timeline]
    assert kinds.count("evc.assignment_proposed") == kinds.count("evc.assignment_published") == 1
    with new_session() as session:
        assert session.scalar(select(func.count()).select_from(AssignmentExpert).where(AssignmentExpert.published)) == 6
        assert session.get(ScheduleRun, UUID(body["run_id"])).status == "PUBLISHED"
    completed = action(env, apps[0], "complete_evc", 3)
    assert completed.status_code == 200, completed.text
    assert status(apps[0]) == "DONE"


def test_unschedulable_requests_stay_queued_with_the_shared_reason(env):
    experts(env, count=2)
    app = enter(env)
    north = enter(env, NORTH)
    body = propose(env).json()
    assert {row["request_id"]: row["reason_code"] for row in body["unscheduled"]} == {
        str(request_row(app).id): "NO_FEASIBLE_SLOT", str(request_row(north).id): "NO_FEASIBLE_SLOT"}
    assert body["metrics"]["unscheduled"] == 2 and body["metrics"]["lateness_days"] == [None, None]
    assert status(app) == status(north) == "QUEUED"
    assert ledger("evc.assignment_proposed") == []
    assert publish(env, body["run_id"]).json()["detail"] == "EVC_RUN_EMPTY"


def test_region_scope_per_role_with_upper_case_expert_regions(env):
    experts(env, "SOUTHERN")
    experts(env, "NORTHERN", token="n")
    south, north = enter(env), enter(env, NORTH)
    south_id, north_id = str(request_row(south).id), str(request_row(north).id)
    assert propose(env, actor=RO_SOUTH, region="Northern").status_code == 403
    assert propose(env, actor=headers("INSTITUTION", SUNRISE)).status_code == 403
    assert propose(env, actor=headers("AUDITOR")).status_code == 403
    body = propose(env, actor=RO_SOUTH, region="southern", run="ro").json()
    assert [p["request_id"] for p in body["proposals"]] == [south_id] and body["unscheduled"] == []
    assert body["region_scope"] == "SOUTHERN"
    assert status(north) == "QUEUED"
    assert publish(env, body["run_id"], actor=RO_SOUTH).status_code == 403
    northern = propose(env, region="northern", run="north").json()
    assert [p["request_id"] for p in northern["proposals"]] == [north_id]
    assert status(south) == "PROPOSED"  # the bureau's Northern run leaves the Southern proposal alone
    assert publish(env, body["run_id"], actor=headers("BUREAU_HEAD")).status_code == 200


def test_idempotent_replay_and_reused_run_id(env):
    experts(env)
    enter(env)
    first = propose(env, key="evc-propose-0001")
    again = propose(env, key="evc-propose-0001")
    assert first.status_code == again.status_code == 201 and first.json() == again.json()
    assert again.headers.get("Idempotent-Replayed") == "true"
    reused = propose(env)
    assert reused.status_code == 409 and reused.json()["detail"] == "SCHEDULE_RUN_ALREADY_EXISTS"
    with new_session() as session:
        assert session.scalar(select(func.count()).select_from(ScheduleRun)) == 1
    run = first.json()["run_id"]
    done = publish(env, run, key="evc-publish-0001")
    replay = publish(env, run, key="evc-publish-0001")
    assert done.status_code == replay.status_code == 200 and done.json() == replay.json()
    assert len(ledger("evc.assignment_published")) == 1
    retry = publish(env, run)
    assert retry.status_code == 409 and retry.json()["detail"] == "EVC_RUN_NOT_PUBLISHABLE"


def test_existing_slots_keep_their_capacity_and_proposals_are_not_rescheduled(env):
    experts(env, count=6)
    apps = [enter(env), enter(env)]
    with new_session() as session, session.begin():
        session.add(Slot(id=uuid5(NAMESPACE_URL, "DEMO:schedule:slot:am"), date=DAY, slot_part="AM", capacity=1))
    first = propose(env, "EDF").json()
    assert [(p["date"], p["slot_part"]) for p in first["proposals"]] == [(DAY.isoformat(), "AM"), (DAY.isoformat(), "PM")]
    with new_session() as session:
        assert session.scalar(select(func.count()).select_from(Slot).where(Slot.date == DAY, Slot.slot_part == "AM")) == 1
    second = propose(env, "CPSAT", run="second").json()
    assert second["proposals"] == [] and second["metrics"]["queue_count"] == 0
    assert [status(app) for app in apps] == ["PROPOSED", "PROPOSED"]
    assert propose(env, horizon_end=(DAY - timedelta(days=1)).isoformat(), run="bad").status_code == 422


def foreign_booking(run, expert, day, part):
    """A published commitment from another run, written as the storage layer would hold it."""
    with new_session() as session, session.begin():
        other = uuid5(NAMESPACE_URL, f"DEMO:schedule:foreign:{run}")
        session.add(ScheduleRun(run_id=other, algorithm="EDF", parameters={}, created_at=port(ClockPort).now(),
                                status="PUBLISHED", metrics={}))
        session.flush()
        slot = session.scalar(text("SELECT id FROM evc.slot WHERE date = :d AND slot_part = :p"), dict(d=day, p=part))
        request = session.scalar(select(EvcRequest.id).limit(1))
        session.add(Assignment(id=uuid5(NAMESPACE_URL, f"DEMO:schedule:foreign-a:{run}"), evc_request_id=request,
                               slot_id=slot, expert_ids=[UUID(expert)], panel_role="DEMO_MEMBER", published=True,
                               schedule_run_id=other))


def test_publish_is_atomic_when_one_panel_became_double_booked(env):
    experts(env)
    apps = [enter(env), enter(env)]
    body = propose(env).json()
    late = max(body["proposals"], key=lambda p: (p["date"], p["slot_part"]))
    foreign_booking(body["run_id"], late["expert_ids"][0], late["date"], late["slot_part"])
    refused = publish(env, body["run_id"])
    assert refused.status_code == 409 and refused.json()["detail"] == "EVC_EXPERT_DOUBLE_BOOKED"
    assert [status(app) for app in apps] == ["PROPOSED", "PROPOSED"]
    assert ledger("evc.assignment_published") == []
    with new_session() as session:
        drafts = session.scalars(select(Assignment).where(Assignment.schedule_run_id == UUID(body["run_id"]))).all()
        assert len(drafts) == 2 and not any(d.published for d in drafts)
        assert session.get(ScheduleRun, UUID(body["run_id"])).status == "PROPOSED"


def test_publish_recheck_refuses_an_expert_who_became_unavailable(env):
    experts(env)
    app = enter(env)
    body = propose(env).json()
    [row] = body["proposals"]
    assert env.client.post(f"/api/evc/experts/{row['expert_ids'][0]}/availability", headers=BUREAU, json=dict(
        items=[dict(date=row["date"], slot_part=row["slot_part"], available=False)])).status_code == 200
    refused = publish(env, body["run_id"])
    assert refused.status_code == 409 and refused.json()["detail"] == "EVC_PUBLISH_RECHECK_FAILED"
    assert status(app) == "PROPOSED"


def test_concurrent_publishes_never_double_book(env):
    experts(env)
    first_app, second_app = enter(env), enter(env)
    run = propose(env).json()
    # A second live run holding the same experts on the same slot for the other request (only possible by
    # direct storage writes, since proposals reserve their experts): the database must still allow one winner.
    target = next(p for p in run["proposals"] if p["request_id"] == str(request_row(first_app).id))
    other = uuid5(NAMESPACE_URL, "DEMO:schedule:rival")
    parameters = dict(horizon_start_ordinal=DAY.toordinal(), horizon_end_ordinal=(DAY + timedelta(days=7)).toordinal())
    with new_session() as session, session.begin():
        session.execute(text("DELETE FROM evc.assignment WHERE evc_request_id = :r"), dict(r=request_row(second_app).id))
        session.add(ScheduleRun(run_id=other, algorithm="EDF", parameters=parameters, created_at=port(ClockPort).now(),
                                status="PROPOSED", metrics={}))
        session.flush()
        session.add(Assignment(id=uuid5(NAMESPACE_URL, "DEMO:schedule:rival-a"), evc_request_id=request_row(second_app).id,
                               slot_id=UUID(target["slot_id"]), expert_ids=[UUID(e) for e in target["expert_ids"]],
                               panel_role="DEMO_PANEL", published=False, schedule_run_id=other))
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


def test_proposed_cases_can_still_be_rejected_and_withdraw_their_drafts(env):
    experts(env)
    app = enter(env)
    body = propose(env, "EDF").json()
    rejected = action(env, app, "reject", 3, reason_code="DEMO_REASON")
    assert rejected.status_code == 200, rejected.text
    assert status(app) == "CANCELLED"
    with new_session() as session:
        assert session.scalar(select(func.count()).select_from(Assignment)) == 0
    assert publish(env, body["run_id"]).json()["detail"] == "EVC_RUN_EMPTY"


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
    late = max(body["proposals"], key=lambda p: (p["date"], p["slot_part"]))
    foreign_booking(body["run_id"], late["expert_ids"][0], late["date"], late["slot_part"])
    monkeypatch.setattr(schedule_service, "_memberships", lambda *args, **kwargs: [])
    refused = publish(env, body["run_id"])
    assert refused.status_code == 409 and refused.json()["detail"] == "EVC_EXPERT_DOUBLE_BOOKED"
    assert [status(app) for app in apps] == ["PROPOSED", "PROPOSED"] and ledger("evc.assignment_published") == []
    with new_session() as session:
        assert not any(session.scalars(select(Assignment.published).where(Assignment.schedule_run_id == UUID(body["run_id"]))))
