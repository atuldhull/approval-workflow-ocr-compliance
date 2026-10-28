from datetime import date, datetime, time, timezone
from pathlib import Path

import pytest
import yaml

from app.deadlines.calendars import WorkingCalendar, validate_calendar_id
from app.deadlines.rules import Duration, RuleParser, add_months, due_date
from contracts.enums import ClockKind
from contracts.errors import ValidationFailed

R1 = Path(__file__).resolve().parents[2] / "rulesets" / "aph-2024-27" / "r1" / "deadlines.yaml"


def test_month_end_is_clamped():
    assert add_months(date(2026, 8, 31), 6) == date(2027, 2, 28)
    assert add_months(date(2027, 8, 31), 6) == date(2028, 2, 29)
    assert add_months(date(2026, 1, 15), 6) == date(2026, 7, 15)
    assert add_months(date(2026, 11, 30), 3) == date(2027, 2, 28)


def test_month_arithmetic_rejects_unsupported_inputs():
    with pytest.raises(ValidationFailed, match="positive integer"):
        add_months(date(2026, 1, 1), 0)
    with pytest.raises(ValidationFailed, match="positive integer"):
        add_months(date(2026, 1, 1), True)
    with pytest.raises(ValidationFailed, match="calendar date"):
        add_months(datetime(2026, 1, 1), 1)


def test_end_of_day_includes_the_whole_local_day():
    from app.deadlines.rules import end_of_day

    due_at = end_of_day(date(2026, 7, 1))
    assert due_at.time() == time.max
    assert due_at.utcoffset().total_seconds() == 5.5 * 60 * 60


def test_due_dates_use_the_indian_calendar_date():
    # 20:00 UTC on 1 July is already 2 July in India
    anchor = datetime(2026, 7, 1, 20, 0, tzinfo=timezone.utc)
    assert due_date(anchor, Duration(7, "calendar_days")) == date(2026, 7, 9)


def test_due_date_requires_aware_anchor_and_valid_duration():
    with pytest.raises(ValidationFailed, match="timezone-aware"):
        due_date(datetime(2026, 7, 1, 12), Duration(1, "calendar_days"))
    with pytest.raises(ValidationFailed, match="positive integer"):
        due_date(datetime(2026, 7, 1, tzinfo=timezone.utc), Duration(0, "calendar_days"))
    with pytest.raises(ValidationFailed, match="unsupported duration unit"):
        due_date(datetime(2026, 7, 1, tzinfo=timezone.utc), Duration(1, "weeks"))
    with pytest.raises(ValidationFailed, match="month-end policy"):
        due_date(datetime(2026, 7, 1, tzinfo=timezone.utc), Duration(1, "months", "roll"))


def test_working_days_need_a_calendar():
    with pytest.raises(ValidationFailed, match="explicit, versioned holiday calendar"):
        due_date(datetime(2026, 7, 1, tzinfo=timezone.utc), Duration(5, "working_days"))


def test_working_days_skip_explicit_nonworking_days_and_holidays():
    calendar = WorkingCalendar(
        calendar_id="TEST@v1",
        working_weekdays=frozenset({0, 1, 2, 3, 4}),
        source_status="demo_assumption",
        source_ref="synthetic unit-test calendar",
        holidays=frozenset({date(2026, 7, 3)}),
    )
    anchor = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)
    assert due_date(anchor, Duration(2, "working_days"), calendar=calendar,
                    count_anchor_day=False) == date(2026, 7, 7)


def test_working_days_starting_on_weekend_or_holiday_count_from_next_workday():
    calendar = WorkingCalendar(
        calendar_id="TEST@v1",
        working_weekdays=frozenset({0, 1, 2, 3, 4}),
        source_status="demo_assumption",
        source_ref="synthetic unit-test calendar",
        holidays=frozenset({date(2026, 7, 6)}),
    )
    assert calendar.add_working_days(date(2026, 7, 4), 1, count_anchor_day=True) == date(2026, 7, 7)
    assert calendar.add_working_days(date(2026, 7, 6), 1, count_anchor_day=True) == date(2026, 7, 7)


def test_working_day_anchor_count_is_explicit():
    calendar = WorkingCalendar("TEST@v1", frozenset({0, 1, 2, 3, 4}),
                               source_status="demo_assumption", source_ref="synthetic unit-test calendar")
    anchor = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)
    assert due_date(anchor, Duration(1, "working_days"), calendar=calendar,
                    count_anchor_day=True) == date(2026, 7, 2)
    assert due_date(anchor, Duration(1, "working_days"), calendar=calendar,
                    count_anchor_day=False) == date(2026, 7, 3)
    with pytest.raises(ValidationFailed, match="anchor-day counting rule"):
        due_date(anchor, Duration(1, "working_days"), calendar=calendar)


def test_working_calendar_requires_explicit_weekdays():
    with pytest.raises(ValidationFailed, match="working_weekdays"):
        WorkingCalendar("TEST@v1", frozenset(), source_status="demo_assumption",
                        source_ref="synthetic unit-test calendar")
    with pytest.raises(ValidationFailed, match="weekday numbers"):
        WorkingCalendar("TEST@v1", frozenset({0, 7}),
                        source_status="demo_assumption", source_ref="synthetic unit-test calendar")
    with pytest.raises(ValidationFailed, match="source_status"):
        WorkingCalendar("TEST@v1", frozenset({0}), source_status="unverified", source_ref=None)
    with pytest.raises(ValidationFailed, match="verified calendars need a source_ref"):
        WorkingCalendar("TEST@v1", frozenset({0}), source_status="verified", source_ref=None)
    with pytest.raises(ValidationFailed, match="NAME@VERSION"):
        WorkingCalendar("TEST@v1@extra", frozenset({0}), source_status="demo_assumption", source_ref=None)


@pytest.mark.parametrize("calendar_id", ["TEST@v1@extra", "@v1", "TEST@", "TEST@ \t\n"])
def test_calendar_id_requires_exactly_one_nonblank_version_separator(calendar_id):
    with pytest.raises(ValidationFailed, match="NAME@VERSION"):
        validate_calendar_id(calendar_id)


@pytest.mark.parametrize("source_ref", [None, "", "  ", " \t\n\v\f\r "])
def test_verified_calendar_requires_nonblank_source_reference(source_ref):
    with pytest.raises(ValidationFailed, match="verified calendars need a source_ref"):
        WorkingCalendar("TEST@v1", frozenset({0}), "verified", source_ref)


def test_calendar_metadata_accepts_verified_reference_and_demo_assumption():
    verified = WorkingCalendar("TEST@v1", frozenset({0, 1}), "verified", "official circular 2026")
    assumed = WorkingCalendar("TEST@v2", frozenset({0, 1}), "demo_assumption", None)

    assert verified.calendar_id == "TEST@v1"
    assert verified.source_ref == "official circular 2026"
    assert assumed.source_status == "demo_assumption"


def test_r1_rules_parse():
    rules = RuleParser().parse(yaml.safe_load(R1.read_text(encoding="utf-8")))
    assert {"AICTE_PROCESSING", "APPEAL_7D", "DEPOSIT_15D", "EOA_DEFICIENCY_6M", "LEASE_EOA_STOP"} <= rules.keys()
    assert rules["AICTE_PROCESSING"].clock_kind == ClockKind.INTERNAL
    assert rules["APPEAL_7D"].clock_kind == ClockKind.LEGAL
    assert rules["EOA_DEFICIENCY_6M"].duration == Duration(6, "months", "clamp")
    assert rules["LEASE_EOA_STOP"].duration is None and rules["LEASE_EOA_STOP"].computed


def rule(**overrides):
    base = {"id": "X", "clock_kind": "LEGAL", "clock_owner": "INSTITUTION",
            "source": {"status": "verified"}, "duration": {"value": 7, "unit": "calendar_days"}}
    return {**base, **overrides}


@pytest.mark.parametrize("bad, message", [
    (rule(source={"status": "guess"}), "source.status"),
    (rule(clock_kind="SOMETIMES"), "clock_kind"),
    (rule(duration={"value": 0, "unit": "calendar_days"}), "positive integer"),
    (rule(computed="lease_eoa_stop_year"), "exactly one"),
])
def test_invalid_rules_are_rejected(bad, message):
    with pytest.raises(ValidationFailed, match=message):
        RuleParser().parse({"rules": [bad]})


@pytest.mark.parametrize("raw", [
    [],
    {"rules": "not-a-list"},
    {"rules": [rule(duration="not-an-object")]},
    {"rules": [rule(duration={"value": 1, "unit": []})]},
    {"rules": [rule(source={"status": []})]},
])
def test_malformed_rule_shapes_raise_validation_error(raw):
    with pytest.raises(ValidationFailed):
        RuleParser().parse(raw)


def test_duplicate_rule_ids_are_rejected():
    with pytest.raises(ValidationFailed, match="duplicate"):
        RuleParser().parse({"rules": [rule(), rule()]})


def test_working_day_rule_requires_calendar_version_and_count_convention():
    raw = rule(duration={"value": 3, "unit": "working_days"})
    with pytest.raises(ValidationFailed, match="calendar_id version"):
        RuleParser().parse({"rules": [raw]})

    raw["calendar_id"] = "TEST@v1"
    with pytest.raises(ValidationFailed, match="count_anchor_day"):
        RuleParser().parse({"rules": [raw]})

    raw["count_anchor_day"] = False
    parsed = RuleParser().parse({"rules": [raw]})["X"]
    assert parsed.calendar_id == "TEST@v1"
    assert parsed.count_anchor_day is False


def test_rule_parser_rejects_unsupported_month_end_policy():
    with pytest.raises(ValidationFailed, match="month_end must be 'clamp'"):
        RuleParser().parse({"rules": [rule(duration={"value": 2, "unit": "months", "month_end": "roll"})]})
    with pytest.raises(ValidationFailed, match="month_end applies only to month durations"):
        RuleParser().parse({"rules": [rule(duration={"value": 2, "unit": "calendar_days", "month_end": "clamp"})]})
    bad_computed = rule()
    bad_computed.pop("duration")
    bad_computed["computed"] = []
    with pytest.raises(ValidationFailed, match="computed must be a non-empty rule name"):
        RuleParser().parse({"rules": [bad_computed]})


def test_anchor_count_fields_are_rejected_for_non_working_rules():
    with pytest.raises(ValidationFailed, match="apply only to working_days"):
        RuleParser().parse({"rules": [rule(calendar_id="TEST@v1", count_anchor_day=False)]})


def test_a_rule_can_fall_due_on_its_anchor_date():
    on_date = {k: v for k, v in rule(due="on_anchor_date").items() if k != "duration"}
    parsed = RuleParser().parse({"rules": [on_date]})
    assert parsed["X"].due == "on_anchor_date" and parsed["X"].duration is None
    r1 = RuleParser().parse(yaml.safe_load(R1.read_text(encoding="utf-8")))
    assert r1["DOCUMENT_EXPIRY"].due == "on_anchor_date" and r1["DOCUMENT_EXPIRY"].source_status == "verified"
    assert r1["STRUCTURAL_STABILITY_VALIDITY"].duration == Duration(60, "months", "clamp")
    with pytest.raises(ValidationFailed, match="exactly one"):
        RuleParser().parse({"rules": [rule(due="on_anchor_date")]})
    with pytest.raises(ValidationFailed, match="due must be"):
        RuleParser().parse({"rules": [{k: v for k, v in rule(due="whenever").items() if k != "duration"}]})
