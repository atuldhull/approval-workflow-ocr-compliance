"""PostgreSQL integration checks for calendar constraints and immutability."""
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.deadlines.calendars import WorkingCalendar, register_calendar_version
from app.deadlines.models import CalendarHoliday, CalendarVersion


@pytest.fixture
def pg_session(database):
    engine = create_engine(database)
    with Session(engine) as session:
        yield session
        session.rollback()
    engine.dispose()


def calendar_id(version: str) -> str:
    return f"TEST@{version}-{uuid4().hex}"


def insert_calendar_row(
    session: Session, key: str, *, source_status="demo_assumption", source_ref=None, is_finalized=True
):
    session.add(
        CalendarVersion(
            calendar_id=key,
            working_weekdays=[0, 1, 2, 3, 4],
            source_status=source_status,
            source_ref=source_ref,
            is_finalized=is_finalized,
        )
    )


@pytest.mark.parametrize("key", ["TEST@v1@extra", "@v1", "TEST@", "TEST@ \t\n"])
def test_database_rejects_invalid_calendar_ids(pg_session, key):
    insert_calendar_row(pg_session, key)

    with pytest.raises(DBAPIError):
        pg_session.flush()
    pg_session.rollback()


@pytest.mark.parametrize("source_ref", [None, "", "  ", " \t\n\v\f\r "])
def test_database_rejects_missing_or_blank_verified_source_reference(pg_session, source_ref):
    insert_calendar_row(pg_session, calendar_id("verified"), source_status="verified", source_ref=source_ref)

    with pytest.raises(DBAPIError):
        pg_session.flush()
    pg_session.rollback()


def test_database_accepts_valid_verified_and_demo_metadata(pg_session):
    verified = WorkingCalendar(calendar_id("verified"), frozenset({0, 1, 2, 3, 4}), "verified", "official circular 2026")
    assumed = WorkingCalendar(calendar_id("demo"), frozenset({0, 1, 2, 3, 4}), "demo_assumption", None)

    register_calendar_version(pg_session, verified)
    register_calendar_version(pg_session, assumed)
    pg_session.commit()

    assert pg_session.get(CalendarVersion, verified.calendar_id).is_finalized is True
    assert pg_session.get(CalendarVersion, assumed.calendar_id).source_ref is None


def test_database_does_not_allow_an_unfinalized_version_to_commit(pg_session):
    insert_calendar_row(pg_session, calendar_id("unfinalized"), is_finalized=False)

    with pytest.raises(DBAPIError):
        pg_session.commit()
    pg_session.rollback()


def test_failed_registration_rolls_back_parent_and_holidays(pg_session):
    key = calendar_id("rollback")
    calendar = WorkingCalendar(
        key,
        frozenset({0, 1, 2, 3, 4}),
        "verified",
        "official circular 2026",
        frozenset({date(2026, 7, 3)}),
    )

    def fail_before_holiday_flush(session, flush_context, instances):
        if any(isinstance(instance, CalendarHoliday) for instance in session.new):
            raise RuntimeError("simulated failure while inserting holidays")

    event.listen(pg_session, "before_flush", fail_before_holiday_flush)
    try:
        with pytest.raises(RuntimeError, match="simulated failure"):
            register_calendar_version(pg_session, calendar)
    finally:
        event.remove(pg_session, "before_flush", fail_before_holiday_flush)
    pg_session.rollback()

    assert pg_session.get(CalendarVersion, key) is None
    holiday_count = pg_session.scalar(
        select(func.count()).select_from(CalendarHoliday).where(CalendarHoliday.calendar_id == key)
    )
    assert holiday_count == 0


def test_database_rejects_calendar_and_holiday_changes_but_allows_a_new_version(pg_session):
    old_id = calendar_id("r1")
    original_holiday = date(2026, 7, 3)
    original = WorkingCalendar(
        old_id,
        frozenset({0, 1, 2, 3, 4}),
        "verified",
        "official circular 2026",
        frozenset({original_holiday}),
    )
    register_calendar_version(pg_session, original)
    pg_session.commit()

    version = pg_session.get(CalendarVersion, old_id)
    version.working_weekdays = [0, 1, 2, 3, 4, 5]
    with pytest.raises(DBAPIError):
        pg_session.flush()
    pg_session.rollback()

    holiday = pg_session.get(CalendarHoliday, (old_id, original_holiday))
    holiday.label = "changed"
    with pytest.raises(DBAPIError):
        pg_session.flush()
    pg_session.rollback()

    pg_session.add(CalendarHoliday(calendar_id=old_id, holiday_date=date(2026, 7, 6)))
    with pytest.raises(DBAPIError):
        pg_session.flush()
    pg_session.rollback()

    pg_session.delete(pg_session.get(CalendarHoliday, (old_id, original_holiday)))
    with pytest.raises(DBAPIError):
        pg_session.flush()
    pg_session.rollback()

    pg_session.delete(pg_session.get(CalendarVersion, old_id))
    with pytest.raises(DBAPIError):
        pg_session.flush()
    pg_session.rollback()

    new_id = calendar_id("r2")
    revised = WorkingCalendar(
        new_id,
        frozenset({0, 1, 2, 3, 4, 5}),
        "verified",
        "revised official circular 2026",
        frozenset({date(2026, 7, 3), date(2026, 7, 6)}),
    )
    register_calendar_version(pg_session, revised)
    pg_session.commit()

    assert pg_session.get(CalendarVersion, old_id).working_weekdays == [0, 1, 2, 3, 4]
    assert pg_session.get(CalendarVersion, new_id).working_weekdays == [0, 1, 2, 3, 4, 5]
