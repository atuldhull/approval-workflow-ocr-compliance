"""Validate the configurable demo rule before any queue/clock mutation."""
from copy import deepcopy

import pytest

from app.workflow.evc_config import validate_config
from contracts.errors import ValidationFailed
from contracts.fakes import FakeEvc
from contracts.ports import EvcPort

CONFIG = dict(rule_id="EVC_PROCESSING", source_status="DEMO_ASSUMPTION", assumption_code="EVC_DURATION_UNCONFIRMED")
RULE = dict(clock_kind="INTERNAL", clock_owner="COMMITTEE", source=dict(status="demo_assumption"),
            duration=dict(value=7, unit="calendar_days"))


def test_demo_config_and_shared_fake_are_valid():
    assert validate_config(dict(evc=CONFIG), {"EVC_PROCESSING": RULE}) == CONFIG
    assert isinstance(FakeEvc(), EvcPort)


@pytest.mark.parametrize("field,value", [("clock_kind", "LEGAL"), ("clock_owner", "AICTE"),
    ("duration", dict(value=0, unit="calendar_days")), ("duration", dict(value=True, unit="calendar_days")),
    ("duration", dict(value=7, unit="working_days")), ("source", dict(status="verified"))])
def test_bad_or_unconfirmed_policy_cannot_masquerade_as_legal(field, value):
    rule = deepcopy(RULE)
    rule[field] = value
    with pytest.raises(ValidationFailed):
        validate_config(dict(evc=CONFIG), {"EVC_PROCESSING": rule})


@pytest.mark.parametrize("config", [[], "EVC", {}, dict(CONFIG, extra=True), dict(CONFIG, source_status="VERIFIED")])
def test_invalid_config_shape_rejected(config):
    with pytest.raises(ValidationFailed):
        validate_config(dict(evc=config), {"EVC_PROCESSING": RULE})


def test_missing_rule_or_missing_evc_config_rejected():
    with pytest.raises(ValidationFailed):
        validate_config(dict(evc=CONFIG), {})
    with pytest.raises(ValidationFailed, match="EVC_CONFIG_UNAVAILABLE"):
        validate_config(dict(routes=dict(DEMO=dict(stages=["EVC"]))), {})
