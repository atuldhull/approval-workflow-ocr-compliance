"""Answer-key proposal: structural contract, real example and semantic checks."""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError
import pytest
import yaml

from generator.cases.answer_key_models import AnswerKey, answer_key_json_schema

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "docs/p1/answer_key.schema.json").read_text(encoding="utf-8"))
EXAMPLE = json.loads((ROOT / "docs/p1/answer_key_example.json").read_text(encoding="utf-8"))
FORMATS = FormatChecker()


@FORMATS.checks("date-time", raises=ValueError)
def valid_datetime(value):
    # jsonschema's RFC3339 checker is optional and absent in the pinned dev setup.
    # The schema pattern separately enforces canonical UTC spelling.
    if isinstance(value, str):
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    return True


VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FORMATS)


def test_hand_written_example_matches_schema_and_models():
    Draft202012Validator.check_schema(SCHEMA)
    VALIDATOR.validate(EXAMPLE)
    assert AnswerKey.model_validate(EXAMPLE).model_dump(mode="json") == EXAMPLE


def test_schema_exactly_mirrors_pydantic():
    assert SCHEMA == answer_key_json_schema()


def test_example_route_and_clock_rules_match_pinned_yaml():
    routes = yaml.safe_load((ROOT / "rulesets/aph-2024-27/r1/routes.yaml").read_text(encoding="utf-8"))
    rules = yaml.safe_load((ROOT / "rulesets/aph-2024-27/r1/deadlines.yaml").read_text(encoding="utf-8"))
    app = EXAMPLE["applications"][0]
    normalized = [dict(stage=s, when="always") if isinstance(s, str) else s
                  for s in routes["routes"][app["route_id"]]["stages"]]
    assert EXAMPLE["workflow_expectations"][0]["route_outcome"]["expected_stage_list"] == normalized
    assert {c["rule_id"] for c in EXAMPLE["clock_expectations"]} <= {r["id"] for r in rules["rules"]}


def test_same_explicit_input_serializes_deterministically():
    assert AnswerKey.model_validate(EXAMPLE).model_dump_json() == AnswerKey.model_validate(deepcopy(EXAMPLE)).model_dump_json()


def set_value(data, path, value):
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


@pytest.mark.parametrize("path,value", [
    (("header", "seed"), -1),
    (("header", "seed"), True),
    (("header", "seed"), "1"),
    (("header", "label"), "REAL"),
    (("header", "generated_at_clock"), "2026-02-30T04:30:00Z"),
    (("header", "generated_at_clock"), "2026-07-01T04:30:00"),
    (("header", "generator_version"), "latest version"),
    (("institutions", 0, "id"), "not-a-uuid"),
    (("institutions", 0, "region"), "Southern region notes"),
    (("applications", 0, "category"), "new programme"),
    (("workflow_expectations", 0, "route_outcome", "expected_status"), "UNKNOWN"),
    (("workflow_expectations", 0, "route_outcome", "expected_stage_list", 0, "stage"), "UNKNOWN"),
    (("workflow_expectations", 0, "route_outcome", "expected_stage_list", 2, "when"), "sometimes"),
    (("workflow_expectations", 0, "letters_to_issue", 0, "type"), "UNKNOWN"),
    (("workflow_expectations", 0, "letters_to_issue", 0, "lists_deficiencies"), "true"),
    (("clock_expectations", 1, "clock_kind"), "LEGAL"),
    (("clock_expectations", 0, "expected_due_date"), "2026-02-30"),
    (("clock_expectations", 3, "outcome"), "BREACHED"),
    (("p2_extensions",), {"ocr_truth": "unreviewed"}),
    (("p3_extensions",), {"tamper_target": "unreviewed"}),
    (("workflow_expectations", 0, "notes"), "arbitrary free text"),
])
def test_invalid_values_fail_both_schema_and_models(path, value):
    data = deepcopy(EXAMPLE)
    set_value(data, path, value)
    assert list(VALIDATOR.iter_errors(data))
    with pytest.raises(ValidationError):
        AnswerKey.model_validate(data)


@pytest.mark.parametrize("path,value", [
    (("header", "counts", "applications"), 2),
    (("applications", 0, "institution_id"), "00000000-0000-4000-8000-999999999999"),
    (("applications", 0, "pinned_ruleset_key"), "aph-2024-27@r3-DEMO"),
    (("applications", 0, "route_id"), "MERGER"),
    (("workflow_expectations",), []),
    (("workflow_expectations", 0, "deficiency_loop_count"), 2),
    (("workflow_expectations", 0, "late_responses", 0, "late_by_seconds"), 1),
    (("workflow_expectations", 0, "evc_delays", 0, "delay_seconds"), 1),
    (("workflow_expectations", 0, "deficiency_loops", 0, "items", 1, "status"), "RESOLVED"),
    (("workflow_expectations", 0, "deficiency_loops", 0, "as_of_clock"), "2026-07-01T04:30:00Z"),
    (("workflow_expectations", 0, "deficiency_loops", 0, "response_id"), None),
    (("workflow_expectations", 0, "late_responses", 0, "loop_id"), "00000000-0000-4000-8000-999999999999"),
    (("clock_expectations", 1, "application_id"), "00000000-0000-4000-8000-999999999999"),
    (("clock_expectations", 1, "subject_id"), "00000000-0000-4000-8000-999999999999"),
    (("clock_expectations", 0, "anchor_at_clock"), "2027-07-01T04:30:00Z"),
    (("clock_expectations", 1, "id"), EXAMPLE["clock_expectations"][0]["id"]),
])
def test_semantic_invariants_beyond_json_schema(path, value):
    data = deepcopy(EXAMPLE)
    set_value(data, path, value)
    VALIDATOR.validate(data)  # Demonstrate the documented structural/semantic boundary.
    with pytest.raises(ValidationError):
        AnswerKey.model_validate(data)


@pytest.mark.parametrize("key", ["header", "p2_extensions", "p3_extensions", "clock_expectations"])
def test_required_sections_cannot_be_omitted(key):
    data = deepcopy(EXAMPLE)
    del data[key]
    assert list(VALIDATOR.iter_errors(data))
    with pytest.raises(ValidationError):
        AnswerKey.model_validate(data)
