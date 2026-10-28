"""Lease stop academic year (APH 2.1(e), 6.17) and the ruleset's alert / academic-year configuration."""
from datetime import date, datetime
from pathlib import Path

import pytest
import yaml

from app.deadlines.escalation import OWNER, parse_alert_config, parse_offset
from app.deadlines.rules import AcademicYearStart, RuleParser, lease_eoa_stop_year, lease_meets_minimum
from contracts.enums import Role
from contracts.errors import ValidationFailed

JULY = AcademicYearStart(7, 1)
RULESET = Path(__file__).resolve().parents[2] / "rulesets" / "aph-2024-27" / "r1" / "deadlines.yaml"


@pytest.mark.parametrize("lease_end, years, expected", [
    # remaining lease equals 4 years exactly on 1 Jul 2036, the first day of AY 2036-37
    (date(2040, 6, 30), 4, "2036-37"),
    # one day shorter: 4 years remain only up to 30 Jun 2036, still in AY 2035-36
    (date(2040, 6, 29), 4, "2035-36"),
    # one day longer: the crossing moves to 2 Jul 2036, still AY 2036-37
    (date(2040, 7, 1), 4, "2036-37"),
    # mid-year lease end: 4 years remain until 16 Mar 2037, inside AY 2036-37
    (date(2041, 3, 15), 4, "2036-37"),
])
def test_stop_year_around_the_academic_year_boundary(lease_end, years, expected):
    assert lease_eoa_stop_year(lease_end, years, JULY) == expected


@pytest.mark.parametrize("lease_end, years, expected", [
    # 1 Mar 2036 + 4 years - 1 day = 29 Feb 2040
    (date(2040, 2, 29), 4, "2035-36"),
    # 1 Mar 2037 + 3 years - 1 day = 29 Feb 2040
    (date(2040, 2, 29), 3, "2036-37"),
    # a lease ending 28 Feb in a leap year: from 1 Mar 2037 it would need 29 Feb 2040, so 28 Feb 2037 is the day
    (date(2040, 2, 28), 3, "2036-37"),
    # a one-year course from 1 Mar 2040 ends 28 Feb 2041
    (date(2041, 2, 28), 1, "2039-40"),
])
def test_stop_year_with_leap_days(lease_end, years, expected):
    assert lease_eoa_stop_year(lease_end, years, JULY) == expected


@pytest.mark.parametrize("years, expected", [(1, "2049-50"), (2, "2048-49"), (4, "2046-47"), (5, "2045-46")])
def test_longer_courses_stop_earlier(years, expected):
    assert lease_eoa_stop_year(date(2050, 6, 30), years, JULY) == expected


def test_the_academic_year_start_is_configurable():
    # with an August start, 1 Jul 2036 still belongs to AY 2035-36
    assert lease_eoa_stop_year(date(2040, 6, 30), 4, AcademicYearStart(8, 1)) == "2035-36"
    assert lease_eoa_stop_year(date(2040, 7, 31), 4, AcademicYearStart(8, 1)) == "2036-37"


def test_a_30_year_extension_moves_the_stop_year_by_30_years():
    assert lease_eoa_stop_year(date(2070, 6, 30), 4, JULY) == "2066-67"


@pytest.mark.parametrize("args", [
    (datetime(2040, 6, 30), 4, JULY),
    ("2040-06-30", 4, JULY),
    (date(2040, 6, 30), 0, JULY),
    (date(2040, 6, 30), 11, JULY),
    (date(2040, 6, 30), True, JULY),
    (date(2040, 6, 30), 4.0, JULY),
    (date(2040, 6, 30), 4, (7, 1)),
])
def test_bad_inputs_are_refused(args):
    with pytest.raises(ValidationFailed):
        lease_eoa_stop_year(*args)


@pytest.mark.parametrize("value", ["02-29", "13-01", "7-1", "07/01", "04-31", None, 701])
def test_bad_academic_year_starts_are_refused(value):
    with pytest.raises(ValidationFailed):
        AcademicYearStart.parse(value)


def test_minimum_lease_of_30_years_counts_the_end_date():
    assert lease_meets_minimum(date(2010, 7, 1), date(2040, 6, 30))
    assert not lease_meets_minimum(date(2010, 7, 1), date(2040, 6, 29))
    with pytest.raises(ValidationFailed):
        lease_meets_minimum(date(2040, 1, 1), date(2039, 1, 1))


# ---- ruleset configuration ----

def shipped():
    return yaml.safe_load(RULESET.read_text(encoding="utf-8"))


def test_shipped_ruleset_labels_alerts_and_academic_year_as_demo_assumptions():
    raw = shipped()
    rules = RuleParser().parse(raw)
    assert raw["alerts"]["source"]["status"] == "demo_assumption"
    assert raw["academic_year"]["source"]["status"] == "demo_assumption"
    assert rules.academic_year == JULY
    standard = rules.alerts.ladders["standard"]
    assert [s.to for s in standard] == [OWNER, "RO_OFFICER", "BUREAU_OFFICER", "BUREAU_HEAD"]
    assert rules.alerts.role_for(standard[0], "INSTITUTION") == Role.INSTITUTION
    assert rules.alerts.ladder(rules["APPEAL_7D"]) == rules.alerts.ladders["reminder_only"]
    assert rules.alerts.ladder(rules["AICTE_PROCESSING"]) == standard


def config(**overrides):
    raw = dict(shipped()["alerts"])
    raw.update(overrides)
    return raw


@pytest.mark.parametrize("overrides", [
    {"channels": ["pager"]},
    {"channels": []},
    {"owner_roles": {"AICTE": "RO_OFFICER"}},
    {"owner_roles": {"AICTE": "AUDITOR", "INSTITUTION": "INSTITUTION", "COMMITTEE": "SCRUTINY_COMMITTEE"}},
    {"default_ladder": "missing"},
    {"source": {"status": "guess"}},
    {"ladders": {"x": [{"level": 0, "to": "owner", "at": "1d", "template": "nope"}]}},
    {"ladders": {"x": [{"level": 0, "to": "owner", "at": "1d", "template": "deadline.reminder"},
                       {"level": 1, "to": "BUREAU_HEAD", "at": "1d", "template": "deadline.escalated"}]}},
    {"ladders": {"x": [{"level": 1, "to": "owner", "at": "1d", "template": "deadline.reminder"}]}},
    {"ladders": {"x": [{"level": 0, "to": "SYSTEM", "at": "1d", "template": "deadline.reminder"}]}},
    {"ladders": {"x": [{"level": 0, "to": "owner", "at": "1 week", "template": "deadline.reminder"}]}},
])
def test_bad_alert_configuration_is_refused(overrides):
    with pytest.raises(ValidationFailed):
        parse_alert_config(config(**overrides))


def test_a_rule_naming_an_unknown_ladder_is_refused():
    raw = shipped()
    raw["rules"][0]["alert_ladder"] = "missing"
    with pytest.raises(ValidationFailed, match="alert_ladder"):
        RuleParser().parse(raw)


def test_offsets():
    assert parse_offset("-2d", "x").days == -2
    assert parse_offset("12h", "x").total_seconds() == 12 * 3600
    assert parse_offset("+0d", "x").total_seconds() == 0


# ---- a rule's own reminders ----

def test_a_rules_reminders_replace_the_ladders_advance_steps():
    rules = RuleParser().parse(shipped())
    ladder = rules.alerts.ladder(rules["DEPOSIT_15D"])
    assert [(s.level, s.to, s.offset.days, s.template, s.advance) for s in ladder] == [
        (0, OWNER, -7, "deadline.reminder", True), (1, OWNER, -2, "deadline.reminder", True),
        (2, OWNER, -1, "deadline.reminder", True), (3, "RO_OFFICER", 0, "deadline.breached", False),
        (4, "BUREAU_OFFICER", 3, "deadline.escalated", False), (5, "BUREAU_HEAD", 7, "deadline.escalated", False)]
    expiry = rules.alerts.ladder(rules["DOCUMENT_EXPIRY"])
    assert [(s.to, s.offset.days) for s in expiry] == [
        (OWNER, -90), (OWNER, -30), (OWNER, -7), ("RO_OFFICER", 0), ("BUREAU_OFFICER", 7), ("BUREAU_HEAD", 30)]
    # a computed rule has no clock; its reminders (months before the stop year) stay information
    assert rules.alerts.ladder(rules["LEASE_EOA_STOP"]) == rules.alerts.ladders["standard"]


@pytest.mark.parametrize("reminders, message", [
    (["2d"], "before the due time"),
    (["-2d", "-7d"], "earliest first"),
    (["-7d", "-7d"], "earliest first"),
    ("-7d", "non-empty list"),
    (["-2 weeks"], "offset"),
    ([f"-{n}d" for n in range(20, 11, -1)], "exceed"),
])
def test_bad_rule_reminders_are_refused(reminders, message):
    raw = shipped()
    rule = next(r for r in raw["rules"] if r["id"] == "AICTE_PROCESSING")
    rule["reminders"] = reminders
    with pytest.raises(ValidationFailed, match=message):
        RuleParser().parse(raw)


def test_reminders_need_a_ladder():
    raw = shipped()
    rule = next(r for r in raw["rules"] if r["id"] == "AICTE_PROCESSING")
    rule["reminders"], rule["alert_ladder"] = ["-2d"], "none"
    with pytest.raises(ValidationFailed, match="alert ladder"):
        RuleParser().parse(raw)
