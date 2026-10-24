"""Notification delivery from the outbox: retries, dead letters, leases, concurrency and the inbox."""
import smtplib
import threading
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.platform.db import new_session, unit_of_work
from app.platform.demo_seed import seed_directory
from app.platform.models import DeliveryAttempt, Notification, Outbox
from app.platform.notifier import Notifier
from app.platform.providers import AMBIGUOUS, PERMANENT, TRANSIENT, FakeProvider, Message, SmtpProvider, DeliveryError
from app.platform.recipients import directory, group_ref
from app.platform.records import OutboxWriter
from conftest import SUNRISE, headers
from contracts.enums import Role
from contracts.types import OutboundMessage, Principal

SYSTEM = Principal(UUID(int=0), Role.SYSTEM)
SUNRISE_GROUP = group_ref(Role.INSTITUTION, institution_id=SUNRISE)


class Clock:
    def __init__(self):
        self.at = datetime.now(timezone.utc)

    def __call__(self):
        return self.at

    def tick(self, seconds):
        self.at += timedelta(seconds=seconds)


@pytest.fixture
def env(client):
    seed_directory()
    return client


def enqueue(channel="email", template="deadline.reminder", ref=SUNRISE_GROUP, alert=None):
    alert = alert or uuid4()
    with unit_of_work(SYSTEM) as uow:
        OutboxWriter().enqueue(uow, OutboundMessage(alert, channel, template, ref))
    return alert


def worker(provider=None, clock=None, name="w1", **kw):
    return Notifier({"email": provider or FakeProvider()}, worker_id=name, now=clock or Clock(),
                    rng=lambda: 1.0, backoff_base=30, backoff_cap=600, max_attempts=kw.pop("max_attempts", 3),
                    lease_seconds=60, **kw)


def row(alert, channel="email"):
    with new_session() as s:
        return s.scalars(select(Outbox).where(Outbox.alert_id == alert, Outbox.channel == channel)).one()


def attempts(alert):
    with new_session() as s:
        return s.scalars(select(DeliveryAttempt).join(Outbox, Outbox.id == DeliveryAttempt.outbox_id)
                         .where(Outbox.alert_id == alert).order_by(DeliveryAttempt.finished_at)).all()


def test_successful_send_resolves_the_group_to_addresses(env):
    fake = FakeProvider()
    alert = enqueue()
    assert worker(fake).run_once() == 1
    r = row(alert)
    assert (r.status, r.attempts, r.claimed_by) == ("DELIVERED", 1, None)
    assert fake.sent[0].addresses == ("inst.sunrise@awoc.example.invalid",)
    assert [a.outcome for a in attempts(alert)] == ["DELIVERED"]


def test_delivered_messages_are_not_sent_again(env):
    fake = FakeProvider()
    enqueue()
    w = worker(fake)
    w.run_once()
    assert w.run_once() == 0
    assert len(fake.sent) == 1


def test_queueing_the_same_alert_twice_gives_one_row(env):
    alert = enqueue()
    enqueue(alert=alert)
    with new_session() as s:
        assert s.scalar(select(func.count()).select_from(Outbox).where(Outbox.alert_id == alert)) == 1


def test_temporary_failure_is_retried_with_backoff(env):
    clock = Clock()
    alert = enqueue()
    w = worker(FakeProvider(script=[TRANSIENT]), clock)
    w.run_once()
    r = row(alert)
    assert (r.status, r.last_error) == ("PENDING", "SCRIPTED_TRANSIENT")
    assert r.next_attempt_at == clock.at + timedelta(seconds=30)
    assert w.run_once() == 0                    # not due yet
    clock.tick(31)
    assert w.run_once() == 1
    assert row(alert).status == "DELIVERED"
    assert [a.outcome for a in attempts(alert)] == [TRANSIENT, "DELIVERED"]


def test_backoff_grows_exponentially_with_bounded_jitter():
    w = Notifier({}, backoff_base=30, backoff_cap=600, rng=lambda: 0.0, now=Clock())
    assert [w.backoff(n).total_seconds() for n in (1, 2, 3, 6)] == [15, 30, 60, 300]
    w.rng = lambda: 1.0
    assert w.backoff(10).total_seconds() == 600  # capped


def test_permanent_failure_goes_straight_to_dead_letter(env):
    alert = enqueue()
    worker(FakeProvider(script=[PERMANENT])).run_once()
    r = row(alert)
    assert (r.status, r.attempts) == ("DEAD", 1) and r.dead_at is not None


def test_retries_are_exhausted_into_dead_letter(env):
    clock = Clock()
    alert = enqueue()
    w = worker(FakeProvider(script=[TRANSIENT] * 5), clock, max_attempts=3)
    for _ in range(3):
        w.run_once()
        clock.tick(10_000)
    r = row(alert)
    assert (r.status, r.attempts) == ("DEAD", 3)
    assert len(attempts(alert)) == 3


def test_ambiguous_failures_are_retried_and_recorded_as_such(env):
    clock = Clock()
    fake = FakeProvider(script=[AMBIGUOUS])
    alert = enqueue()
    w = worker(fake, clock)
    w.run_once()
    clock.tick(10_000)
    w.run_once()
    assert [a.outcome for a in attempts(alert)] == [AMBIGUOUS, "DELIVERED"]  # the recipient may have it twice


def test_unknown_template_and_missing_recipient_are_dead_letters(env):
    a = enqueue(template="something.unknown")
    b = enqueue(ref=group_ref(Role.RO_OFFICER, "Western"))       # nobody holds this post
    worker().run_once()
    assert (row(a).status, row(a).last_error) == ("DEAD", "UNKNOWN_TEMPLATE")
    assert (row(b).status, row(b).last_error) == ("DEAD", "NO_RECIPIENT")


def test_vacant_posts_can_be_detected_before_queueing(env):
    with new_session() as s:
        assert directory.has_members(s, group_ref(Role.RO_OFFICER, "Southern"))
        assert not directory.has_members(s, group_ref(Role.RO_OFFICER, "Western"))


def test_two_workers_never_claim_the_same_message(env):
    for _ in range(40):
        enqueue()
    claimed: dict[str, list] = {}
    barrier = threading.Barrier(2)

    def run(name):
        w = worker(name=name)
        barrier.wait()
        claimed[name] = [c.id for c in w.claim(limit=40)]

    threads = [threading.Thread(target=run, args=(n,)) for n in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not set(claimed["a"]) & set(claimed["b"])
    assert len(claimed["a"]) + len(claimed["b"]) == 40


def test_a_crashed_workers_messages_are_picked_up_after_the_lease(env):
    clock = Clock()
    alert = enqueue()
    crashed = worker(clock=clock, name="crashed")
    assert len(crashed.claim()) == 1               # claims, then dies without finishing
    survivor = worker(FakeProvider(), clock, name="survivor")
    assert survivor.run_once() == 0                # lease still valid
    clock.tick(61)
    assert survivor.run_once() == 1
    r = row(alert)
    assert (r.status, r.attempts) == ("DELIVERED", 2)


def test_a_worker_that_lost_its_lease_cannot_overwrite_the_result(env):
    clock = Clock()
    alert = enqueue()
    slow_provider = FakeProvider(script=[TRANSIENT])
    slow = worker(slow_provider, clock, name="slow")
    (claim,) = slow.claim()
    clock.tick(61)
    worker(FakeProvider(), clock, name="fast").run_once()    # takes over and delivers
    slow.deliver(claim)                                       # wakes up late
    assert row(alert).status == "DELIVERED"
    assert slow_provider.sent == [] and slow_provider.script == [TRANSIENT]   # recipient already reached: no resend
    assert [a.outcome for a in attempts(alert)] == ["DELIVERED", "DELIVERED_LEASE_LOST"]


def test_in_app_delivery_is_exactly_once_even_after_a_crash(env):
    clock = Clock()
    alert = enqueue(channel="in_app")
    worker(clock=clock, name="crashed").claim()
    clock.tick(61)
    w = worker(clock=clock, name="survivor")
    w.run_once()
    w.run_once()
    with new_session() as s:
        assert s.scalar(select(func.count()).select_from(Notification).where(Notification.alert_id == alert)) == 1


def test_inbox_shows_notifications_only_to_group_members(env):
    enqueue(channel="in_app")
    worker().run_once()
    mine = env.get("/api/notifications/inbox", headers=headers("INSTITUTION", SUNRISE)).json()
    assert [n["subject"] for n in mine] == ["Deadline reminder"]
    other = headers("INSTITUTION", UUID("00000000-0000-4000-8000-000000000002"),
                    user="00000000-0000-4000-9000-000000000004")
    assert env.get("/api/notifications/inbox", headers=other).json() == []
    assert env.post(f"/api/notifications/inbox/{mine[0]['id']}/read", headers=other).status_code == 404
    read = env.post(f"/api/notifications/inbox/{mine[0]['id']}/read", headers=headers("INSTITUTION", SUNRISE))
    assert read.json()["read_at"] is not None


def test_delivery_health_and_operations_are_for_oversight_only(env):
    alert = enqueue()
    worker(FakeProvider(script=[PERMANENT])).run_once()
    head = headers("BUREAU_HEAD", user="00000000-0000-4000-9000-000000000007")
    h = env.get("/api/notifications/health", headers=head).json()
    assert h["by_status"]["DEAD"] == 1 and h["attempts_24h"] == {"PERMANENT": 1}
    dead = env.get("/api/notifications/outbox?status=DEAD", headers=head).json()
    assert dead[0]["alert_id"] == str(alert) and "recipient" not in str(dead[0]).lower()
    assert env.post(f"/api/notifications/outbox/{dead[0]['id']}/retry", headers=head).status_code == 200
    assert row(alert).status == "PENDING"
    inst = headers("INSTITUTION", SUNRISE)
    assert env.get("/api/notifications/health", headers=inst).status_code == 403
    assert env.post(f"/api/notifications/outbox/{dead[0]['id']}/retry",
                    headers=headers("AUDITOR")).status_code == 403


class FakeSMTP:
    behaviour = None
    sent: list = []

    def __init__(self, host, port, timeout):
        if FakeSMTP.behaviour == "refused":
            raise ConnectionRefusedError()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        pass

    def send_message(self, msg):
        b = FakeSMTP.behaviour
        if b == "timeout":
            raise TimeoutError()
        if b == "550":
            raise smtplib.SMTPDataError(550, b"mailbox unavailable")
        if b == "451":
            raise smtplib.SMTPDataError(451, b"try later")
        FakeSMTP.sent.append(msg)


@pytest.mark.parametrize("behaviour, category", [("refused", TRANSIENT), ("timeout", AMBIGUOUS),
                                                  ("550", PERMANENT), ("451", TRANSIENT)])
def test_smtp_failures_are_classified(monkeypatch, behaviour, category):
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    FakeSMTP.behaviour = behaviour
    with pytest.raises(DeliveryError) as e:
        SmtpProvider("mail.test", 25, "no-reply@awoc.example.invalid").send(
            Message(uuid4(), uuid4(), "email", "deadline.reminder", ("a@awoc.example.invalid",), 1))
    assert e.value.category == category


def test_smtp_message_carries_no_case_details_and_a_stable_message_id(monkeypatch):
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    FakeSMTP.behaviour, FakeSMTP.sent = None, []
    outbox_id, alert = uuid4(), uuid4()
    SmtpProvider("mail.test", 25, "no-reply@awoc.example.invalid").send(
        Message(outbox_id, alert, "email", "deadline.breached", ("a@awoc.example.invalid",), 1))
    m = FakeSMTP.sent[0]
    assert m["Message-ID"].startswith(f"<{outbox_id}.") and m["To"] == "a@awoc.example.invalid"
    SmtpProvider("mail.test", 25, "no-reply@awoc.example.invalid").send(
        Message(outbox_id, alert, "email", "deadline.breached", ("a@awoc.example.invalid",), 2))
    assert FakeSMTP.sent[1]["Message-ID"] == m["Message-ID"]          # stable across retries
    assert str(alert) in m.get_content() and "Sunrise" not in m.get_content()


def test_unconfigured_smtp_is_a_permanent_failure():
    with pytest.raises(DeliveryError) as e:
        SmtpProvider("", 25, "x@awoc.example.invalid").send(
            Message(uuid4(), uuid4(), "email", "deadline.reminder", ("a@awoc.example.invalid",), 1))
    assert e.value.reason == "NOT_CONFIGURED"


# ---- privacy and metrics (P3-10) ----

def two_member_group():
    ref = group_ref(Role.BUREAU_OFFICER, "Twoshire")
    with new_session() as s:
        for n in (11, 12):
            user = UUID(f"00000000-0000-4000-9000-0000000000{n}")
            directory.add_member(s, ref, user)
            directory.set_contact(s, user, "email", f"officer{n}@awoc.example.invalid")
        s.commit()
    return ref


def test_each_recipient_gets_their_own_message(env, monkeypatch):
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    FakeSMTP.behaviour, FakeSMTP.sent = None, []
    enqueue(ref=two_member_group())
    w = Notifier({"email": SmtpProvider("mail.test", 25, "no-reply@awoc.example.invalid")}, worker_id="w",
                 now=Clock(), max_attempts=3)
    w.run_once()
    tos = [m["To"] for m in FakeSMTP.sent]
    assert sorted(tos) == ["officer11@awoc.example.invalid", "officer12@awoc.example.invalid"]
    for m in FakeSMTP.sent:     # no message mentions the other recipient anywhere
        other = ({"officer11", "officer12"} - {m["To"].split("@")[0]}).pop()
        assert other not in m.as_string()


def test_a_retry_only_goes_to_recipients_not_yet_reached(env):
    clock = Clock()
    fake = FakeProvider(script=[None, TRANSIENT])          # first recipient ok, second fails
    alert = enqueue(ref=two_member_group())
    w = worker(fake, clock)
    w.run_once()
    assert row(alert).status == "PENDING" and len(fake.sent) == 1
    first = fake.sent[0].addresses
    clock.tick(10_000)
    w.run_once()
    assert row(alert).status == "DELIVERED"
    assert [m.addresses for m in fake.sent] == [first, tuple(a for a in (
        "officer11@awoc.example.invalid", "officer12@awoc.example.invalid") if (a,) != first)]


def test_a_refused_recipient_dead_letters_the_message_without_resending_to_the_others(env):
    clock = Clock()
    fake = FakeProvider(script=[None, "REFUSED"])
    alert = enqueue(ref=two_member_group())
    worker(fake, clock).run_once()
    r = row(alert)
    assert (r.status, r.last_error) == ("DEAD", "SOME_RECIPIENTS_REFUSED") and len(fake.sent) == 1


def test_recipient_records_hold_no_addresses(env):
    from app.platform.models import DeliveryRecipient
    enqueue(ref=two_member_group())
    worker().run_once()
    with new_session() as s:
        keys = s.scalars(select(DeliveryRecipient.recipient_key)).all()
    assert len(keys) == 2 and not any("@" in k for k in keys)


def test_provider_errors_are_logged_without_their_text(env, caplog):
    class Leaky:
        name = "leaky"

        def send(self, msg):
            raise RuntimeError(f"cannot reach {msg.addresses[0]}")

    enqueue()
    Notifier({"email": Leaky()}, worker_id="w", now=Clock(), max_attempts=3).run_once()
    assert "RuntimeError" in caplog.text and "@" not in caplog.text


def test_first_try_rate_counts_only_first_attempts(env):
    clock = Clock()
    a = enqueue()
    b = enqueue()
    fake = FakeProvider(script=[None, TRANSIENT])         # a: ok first time; b: fails, then ok
    w = worker(fake, clock)
    w.run_once()
    clock.tick(10_000)
    w.run_once()
    from app.platform.notifier import health
    h = health(clock())
    assert (row(a).status, row(b).status) == ("DELIVERED", "DELIVERED")
    assert h["first_tries_24h"] == 2
    assert h["first_try_success_rate_24h"] == 0.5          # the old formula said 2/3
    assert h["delivered_after_retry_24h"] == 1


def test_a_requeued_message_is_not_counted_as_a_new_first_try(env):
    from app.platform.notifier import health, requeue
    clock = Clock()
    alert = enqueue()
    w = worker(FakeProvider(script=[PERMANENT]), clock)
    w.run_once()
    requeue(row(alert).id, clock())
    clock.tick(5)
    w.run_once()                                            # delivered; attempt_no restarts at 1
    h = health(clock())
    assert (h["first_tries_24h"], h["first_try_success_rate_24h"]) == (1, 0.0)


# ---- reliability and privacy (P3-16) ----

def test_a_worker_that_lost_its_lease_stops_sending(env):
    clock = Clock()
    alert = enqueue(ref=two_member_group())
    slow_provider = FakeProvider()
    slow = worker(slow_provider, clock, name="slow")
    (claim,) = slow.claim()
    clock.tick(61)
    assert len(worker(FakeProvider(), clock, name="taker").claim()) == 1   # taken over, still in progress
    slow.deliver(claim)
    assert slow_provider.sent == []
    assert [a.outcome for a in attempts(alert)] == ["TRANSIENT_LEASE_LOST"]


def test_the_lease_is_renewed_while_a_long_message_is_being_sent(env):
    clock = Clock()
    alert = enqueue(ref=two_member_group())

    class Slow(FakeProvider):
        def send(self, msg):
            clock.tick(50)            # each send takes most of a 60 s lease
            return super().send(msg)

    provider = Slow()
    worker(provider, clock).run_once()
    assert len(provider.sent) == 2 and row(alert).status == "DELIVERED"


def test_a_provider_wide_failure_blames_no_recipient_and_requeue_recovers(env):
    from app.platform.notifier import requeue
    clock = Clock()
    alert = enqueue(ref=two_member_group())
    Notifier({"email": SmtpProvider("", 25, "x@awoc.example.invalid")}, worker_id="w", now=clock, max_attempts=3).run_once()
    assert (row(alert).status, row(alert).last_error) == ("DEAD", "NOT_CONFIGURED")
    requeue(row(alert).id, clock())
    fixed = FakeProvider()
    clock.tick(5)
    worker(fixed, clock).run_once()
    assert len(fixed.sent) == 2 and row(alert).status == "DELIVERED"


def test_requeue_retries_refused_recipients_but_never_resends_to_reached_ones(env):
    from app.platform.notifier import requeue
    clock = Clock()
    alert = enqueue(ref=two_member_group())
    first = FakeProvider(script=[None, "REFUSED"])
    worker(first, clock).run_once()
    assert row(alert).last_error == "SOME_RECIPIENTS_REFUSED"
    requeue(row(alert).id, clock())
    clock.tick(5)
    second = FakeProvider()
    worker(second, clock).run_once()
    assert row(alert).status == "DELIVERED"
    assert len(second.sent) == 1 and second.sent[0].addresses != first.sent[0].addresses


def test_a_message_level_failure_stops_before_the_other_recipients(env):
    fake = FakeProvider(script=[PERMANENT])
    alert = enqueue(ref=two_member_group())
    worker(fake).run_once()
    assert (row(alert).status, row(alert).last_error, len(fake.sent)) == ("DEAD", "SCRIPTED_PERMANENT", 0)
    from app.platform.models import DeliveryRecipient
    with new_session() as s:
        assert s.scalar(select(func.count()).select_from(DeliveryRecipient)) == 0   # nobody marked refused


def test_recipient_records_are_keyed_digests(env, monkeypatch):
    from app.platform import notifier
    from app.platform.models import DeliveryRecipient
    enqueue(ref=two_member_group())
    worker().run_once()
    with new_session() as s:
        keys = s.scalars(select(DeliveryRecipient.recipient_key)).all()
    assert keys and all(k.startswith("h1:") for k in keys)
    oid = UUID(int=1)
    a = notifier.recipient_key(oid, "x@awoc.example.invalid")
    monkeypatch.setattr(notifier, "settings", __import__("dataclasses").replace(notifier.settings, notify_recipient_key="k" * 32))
    assert notifier.recipient_key(oid, "x@awoc.example.invalid") != a       # depends on the configured key
    assert notifier.legacy_recipient_key(oid, "x@awoc.example.invalid") not in (a,)


def test_rows_written_before_keyed_digests_still_prevent_resends(env):
    from app.platform.notifier import legacy_recipient_key, record_recipient
    clock = Clock()
    alert = enqueue(ref=two_member_group())
    oid = row(alert).id
    record_recipient(oid, legacy_recipient_key(oid, "officer11@awoc.example.invalid"), "DELIVERED")
    fake = FakeProvider()
    worker(fake, clock).run_once()
    assert [m.addresses for m in fake.sent] == [("officer12@awoc.example.invalid",)]


def test_production_requires_a_recipient_key():
    from dataclasses import replace
    from app.platform.settings import problems, settings
    found = problems(replace(settings, app_env="production", notify_recipient_key=""))
    assert any("NOTIFY_RECIPIENT_KEY" in p for p in found)


def test_delivery_operations_are_refused_to_case_roles(env):
    for h in (headers("SCRUTINY_COMMITTEE"), {**headers("RO_OFFICER"), "X-Demo-Region": "Southern"}):
        assert env.get("/api/notifications/health", headers=h).status_code == 403
        assert env.get("/api/notifications/outbox", headers=h).status_code == 403
