from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.deadlines.rules import end_of_day
from app.deadlines.service import DeadlineEngine
from contracts.enums import ClockKind, DeadlineStatus
from contracts.errors import Conflict, ValidationFailed
from contracts.ports import ClockPort
from contracts.types import SubjectRef


class FrozenClock:
    def __init__(self, at: datetime):
        self.at = at

    def now(self) -> datetime:
        return self.at


def deadline(*, kind=ClockKind.INTERNAL, status=DeadlineStatus.RUNNING):
    return SimpleNamespace(
        clock_kind=kind,
        status=status,
        paused_at=None,
        due_at=end_of_day(date(2026, 7, 10)),
        due_date=date(2026, 7, 10),
        due_version=1,
    )


def bind_deadline(monkeypatch, engine, row, clock):
    monkeypatch.setattr(engine, "_require_live", lambda *_: row)
    monkeypatch.setattr("app.deadlines.service.port", lambda port_type: clock if port_type is ClockPort else None)


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
