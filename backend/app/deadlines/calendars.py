"""Explicit, versioned working-day calendars for deadline calculations."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deadlines.models import CalendarHoliday, CalendarVersion
from contracts.errors import Conflict, ValidationFailed

_TRIM_CHARS = " \t\n\v\f\r"


def validate_calendar_id(calendar_id: object, *, context: str | None = None) -> str:
    """Validate the version key using the same whitespace and separator rules as PostgreSQL."""
    prefix = f"{context}: " if context else ""
    if not isinstance(calendar_id, str) or not calendar_id.strip(_TRIM_CHARS):
        raise ValidationFailed(f"{prefix}working_days requires an explicit calendar_id version")
    parts = calendar_id.split("@")
    if len(parts) != 2 or not all(part.strip(_TRIM_CHARS) for part in parts):
        raise ValidationFailed(f"{prefix}calendar_id must include its version as NAME@VERSION")
    return calendar_id


def validate_calendar_metadata(calendar_id: object, source_status: object, source_ref: object) -> None:
    validate_calendar_id(calendar_id)
    if not isinstance(source_status, str) or source_status not in {"verified", "demo_assumption"}:
        raise ValidationFailed("calendar source_status must be verified or demo_assumption")
    if source_status == "verified" and not (
        isinstance(source_ref, str) and source_ref.strip(_TRIM_CHARS)
    ):
        raise ValidationFailed("verified calendars need a source_ref")


@dataclass(frozen=True)
class WorkingCalendar:
    """A single finalized calendar version.

    Weekdays use ``date.weekday()`` numbering (Monday=0, Sunday=6). No weekend or
    holiday assumptions are supplied by this class; callers must provide them.
    """

    calendar_id: str
    working_weekdays: frozenset[int]
    source_status: str
    source_ref: str | None
    holidays: frozenset[date] = frozenset()

    def __post_init__(self) -> None:
        validate_calendar_metadata(self.calendar_id, self.source_status, self.source_ref)

        weekdays = frozenset(self.working_weekdays)
        if not weekdays or any(type(day) is not int or day not in range(7) for day in weekdays):
            raise ValidationFailed("working_weekdays must contain one or more weekday numbers from 0 to 6")
        object.__setattr__(self, "working_weekdays", weekdays)

        holidays = frozenset(self.holidays)
        if any(type(day) is not date for day in holidays):
            raise ValidationFailed("calendar holidays must be dates")
        object.__setattr__(self, "holidays", holidays)

    def is_working_day(self, day: date) -> bool:
        return day.weekday() in self.working_weekdays and day not in self.holidays

    def add_working_days(self, start: date, count: int, *, count_anchor_day: bool) -> date:
        """Return the date reached after ``count`` configured working days.

        Whether the anchor itself counts is required by the caller because the
        governing rule may use an inclusive or exclusive count.
        """
        if not isinstance(start, date) or isinstance(start, datetime):
            raise ValidationFailed("working-day arithmetic needs a calendar date")
        if type(count) is not int or count < 1:
            raise ValidationFailed("working-day duration must be a positive integer")
        if type(count_anchor_day) is not bool:
            raise ValidationFailed("count_anchor_day must be explicitly true or false")

        current = start
        remaining = count
        if count_anchor_day and self.is_working_day(current):
            remaining -= 1

        while remaining:
            current += timedelta(days=1)
            if self.is_working_day(current):
                remaining -= 1
        return current


def load_calendar(session: Session, calendar_id: str) -> WorkingCalendar:
    """Load the exact finalized calendar version referenced by a deadline rule."""
    record = session.get(CalendarVersion, calendar_id)
    if record is None:
        raise ValidationFailed(f"working-day calendar {calendar_id} is not configured")
    holidays = session.scalars(
        select(CalendarHoliday.holiday_date).where(CalendarHoliday.calendar_id == calendar_id)
    ).all()
    return WorkingCalendar(
        calendar_id=record.calendar_id,
        working_weekdays=frozenset(record.working_weekdays),
        source_status=record.source_status,
        source_ref=record.source_ref,
        holidays=frozenset(holidays),
    )


def register_calendar_version(session: Session, calendar: WorkingCalendar) -> CalendarVersion:
    """Insert a new version and its holidays, then finalize it in the same transaction.

    Existing version IDs cannot be updated. Revised source data must use a new
    calendar_id so deadlines keep resolving to their original calendar.
    """
    if session.get(CalendarVersion, calendar.calendar_id) is not None:
        raise Conflict(f"calendar version {calendar.calendar_id} already exists; use a new version ID")

    record = CalendarVersion(
        calendar_id=calendar.calendar_id,
        working_weekdays=sorted(calendar.working_weekdays),
        source_status=calendar.source_status,
        source_ref=calendar.source_ref,
        is_finalized=False,
    )
    session.add(record)
    session.flush()

    session.add_all(
        CalendarHoliday(calendar_id=calendar.calendar_id, holiday_date=holiday)
        for holiday in sorted(calendar.holidays)
    )
    session.flush()

    record.is_finalized = True
    session.flush()
    return record
