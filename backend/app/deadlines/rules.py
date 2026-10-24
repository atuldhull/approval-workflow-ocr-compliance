"""Deadline rules from deadlines.yaml, and the date arithmetic behind them."""
import calendar
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

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
    extra: dict[str, Any] = field(default_factory=dict)  # reminders, escalation, applies_when ...


def parse_rule(raw: dict[str, Any]) -> DeadlineRule:
    rid = raw.get("id")
    if not rid:
        raise ValidationFailed("deadline rule without id")
    try:
        kind = ClockKind(raw["clock_kind"])
        owner = ClockOwner(raw["clock_owner"])
    except (KeyError, ValueError):
        raise ValidationFailed(f"{rid}: clock_kind and clock_owner are required and must be known values") from None
    source = raw.get("source") or {}
    if source.get("status") not in SOURCE_STATUSES:
        raise ValidationFailed(f"{rid}: source.status must be one of {sorted(SOURCE_STATUSES)}")

    duration = None
    if "duration" in raw:
        d = raw["duration"]
        if d.get("unit") not in UNITS or not isinstance(d.get("value"), int) or d["value"] <= 0:
            raise ValidationFailed(f"{rid}: duration needs a positive integer value and a unit in {sorted(UNITS)}")
        duration = Duration(d["value"], d["unit"], d.get("month_end", "clamp"))
    if (duration is None) == (raw.get("computed") is None):
        raise ValidationFailed(f"{rid}: give exactly one of duration or computed")

    known = {"id", "clock_kind", "clock_owner", "source", "anchor", "duration", "computed"}
    return DeadlineRule(
        id=rid, clock_kind=kind, clock_owner=owner, source_status=source["status"], clause=source.get("clause"),
        anchor=raw.get("anchor"), duration=duration, computed=raw.get("computed"),
        extra={k: v for k, v in raw.items() if k not in known},
    )


class RuleParser:
    def parse(self, raw: dict[str, Any]) -> dict[str, Any]:
        rules: dict[str, DeadlineRule] = {}
        for item in raw.get("rules", []) or []:
            rule = parse_rule(item)
            if rule.id in rules:
                raise ValidationFailed(f"duplicate deadline rule {rule.id}")
            rules[rule.id] = rule
        return rules


def add_months(d: date, months: int) -> date:
    """Calendar months with the day clamped to the month end: 31 Aug + 6 months -> 28/29 Feb."""
    total = d.month - 1 + months
    year, month = d.year + total // 12, total % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def due_date(anchor_at: datetime, duration: Duration) -> date:
    """Legal dates are Indian calendar dates, so the anchor is read in IST."""
    start = anchor_at.astimezone(IST).date()
    if duration.unit == "calendar_days":
        return start + timedelta(days=duration.value)
    if duration.unit == "months":
        return add_months(start, duration.value)
    raise ValidationFailed("working_days needs a holiday calendar, which is not configured yet")


def end_of_day(d: date) -> datetime:
    return datetime.combine(d, time(23, 59, 59), IST)
