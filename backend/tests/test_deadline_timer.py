"""Deadline timer worker and alert ladder: restart recovery, overlap, vacancy, outage, ack, delivery, replay."""
import threading
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import OperationalError

from app.deadlines.alerts import AlertEngine, Scope, alert_config
from app.deadlines.models import Alert, Deadline, TimerOutcome
from app.deadlines.service import DeadlineEngine
from app.deadlines.wiring import clock
from app.deadlines.worker import TimerWorker
from app.platform import replay
from app.platform.db import new_session, unit_of_work
from app.platform.demo_seed import seed_directory
from app.platform.models import DomainEvent, Notification, Outbox
from app.platform.notifier import Notifier
from app.platform.providers import TRANSIENT, FakeProvider
from app.platform.recipients import directory, group_ref
from conftest import NORTHFIELD, SUNRISE, headers
from contracts.enums import Role
from contracts.types import Anchor, Principal, SubjectRef

SYSTEM = Principal(UUID(int=0), Role.SYSTEM)
INST = headers("INSTITUTION", SUNRISE)
NORTH_INST = headers("INSTITUTION", NORTHFIELD, user="00000000-0000-4000-9000-000000000004")
SOUTH_RO = {**headers("RO_OFFICER", user="00000000-0000-4000-9000-000000000005"), "X-Demo-Region": "Southern"}
NORTH_RO = {**headers("RO_OFFICER", user="00000000-0000-4000-9000-000000000008"), "X-Demo-Region": "Northern"}
BUREAU_HEAD = headers("BUREAU_HEAD", user="00000000-0000-4000-9000-000000000007")
AUDITOR = headers("AUDITOR", user="00000000-0000-4000-9000-000000000003")
COMMITTEE = headers("SCRUTINY_COMMITTEE", user="00000000-0000-4000-9000-000000000002")


@pytest.fixture
def env(client):
    seed_directory()
    return client


def submit(client, inst=SUNRISE, h=INST):
    app_id = client.post("/api/applications", headers=h, json={
        "institution_id": str(inst), "category": "NEW_PROGRAMME", "academic_year": "2027-28"}).json()["id"]
    assert client.post(f"/api/applications/{app_id}/submit", headers=h).status_code == 200
    return UUID(app_id)


def deadline_of(app_id, rule_id="AICTE_PROCESSING") -> Deadline:
    with new_session() as s:
        return s.scalars(select(Deadline).where(Deadline.subject_id == app_id, Deadline.rule_id == rule_id)).one()


def alerts_of(deadline_id) -> list[Alert]:
    with new_session() as s:
        return s.scalars(select(Alert).where(Alert.deadline_id == deadline_id)
                         .order_by(Alert.due_version, Alert.level)).all()


def outcomes_of(deadline_id) -> list[TimerOutcome]:
    with new_session() as s:
        return s.scalars(select(TimerOutcome).where(TimerOutcome.deadline_id == deadline_id)
                         .order_by(TimerOutcome.fence)).all()


def count(model, *where) -> int:
    with new_session() as s:
        return s.scalar(select(func.count()).select_from(model).where(*where))


def events(event_type) -> list[dict]:
    with new_session() as s:
        return [e.payload for e in s.scalars(select(DomainEvent).where(DomainEvent.event_type == event_type)
                                              .order_by(DomainEvent.seq))]


class Directory:
    """The real resolver, with chosen groups vacant or the whole directory down."""

    def __init__(self, vacant=(), down=False):
        self.vacant, self.down = set(vacant), down

    def resolve(self, role, resource):
        return directory.resolve(role, resource)

    def has_members(self, session, ref):
        if self.down:
            raise OperationalError("SELECT 1", {}, Exception("directory unavailable"))
        return ref not in self.vacant and directory.has_members(session, ref)


def worker(name="w1", engine=None, ahead=timedelta(0), **kw):
    return TimerWorker(worker_id=name, engine=engine, now=lambda: clock.now() + ahead, **kw)


# ---- scheduling, time travel, restart ----

def test_opening_a_deadline_schedules_its_first_level(env):
    d = deadline_of(submit(env))
    assert d.next_fire_at == d.due_at - timedelta(days=2)
    assert d.alert_level == 0


def test_future_timers_are_untouched(env):
    d = deadline_of(submit(env))
    assert worker().run_once() == 0
    after = deadline_of(d.subject_id)
    assert (after.next_fire_at, after.timer_fence, after.timer_claimed_by) == (d.next_fire_at, 0, None)
    assert outcomes_of(d.id) == [] and alerts_of(d.id) == []


def test_time_travel_triggers_the_first_alert(env):
    d = deadline_of(submit(env))
    clock.advance(29)
    assert worker().run_once() == 1
    [a] = alerts_of(d.id)
    assert (a.level, a.role, a.region, a.status, a.due_version) == (0, "RO_OFFICER", "Southern", "OPEN", 1)
    assert a.recipient_ref == group_ref(Role.RO_OFFICER, "Southern")
    assert sorted(r.channel for r in _outbox(a.id)) == ["email", "in_app"]
    assert events("dl.alert_raised") == [{"alert_id": str(a.id), "deadline_id": str(d.id), "level": 0,
                                          "role": "RO_OFFICER", "due_version": 1, "status": "OPEN"}]
    after = deadline_of(d.subject_id)
    assert after.next_fire_at == d.due_at and after.alert_level == 1 and after.timer_claimed_by is None
    [o] = outcomes_of(d.id)
    assert (o.outcome, o.levels_raised, o.scheduled_at) == ("ALERTED", 1, d.next_fire_at)


def test_api_time_travel_and_demo_timer_run(env):
    d = deadline_of(submit(env))
    assert env.post("/api/sim/clock", headers=INST, json={"days": 29}).status_code == 200
    assert env.post("/api/sim/timers/run", headers=INST).json() == {"processed": 1}
    assert [a.level for a in alerts_of(d.id)] == [0]


def test_a_due_timer_survives_a_worker_crash(env):
    d = deadline_of(submit(env))
    clock.advance(29)
    crashed = worker("crashed")
    assert len(crashed.claim()) == 1       # claimed, then the process died before doing anything
    assert worker("w2").run_once() == 0    # lease still held: nobody else takes it
    assert alerts_of(d.id) == []
    assert worker("w2", ahead=timedelta(seconds=121)).run_once() == 1   # after the lease runs out
    assert [a.level for a in alerts_of(d.id)] == [0]
    assert [o.worker for o in outcomes_of(d.id)] == ["w2"]


def test_a_rolled_back_run_leaves_the_work_retryable(env, monkeypatch):
    d = deadline_of(submit(env))
    clock.advance(29)
    calls = []

    def broken_enqueue(self, uow, msg):
        calls.append(msg)
        raise RuntimeError("outbox write failed")

    monkeypatch.setattr("app.platform.records.OutboxWriter.enqueue", broken_enqueue)
    assert worker().run_once() == 1
    assert calls and alerts_of(d.id) == [] and events("dl.alert_raised") == []   # all rolled back together
    [o] = outcomes_of(d.id)
    assert (o.outcome, o.detail) == ("RETRY", "PROCESSING_ERROR")
    monkeypatch.undo()
    assert worker(ahead=timedelta(minutes=16)).run_once() == 1
    assert [a.level for a in alerts_of(d.id)] == [0]


def test_overlapping_runs_create_one_outcome(env):
    ids = [deadline_of(submit(env)).id for _ in range(3)]
    clock.advance(29)
    barrier = threading.Barrier(4)
    done = []

    def run(name):
        barrier.wait()
        done.append(worker(name).run_once())

    threads = [threading.Thread(target=run, args=(f"w{i}",)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(done) == 3
    for deadline_id in ids:
        assert len(outcomes_of(deadline_id)) == 1
        assert [a.level for a in alerts_of(deadline_id)] == [0]
    assert len(events("dl.alert_raised")) == 3


def test_a_worker_that_lost_its_claim_records_nothing(env):
    d = deadline_of(submit(env))
    clock.advance(29)
    slow = worker("slow")
    [stale] = slow.claim()
    assert worker("fast", ahead=timedelta(seconds=121)).run_once() == 1
    assert slow.process(stale) == 0
    assert len(outcomes_of(d.id)) == 1 and len(alerts_of(d.id)) == 1


def test_concurrent_duplicate_alert_attempts_create_one_alert(env):
    d = deadline_of(submit(env))
    engine = AlertEngine()
    barrier = threading.Barrier(2)
    errors = []

    def attempt():
        try:
            with unit_of_work(SYSTEM) as uow:
                row = uow.session.get(Deadline, d.id)
                config, ladder = alert_config(row)
                barrier.wait()
                engine.raise_level(uow, row, ladder[0], config, Scope(SUNRISE, "Southern"), None, None, clock.now())
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    [a] = alerts_of(d.id)
    assert len(events("dl.alert_raised")) == 1
    assert len(_outbox(a.id)) == 2


def test_catch_up_after_downtime_raises_every_missed_level_once(env):
    d = deadline_of(submit(env))
    clock.advance(40)
    assert worker().run_once() == 1
    alerts = alerts_of(d.id)
    assert [(a.level, a.role, a.status) for a in alerts] == [
        (0, "RO_OFFICER", "ESCALATED"), (1, "RO_OFFICER", "ESCALATED"),
        (2, "BUREAU_OFFICER", "ESCALATED"), (3, "BUREAU_HEAD", "OPEN")]
    assert [e["reason"] for e in events("dl.alert_escalated")] == ["WINDOW_ELAPSED"] * 3
    assert deadline_of(d.subject_id).next_fire_at is None
    [o] = outcomes_of(d.id)
    assert (o.outcome, o.levels_raised) == ("ALERTED", 4)
    assert worker().run_once() == 0


def test_window_elapsing_unacknowledged_escalates_one_level(env):
    d = deadline_of(submit(env))
    clock.advance(29)
    worker().run_once()
    clock.advance(2)    # past the due instant: level 1
    assert worker().run_once() == 1
    first, second = alerts_of(d.id)
    assert (first.status, second.level, second.reason, second.from_alert_id) == (
        "ESCALATED", 1, "WINDOW_ELAPSED", first.id)
    assert deadline_of(d.subject_id).next_fire_at == d.due_at + timedelta(days=3)


# ---- vacancy and outage ----

def test_explicit_vacancy_advances_to_the_next_role_at_once(env):
    d = deadline_of(submit(env))
    clock.advance(29)
    vacant = Directory(vacant={group_ref(Role.RO_OFFICER, "Southern")})
    assert worker(engine=AlertEngine(vacant)).run_once() == 1
    alerts = alerts_of(d.id)
    assert [(a.level, a.role, a.status, a.reason) for a in alerts] == [
        (0, "RO_OFFICER", "VACANT", None), (1, "RO_OFFICER", "VACANT", "VACANCY"),
        (2, "BUREAU_OFFICER", "OPEN", "VACANCY")]
    assert [len(_outbox(a.id)) for a in alerts] == [0, 0, 2]   # nothing queued for a vacant group
    assert [e["status"] for e in events("dl.alert_raised")] == ["VACANT", "VACANT", "OPEN"]
    assert [e["reason"] for e in events("dl.alert_escalated")] == ["VACANCY", "VACANCY"]
    # the next level still waits for its own window
    assert deadline_of(d.subject_id).next_fire_at == d.due_at + timedelta(days=7)


def test_resolver_outage_is_not_treated_as_vacancy(env):
    d = deadline_of(submit(env))
    clock.advance(29)
    assert worker(engine=AlertEngine(Directory(down=True))).run_once() == 1
    assert alerts_of(d.id) == [] and events("dl.alert_raised") == [] and events("dl.alert_escalated") == []
    after = deadline_of(d.subject_id)
    assert after.alert_level == 0 and after.next_fire_at > clock.now()
    [o] = outcomes_of(d.id)
    assert (o.outcome, o.detail) == ("RETRY", "RESOLVER_UNAVAILABLE")
    # still down at the retry: still nothing
    assert worker(engine=AlertEngine(Directory(down=True)), ahead=timedelta(minutes=16)).run_once() == 1
    assert alerts_of(d.id) == []
    # back up: the level is raised for the role it was meant for
    assert worker(ahead=timedelta(minutes=32)).run_once() == 1
    assert [(a.level, a.status) for a in alerts_of(d.id)] == [(0, "OPEN")]


def test_unknown_scope_stops_without_guessing_a_recipient(env):
    with unit_of_work(SYSTEM) as uow:
        subject = SubjectRef("obligation", UUID(int=99))
        DeadlineEngine().open(uow, subject, "INSTITUTION_RESPONSE", Anchor(at=clock.now()), "aph-2024-27@r1")
    clock.advance(14)
    assert worker().run_once() == 1
    with new_session() as s:
        d = s.scalars(select(Deadline).where(Deadline.subject_id == UUID(int=99))).one()
    assert alerts_of(d.id) == [] and d.next_fire_at is None
    assert [(o.outcome, o.detail) for o in outcomes_of(d.id)] == [("FAILED", "SCOPE_UNRESOLVED")]


def test_paused_and_closed_deadlines_are_not_fired(env):
    paused, closed = deadline_of(submit(env)), deadline_of(submit(env))
    with unit_of_work(SYSTEM) as uow:
        DeadlineEngine().pause_internal(uow, SubjectRef("application", paused.subject_id), "AICTE_PROCESSING")
        DeadlineEngine().close(uow, SubjectRef("application", closed.subject_id), "AICTE_PROCESSING", "MET")
    clock.advance(40)
    assert worker().run_once() == 0
    assert alerts_of(paused.id) == [] and alerts_of(closed.id) == []


def test_resuming_starts_a_fresh_ladder_for_the_new_due_version(env):
    d = deadline_of(submit(env))
    clock.advance(29)
    worker().run_once()
    subject = SubjectRef("application", d.subject_id)
    with unit_of_work(SYSTEM) as uow:
        DeadlineEngine().pause_internal(uow, subject, "AICTE_PROCESSING")
    clock.advance(1)
    with unit_of_work(SYSTEM) as uow:
        DeadlineEngine().resume_internal(uow, subject, "AICTE_PROCESSING")
    after = deadline_of(d.subject_id)
    assert (after.due_version, after.alert_level, after.next_fire_at <= clock.now()) == (2, 0, True)
    assert worker().run_once() == 1
    assert [(a.due_version, a.level) for a in alerts_of(d.id)] == [(1, 0), (2, 0)]
    assert deadline_of(d.subject_id).next_fire_at == after.due_at


def test_a_resumed_deadline_with_nothing_due_is_rescheduled(env):
    d = deadline_of(submit(env))
    subject = SubjectRef("application", d.subject_id)
    with unit_of_work(SYSTEM) as uow:
        DeadlineEngine().pause_internal(uow, subject, "AICTE_PROCESSING")
    clock.advance(3)
    with unit_of_work(SYSTEM) as uow:
        DeadlineEngine().resume_internal(uow, subject, "AICTE_PROCESSING")
    assert worker().run_once() == 1
    after = deadline_of(d.subject_id)
    assert after.next_fire_at == after.due_at - timedelta(days=2)
    assert outcomes_of(d.id)[-1].outcome == "SCHEDULED" and alerts_of(d.id) == []


# ---- acknowledgement ----

def test_acknowledgement_stops_escalation(env):
    d = deadline_of(submit(env))
    clock.advance(29)
    worker().run_once()
    [a] = alerts_of(d.id)
    r = env.post(f"/api/alerts/{a.id}/ack", headers=SOUTH_RO)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ACKNOWLEDGED"
    assert deadline_of(d.subject_id).next_fire_at is None
    clock.advance(20)
    assert worker().run_once() == 0
    assert [x.level for x in alerts_of(d.id)] == [0]
    assert events("dl.alert_acknowledged") == [{"alert_id": str(a.id), "deadline_id": str(d.id), "level": 0,
                                                "role": "RO_OFFICER", "due_version": 1}]


def test_an_ack_racing_a_claimed_timer_still_stops_escalation(env):
    d = deadline_of(submit(env))
    clock.advance(29)
    worker().run_once()
    clock.advance(2)
    w = worker("w")
    [claim] = w.claim()                      # the worker holds the claim ...
    a = alerts_of(d.id)[0]
    assert env.post(f"/api/alerts/{a.id}/ack", headers=SOUTH_RO).status_code == 200   # ... the ack lands first
    w.process(claim)
    assert [x.level for x in alerts_of(d.id)] == [0]
    assert outcomes_of(d.id)[-1].outcome == "ACKNOWLEDGED"


def test_ack_is_idempotent_and_honours_the_idempotency_key(env):
    d = deadline_of(submit(env))
    clock.advance(29)
    worker().run_once()
    [a] = alerts_of(d.id)
    h = {**SOUTH_RO, "Idempotency-Key": "ack-key-0001"}
    first = env.post(f"/api/alerts/{a.id}/ack", headers=h)
    again = env.post(f"/api/alerts/{a.id}/ack", headers=h)
    assert again.headers.get("Idempotent-Replayed") == "true" and again.json() == first.json()
    assert env.post(f"/api/alerts/{a.id}/ack", headers=SOUTH_RO).status_code == 200
    assert len(events("dl.alert_acknowledged")) == 1


def test_ack_is_only_for_the_addressed_role_and_scope(env):
    d = deadline_of(submit(env))
    clock.advance(29)
    worker().run_once()
    [a] = alerts_of(d.id)
    assert env.post(f"/api/alerts/{a.id}/ack", headers=NORTH_RO).status_code == 403     # other region
    assert env.post(f"/api/alerts/{a.id}/ack", headers=INST).status_code == 403         # not addressed to it
    assert env.post(f"/api/alerts/{a.id}/ack", headers=BUREAU_HEAD).status_code == 403  # not addressed to it
    assert env.post(f"/api/alerts/{a.id}/ack", headers=AUDITOR).status_code == 403      # read-only role
    assert env.post(f"/api/alerts/{UUID(int=5)}/ack", headers=SOUTH_RO).status_code == 404
    assert events("dl.alert_acknowledged") == []


def test_a_vacant_alert_cannot_be_acknowledged(env):
    d = deadline_of(submit(env))
    clock.advance(29)
    worker(engine=AlertEngine(Directory(vacant={group_ref(Role.RO_OFFICER, "Southern")}))).run_once()
    vacant = alerts_of(d.id)[0]
    assert env.post(f"/api/alerts/{vacant.id}/ack", headers=SOUTH_RO).status_code == 409


# ---- delivery and replay ----

def test_delivery_retry_does_not_create_another_domain_alert(env):
    d = deadline_of(submit(env))
    clock.advance(29)
    worker().run_once()
    [a] = alerts_of(d.id)
    fake = FakeProvider(script=[TRANSIENT])
    notifier = Notifier({"email": fake}, worker_id="n1", now=clock.now, rng=lambda: 1.0, backoff_base=30,
                        max_attempts=3, lease_seconds=60)
    notifier.run_once()
    notifier.now = lambda: clock.now() + timedelta(minutes=5)
    notifier.run_once()
    assert len(fake.sent) == 1
    assert {r.status for r in _outbox(a.id)} == {"DELIVERED"}
    assert count(Notification, Notification.alert_id == a.id) == 1
    assert worker(ahead=timedelta(minutes=5)).run_once() == 0
    assert len(alerts_of(d.id)) == 1 and len(events("dl.alert_raised")) == 1


def test_replay_rebuilds_alerts_and_sends_nothing(env):
    d = deadline_of(submit(env))
    clock.advance(40)
    worker(engine=AlertEngine(Directory(vacant={group_ref(Role.BUREAU_OFFICER)}))).run_once()
    env.post(f"/api/alerts/{alerts_of(d.id)[-1].id}/ack", headers=BUREAU_HEAD)
    queued, raised = count(Outbox), count(Alert)
    report = replay.replay()
    assert report["ok"], report
    alerts = {p["name"]: p for p in report["projections"]}["alerts"]
    assert alerts["status"] == "MATCH" and alerts["records"] == raised == 4
    assert count(Outbox) == queued and count(Alert) == raised


# ---- listing ----

def test_alert_list_is_scoped_by_role_region_and_institution(env):
    south = submit(env)
    submit(env, NORTHFIELD, NORTH_INST)
    with unit_of_work(SYSTEM) as uow:
        DeadlineEngine().open(uow, SubjectRef("application", south), "INSTITUTION_RESPONSE",
                              Anchor(at=clock.now()), "aph-2024-27@r1")
    clock.advance(29)
    worker().run_once()

    def listed(h, **params):
        r = env.get("/api/alerts", headers=h, params=params)
        assert r.status_code == 200, r.text
        return sorted((x["role"], x["region"], x["level"]) for x in r.json())

    everything = listed(AUDITOR)
    assert ("INSTITUTION", "Southern", 0) in everything and ("RO_OFFICER", "Northern", 0) in everything
    assert listed(INST) == [("INSTITUTION", "Southern", 0)]
    assert listed(NORTH_INST) == []
    assert all(region == "Southern" for _, region, _ in listed(SOUTH_RO)) and listed(SOUTH_RO)
    north_ro = listed(NORTH_RO)
    assert ("RO_OFFICER", "Northern", 0) in north_ro and all(region == "Northern" for _, region, _ in north_ro)
    assert listed(NORTH_RO, region="Southern") == north_ro   # always its own region
    assert all(region == "Northern" for _, region, _ in listed(BUREAU_HEAD, region="Northern"))
    assert listed(COMMITTEE) == []
    assert env.get("/api/alerts", headers=AUDITOR, params={"status": "BOGUS"}).status_code == 422


def _outbox(alert_id):
    with new_session() as s:
        return s.scalars(select(Outbox).where(Outbox.alert_id == alert_id)).all()


# ---- alerts lead back to the case and the obligation ----

def test_alerts_carry_the_rule_due_date_and_case(env):
    app_id = submit(env)
    d = deadline_of(app_id)
    clock.advance(29)
    worker().run_once()
    [listed] = [a for a in env.get("/api/alerts", headers=SOUTH_RO).json() if a["deadline_id"] == str(d.id)]
    assert (listed["rule_id"], listed["due_date"], listed["deadline_status"]) == (
        "AICTE_PROCESSING", d.due_date.isoformat(), "RUNNING")
    assert (listed["subject_type"], listed["subject_id"], listed["application_id"]) == (
        "application", str(app_id), str(app_id))
    acked = env.post(f"/api/alerts/{listed['id']}/ack", headers=SOUTH_RO).json()
    assert acked["rule_id"] == "AICTE_PROCESSING" and acked["application_id"] == str(app_id)


def test_an_obligation_alert_names_the_application_it_belongs_to(env):
    from app.compliance.demo_seed import seed_letters
    from app.compliance.models import Obligation

    seed_letters()  # one of the demo letters is already overdue
    worker().run_once()
    with new_session() as s:
        obligations = {o.id: o for o in s.scalars(select(Obligation)).all()}
    traced = [a for a in env.get("/api/alerts", headers=AUDITOR).json() if a["subject_type"] == "obligation"]
    assert traced, "the overdue demo obligation raised no alert"
    # five days overdue: reminder, breach and the first escalation have all been raised for the demo
    assert {a["level"] for a in traced} == {0, 1, 2}
    assert {a["role"] for a in traced} == {"INSTITUTION", "RO_OFFICER", "BUREAU_OFFICER"}
    for a in traced:
        o = obligations[UUID(a["subject_id"])]
        assert a["application_id"] == str(o.application_id) and a["deadline_id"] == str(o.deadline_id)
        assert a["rule_id"] == o.rule_id and a["due_date"] == o.due_date.isoformat()
    inst = env.get("/api/alerts", headers=INST).json()
    assert all(a["application_id"] is not None for a in inst if a["subject_type"] == "obligation")
