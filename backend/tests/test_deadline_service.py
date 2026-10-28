from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.deadlines.rules import end_of_day
from app.deadlines.service import DeadlineEngine
from contracts.enums import ClockKind, DeadlineStatus
from contracts.errors import Conflict, ValidationFailed
from contracts.fakes import FakeLedger
from contracts.ports import ClockPort, LedgerPort
from contracts.types import SubjectRef


class FrozenClock:
    def __init__(self, at: datetime):
        self.at = at

    def now(self) -> datetime:
        return self.at


def deadline(*, kind=ClockKind.INTERNAL, status=DeadlineStatus.RUNNING):
    return SimpleNamespace(
        id=uuid4(), subject_type="application", subject_id=uuid4(), rule_id="AICTE_PROCESSING",
        ruleset="aph-2024-27", revision="r1", clock_owner="AICTE",
        clock_kind=kind,
        status=status,
        paused_at=None,
        due_at=end_of_day(date(2026, 7, 10)),
        due_date=date(2026, 7, 10),
        due_version=1,
    )


def bind_deadline(monkeypatch, engine, row, clock, ledger=None):
    ledger = ledger or FakeLedger()
    monkeypatch.setattr(engine, "_require_live", lambda *_: row)
    monkeypatch.setattr("app.deadlines.service.port",
                        lambda port_type: clock if port_type is ClockPort else ledger if port_type is LedgerPort else None)
    return ledger


def test_legal_deadlines_cannot_be_paused(monkeypatch):
    engine = DeadlineEngine()
    row = deadline(kind=ClockKind.LEGAL)
    bind_deadline(monkeypatch, engine, row, FrozenClock(datetime(2026, 7, 1, tzinfo=timezone.utc)))

    with pytest.raises(Conflict, match="legal clocks are never paused"):
        engine.pause_internal(None, SubjectRef("application", uuid4()), "APPEAL_7D")
    assert row.status == DeadlineStatus.RUNNING
    assert row.paused_at is None


def test_internal_deadline_pause_and_resume_adds_held_time(monkeypatch):
    engine = DeadlineEngine()
    row = deadline()
    held_from = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)
    resumed_at = held_from + timedelta(days=2)
    clock = FrozenClock(held_from)
    bind_deadline(monkeypatch, engine, row, clock)
    subject = SubjectRef("application", uuid4())

    engine.pause_internal(None, subject, "AICTE_PROCESSING")
    assert row.status == DeadlineStatus.PAUSED
    assert row.paused_at == held_from

    clock.at = resumed_at
    engine.resume_internal(None, subject, "AICTE_PROCESSING")
    assert row.status == DeadlineStatus.RUNNING
    assert row.paused_at is None
    assert row.due_at == end_of_day(date(2026, 7, 12))
    assert row.due_date == date(2026, 7, 12)
    assert row.due_version == 2


def test_pausing_an_already_paused_internal_deadline_is_idempotent(monkeypatch):
    engine = DeadlineEngine()
    initial_pause = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)
    row = deadline(status=DeadlineStatus.PAUSED)
    row.paused_at = initial_pause
    clock = FrozenClock(initial_pause + timedelta(days=1))
    bind_deadline(monkeypatch, engine, row, clock)

    engine.pause_internal(None, SubjectRef("application", uuid4()), "AICTE_PROCESSING")
    assert row.paused_at == initial_pause


def test_resume_rejects_missing_pause_timestamp_without_mutating(monkeypatch):
    engine = DeadlineEngine()
    row = deadline(status=DeadlineStatus.PAUSED)
    bind_deadline(monkeypatch, engine, row, FrozenClock(datetime(2026, 7, 2, tzinfo=timezone.utc)))

    with pytest.raises(Conflict, match="missing paused_at"):
        engine.resume_internal(None, SubjectRef("application", uuid4()), "AICTE_PROCESSING")
    assert row.status == DeadlineStatus.PAUSED
    assert row.due_version == 1


def test_resume_rejects_clock_before_pause_without_mutating(monkeypatch):
    engine = DeadlineEngine()
    row = deadline(status=DeadlineStatus.PAUSED)
    row.paused_at = datetime(2026, 7, 2, tzinfo=timezone.utc)
    bind_deadline(monkeypatch, engine, row, FrozenClock(datetime(2026, 7, 1, tzinfo=timezone.utc)))

    with pytest.raises(Conflict, match="before it was paused"):
        engine.resume_internal(None, SubjectRef("application", uuid4()), "AICTE_PROCESSING")
    assert row.status == DeadlineStatus.PAUSED
    assert row.due_version == 1


def test_clock_must_return_timezone_aware_time(monkeypatch):
    engine = DeadlineEngine()
    row = deadline()
    bind_deadline(monkeypatch, engine, row, FrozenClock(datetime(2026, 7, 1)))

    with pytest.raises(ValidationFailed, match="timezone-aware"):
        engine.pause_internal(None, SubjectRef("application", uuid4()), "AICTE_PROCESSING")
    assert row.status == DeadlineStatus.RUNNING
    assert row.paused_at is None


# ---- lifecycle events ----

def test_pause_and_resume_record_the_held_time_and_new_due_date(monkeypatch):
    engine = DeadlineEngine()
    row = deadline()
    held_from = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)
    clock = FrozenClock(held_from)
    ledger = bind_deadline(monkeypatch, engine, row, clock)
    subject = SubjectRef("application", row.subject_id)

    engine.pause_internal(None, subject, "AICTE_PROCESSING")
    engine.pause_internal(None, subject, "AICTE_PROCESSING")   # already paused: no second event
    clock.at = held_from + timedelta(days=2)
    engine.resume_internal(None, subject, "AICTE_PROCESSING")
    engine.resume_internal(None, subject, "AICTE_PROCESSING")  # already running: no event

    assert [e.event_type for e in ledger.events] == ["dl.deadline_paused", "dl.deadline_resumed"]
    paused, resumed = (e.payload for e in ledger.events)
    assert (paused["from_status"], paused["due_date"], paused["due_version"]) == ("RUNNING", "2026-07-10", 1)
    assert (resumed["due_date"], resumed["due_version"], resumed["held_seconds"]) == ("2026-07-12", 2, 2 * 86400)
    assert all(e.aggregate_type == "deadline" and e.aggregate_id == row.id for e in ledger.events)


@pytest.mark.parametrize("status, now, late", [
    (DeadlineStatus.RUNNING, datetime(2026, 7, 1, tzinfo=timezone.utc), False),
    (DeadlineStatus.RUNNING, datetime(2026, 7, 20, tzinfo=timezone.utc), True),
    (DeadlineStatus.BREACHED, datetime(2026, 7, 20, tzinfo=timezone.utc), True),
    (DeadlineStatus.PAUSED, datetime(2026, 7, 1, tzinfo=timezone.utc), False),
])
def test_close_records_outcome_from_status_and_lateness(monkeypatch, status, now, late):
    engine = DeadlineEngine()
    row = deadline(status=status)
    ledger = bind_deadline(monkeypatch, engine, row, FrozenClock(now))

    engine.close(None, SubjectRef("application", row.subject_id), "AICTE_PROCESSING", DeadlineStatus.MET)

    assert row.status == DeadlineStatus.MET and row.next_fire_at is None
    [e] = ledger.events
    assert e.event_type == "dl.deadline_closed"
    assert (e.payload["outcome"], e.payload["from_status"], e.payload["late"]) == ("MET", status, late)


def test_a_breached_internal_clock_can_be_paused(monkeypatch):
    engine = DeadlineEngine()
    row = deadline(status=DeadlineStatus.BREACHED)
    ledger = bind_deadline(monkeypatch, engine, row, FrozenClock(datetime(2026, 7, 20, tzinfo=timezone.utc)))

    engine.pause_internal(None, SubjectRef("application", row.subject_id), "AICTE_PROCESSING")

    assert row.status == DeadlineStatus.PAUSED
    assert ledger.events[0].payload["from_status"] == "BREACHED"


def test_breach_is_recorded_once(monkeypatch):
    engine = DeadlineEngine()
    row = deadline()
    ledger = bind_deadline(monkeypatch, engine, row, FrozenClock(datetime(2026, 7, 20, tzinfo=timezone.utc)))

    assert engine.breach(None, row) is True
    assert engine.breach(None, row) is False
    assert row.status == DeadlineStatus.BREACHED
    [e] = ledger.events
    assert e.event_type == "dl.deadline_breached"
    assert (e.payload["clock_kind"], e.payload["clock_owner"], e.payload["due_version"]) == ("INTERNAL", "AICTE", 1)
