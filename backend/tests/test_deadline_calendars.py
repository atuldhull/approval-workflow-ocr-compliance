from datetime import date

import pytest

from app.deadlines.calendars import load_calendar
from app.deadlines.models import CalendarHoliday, CalendarVersion
from contracts.errors import ValidationFailed


class ScalarResult:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


class CalendarSession:
    def __init__(self, record=None, holidays=()):
        self.record = record
        self.holidays = list(holidays)

    def get(self, model, calendar_id):
        assert model is CalendarVersion
        assert calendar_id == "TEST@v1"
        return self.record

    def scalars(self, statement):
        assert statement.column_descriptions[0]["name"] == "holiday_date"
        return ScalarResult(self.holidays)


def test_load_calendar_pins_weekdays_and_holidays_to_exact_version():
    session = CalendarSession(
        CalendarVersion(
            calendar_id="TEST@v1",
            working_weekdays=[0, 1, 2, 3, 4],
            source_status="verified",
            source_ref="approved schedule 2026",
        ),
        holidays=[date(2026, 7, 3)],
    )

    calendar = load_calendar(session, "TEST@v1")

    assert calendar.calendar_id == "TEST@v1"
    assert calendar.working_weekdays == frozenset({0, 1, 2, 3, 4})
    assert calendar.holidays == frozenset({date(2026, 7, 3)})
    assert calendar.add_working_days(date(2026, 7, 2), 1, count_anchor_day=False) == date(2026, 7, 6)


def test_load_calendar_fails_closed_for_unknown_version():
    with pytest.raises(ValidationFailed, match="not configured"):
        load_calendar(CalendarSession(), "TEST@v1")
