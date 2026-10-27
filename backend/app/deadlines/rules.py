"""Deadline rules from deadlines.yaml, and the date arithmetic behind them."""
import calendar
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.deadlines.calendars import WorkingCalendar, validate_calendar_id
from app.deadlines.escalation import check_rule_ladders, parse_alert_config
from contracts.enums import ClockKind, ClockOwner
from contracts.errors import ValidationFailed

IST = ZoneInfo("Asia/Kolkata")
SOURCE_STATUSES = {"verified", "verified_letter_text", "demo_assumption"}
UNITS = {"calendar_days", "working_days", "months"}


@dataclass(frozen=True)
class Duration:
    value: int
    unit: str
    month_end: str = "clamp"


@dataclass(frozen=True)
class DeadlineRule:
    id: str
    clock_kind: ClockKind
    clock_owner: ClockOwner
    source_status: str
    clause: str | None
    anchor: str | None
    duration: Duration | None  # None for computed rules (e.g. lease stop year)
    computed: str | None
    calendar_id: str | None
    count_anchor_day: bool | None
    extra: dict[str, Any] = field(default_factory=dict)  # reminders, escalation, applies_when ...


def parse_rule(raw: dict[str, Any]) -> DeadlineRule:
    if not isinstance(raw, dict):
        raise ValidationFailed("deadline rule must be an object")
    rid = raw.get("id")
    if not isinstance(rid, str) or not rid.strip():
        raise ValidationFailed("deadline rule without id")
    try:
        kind = ClockKind(raw["clock_kind"])
        owner = ClockOwner(raw["clock_owner"])
    except (KeyError, TypeError, ValueError):
        raise ValidationFailed(f"{rid}: clock_kind and clock_owner are required and must be known values") from None
    source = raw.get("source") or {}
    if not isinstance(source, dict):
        raise ValidationFailed(f"{rid}: source must be an object")
    if not isinstance(source.get("status"), str) or source["status"] not in SOURCE_STATUSES:
        raise ValidationFailed(f"{rid}: source.status must be one of {sorted(SOURCE_STATUSES)}")

    duration = None
    if "duration" in raw:
        d = raw["duration"]
        if not isinstance(d, dict):
            raise ValidationFailed(f"{rid}: duration must be an object")
        if (not isinstance(d.get("unit"), str) or d["unit"] not in UNITS
                or type(d.get("value")) is not int or d["value"] <= 0):
            raise ValidationFailed(f"{rid}: duration needs a positive integer value and a unit in {sorted(UNITS)}")
        month_end = d.get("month_end", "clamp")
        if month_end != "clamp":
            raise ValidationFailed(f"{rid}: month_end must be 'clamp'; other month-end policies are unsupported")
        if "month_end" in d and d["unit"] != "months":
            raise ValidationFailed(f"{rid}: month_end applies only to month durations")
        duration = Duration(d["value"], d["unit"], month_end)
    computed = raw.get("computed")
    if computed is not None and (not isinstance(computed, str) or not computed.strip()):
        raise ValidationFailed(f"{rid}: computed must be a non-empty rule name")
    if (duration is None) == (computed is None):
        raise ValidationFailed(f"{rid}: give exactly one of duration or computed")

    calendar_id = raw.get("calendar_id")
    count_anchor_day = raw.get("count_anchor_day")
    if duration is not None and duration.unit == "working_days":
        calendar_id = validate_calendar_id(calendar_id, context=rid)
        if type(count_anchor_day) is not bool:
            raise ValidationFailed(f"{rid}: working_days requires count_anchor_day to be true or false")
    elif calendar_id is not None or count_anchor_day is not None:
        raise ValidationFailed(f"{rid}: calendar_id and count_anchor_day apply only to working_days")

    known = {"id", "clock_kind", "clock_owner", "source", "anchor", "duration", "computed",
             "calendar_id", "count_anchor_day"}
    return DeadlineRule(
        id=rid, clock_kind=kind, clock_owner=owner, source_status=source["status"], clause=source.get("clause"),
        anchor=raw.get("anchor"), duration=duration, computed=computed,
        calendar_id=calendar_id, count_anchor_day=count_anchor_day,
        extra={k: v for k, v in raw.items() if k not in known},
    )


class DeadlineRules(dict):
    """Rules by id, plus the ruleset-wide alert ladder and academic-year boundary (both may be absent)."""

    def __init__(self, rules: dict[str, DeadlineRule], alerts=None, academic_year: "AcademicYearStart | None" = None,
                 academic_year_source: str | None = None):
        super().__init__(rules)
        self.alerts = alerts
        self.academic_year = academic_year
        self.academic_year_source = academic_year_source


def parse_academic_year(raw: object) -> tuple["AcademicYearStart | None", str | None]:
    if raw is None:
        return None, None
    if not isinstance(raw, dict):
        raise ValidationFailed("academic_year must be an object")
    source = raw.get("source") or {}
    if not isinstance(source, dict) or source.get("status") not in SOURCE_STATUSES:
        raise ValidationFailed(f"academic_year.source.status must be one of {sorted(SOURCE_STATUSES)}")
    return AcademicYearStart.parse(raw.get("starts")), source["status"]


class RuleParser:
    def parse(self, raw: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise ValidationFailed("deadline rules document must be an object")
        items = raw.get("rules", []) or []
        if not isinstance(items, list):
            raise ValidationFailed("deadline rules must be a list")
        rules: dict[str, DeadlineRule] = {}
        for item in items:
            rule = parse_rule(item)
            if rule.id in rules:
                raise ValidationFailed(f"duplicate deadline rule {rule.id}")
            rules[rule.id] = rule
        alerts = parse_alert_config(raw.get("alerts"))
        check_rule_ladders(rules, alerts)
        academic_year, ay_source = parse_academic_year(raw.get("academic_year"))
        return DeadlineRules(rules, alerts, academic_year, ay_source)


def add_months(d: date, months: int) -> date:
    """Calendar months with the day clamped to the month end: 31 Aug + 6 months -> 28/29 Feb."""
    if not isinstance(d, date) or isinstance(d, datetime):
        raise ValidationFailed("month arithmetic needs a calendar date")
    if type(months) is not int or months < 1:
        raise ValidationFailed("month duration must be a positive integer")
    total = d.month - 1 + months
    year, month = d.year + total // 12, total % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def due_date(anchor_at: datetime, duration: Duration, *, calendar: WorkingCalendar | None = None,
             count_anchor_day: bool | None = None) -> date:
    """Legal dates are Indian calendar dates, so the anchor is read in IST."""
    if not isinstance(anchor_at, datetime) or anchor_at.tzinfo is None or anchor_at.utcoffset() is None:
        raise ValidationFailed("deadline anchor must be a timezone-aware datetime")
    if not isinstance(duration, Duration) or type(duration.value) is not int or duration.value <= 0:
        raise ValidationFailed("deadline duration must have a positive integer value")
    if not isinstance(duration.unit, str) or duration.unit not in UNITS:
        raise ValidationFailed(f"unsupported duration unit {duration.unit}")
    start = anchor_at.astimezone(IST).date()
    if duration.unit == "calendar_days":
        return start + timedelta(days=duration.value)
    if duration.unit == "months":
        if duration.month_end != "clamp":
            raise ValidationFailed(f"unsupported month-end policy {duration.month_end}")
        return add_months(start, duration.value)
    if duration.unit == "working_days":
        if calendar is None:
            raise ValidationFailed("working_days needs an explicit, versioned holiday calendar")
        if count_anchor_day is None:
            raise ValidationFailed("working_days needs an explicit anchor-day counting rule")
        return calendar.add_working_days(start, duration.value, count_anchor_day=count_anchor_day)
    raise ValidationFailed(f"unsupported duration unit {duration.unit}")


def end_of_day(d: date) -> datetime:
    if not isinstance(d, date) or isinstance(d, datetime):
        raise ValidationFailed("deadline due date must be a calendar date")
    return datetime.combine(d, time.max, IST)


# ---- lease stop academic year (APH cl. 2.1(e), 6.17) ----

@dataclass(frozen=True)
class AcademicYearStart:
    """The calendar day an academic year begins, e.g. 1 July -> AY 2031-32 runs 1 Jul 2031 to 30 Jun 2032."""
    month: int
    day: int

    def __post_init__(self) -> None:
        if type(self.month) is not int or type(self.day) is not int or not 1 <= self.month <= 12:
            raise ValidationFailed("academic year start needs an integer month and day")
        if (self.month, self.day) == (2, 29) or not 1 <= self.day <= calendar.monthrange(2001, self.month)[1]:
            raise ValidationFailed("academic year start must be a day that exists every year")

    @classmethod
    def parse(cls, value: object) -> "AcademicYearStart":
        if not isinstance(value, str) or len(value) != 5 or value[2] != "-" or not (value[:2] + value[3:]).isdigit():
            raise ValidationFailed("academic year start must look like MM-DD, e.g. 07-01")
        return cls(int(value[:2]), int(value[3:]))

    def year_of(self, d: date) -> int:
        """The starting calendar year of the academic year containing d."""
        return d.year if (d.month, d.day) >= (self.month, self.day) else d.year - 1


def academic_year_label(start_year: int) -> str:
    return f"{start_year}-{(start_year + 1) % 100:02d}"


def add_years(d: date, years: int) -> date:
    """Anniversary of d; a 29 February start rolls to 1 March in a common year."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return date(d.year + years, 3, 1)


def covers(start: date, years: int, lease_end: date) -> bool:
    """Whether a lease ending on lease_end (inclusive) still has `years` full years left on `start`."""
    return add_years(start, years) - timedelta(days=1) <= lease_end


def lease_eoa_stop_year(lease_end_date: date, max_course_duration_years: int,
                        ay_start: AcademicYearStart) -> str:
    """First academic year for which Extension of Approval is blocked by the land lease.

    APH 2.1(e) / 6.17: no EoA from the academic year in which the remaining live lease equals the longest course
    duration, unless the lease is extended by 30 years (the caller then passes the extended end date).
    The day on which the remaining lease equals the course duration is the last day from which a full course of
    that length still fits in the lease; the academic year containing that day is the first one blocked.
    """
    if not isinstance(lease_end_date, date) or isinstance(lease_end_date, datetime):
        raise ValidationFailed("lease_end_date must be a calendar date")
    if type(max_course_duration_years) is not int or not 1 <= max_course_duration_years <= 10:
        raise ValidationFailed("max_course_duration_years must be a whole number of years from 1 to 10")
    if not isinstance(ay_start, AcademicYearStart):
        raise ValidationFailed("ay_start must be an AcademicYearStart")
    years = max_course_duration_years
    # first guess, then settle on the exact last day from which `years` still fit (leap days move it by one)
    day = add_years(lease_end_date + timedelta(days=1), -years)
    while not covers(day, years, lease_end_date):
        day -= timedelta(days=1)
    while covers(day + timedelta(days=1), years, lease_end_date):
        day += timedelta(days=1)
    return academic_year_label(ay_start.year_of(day))


def lease_meets_minimum(lease_start_date: date, lease_end_date: date, min_years: int = 30) -> bool:
    """APH 2.1(e): the lease must run for at least `min_years` years (end date inclusive)."""
    if lease_end_date < lease_start_date:
        raise ValidationFailed("lease ends before it starts")
    return covers(lease_start_date, min_years, lease_end_date)
