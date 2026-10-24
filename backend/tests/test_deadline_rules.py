from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import yaml

from app.deadlines.rules import Duration, RuleParser, add_months, due_date
from contracts.enums import ClockKind
from contracts.errors import ValidationFailed

R1 = Path(__file__).resolve().parents[2] / "rulesets" / "aph-2024-27" / "r1" / "deadlines.yaml"


def test_month_end_is_clamped():
    assert add_months(date(2026, 8, 31), 6) == date(2027, 2, 28)
    assert add_months(date(2027, 8, 31), 6) == date(2028, 2, 29)
    assert add_months(date(2026, 1, 15), 6) == date(2026, 7, 15)
    assert add_months(date(2026, 11, 30), 3) == date(2027, 2, 28)


def test_due_dates_use_the_indian_calendar_date():
    # 20:00 UTC on 1 July is already 2 July in India
    anchor = datetime(2026, 7, 1, 20, 0, tzinfo=timezone.utc)
    assert due_date(anchor, Duration(7, "calendar_days")) == date(2026, 7, 9)


def test_working_days_need_a_calendar():
    with pytest.raises(ValidationFailed, match="holiday calendar"):
        due_date(datetime(2026, 7, 1, tzinfo=timezone.utc), Duration(5, "working_days"))


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


def test_duplicate_rule_ids_are_rejected():
    with pytest.raises(ValidationFailed, match="duplicate"):
        RuleParser().parse({"rules": [rule(), rule()]})
