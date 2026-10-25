"""Deadline rules from deadlines.yaml, and the date arithmetic behind them."""
import calendar
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.deadlines.calendars import WorkingCalendar, validate_calendar_id
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
        return rules


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
