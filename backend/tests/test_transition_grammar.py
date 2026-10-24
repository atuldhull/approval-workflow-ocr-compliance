"""Load-level grammar failures, graph expansion and all-route preservation."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
import yaml

from app.platform.registry import provide
from app.workflow.grammar import validate_workflow
from app.workflow.registry import RulesetRegistry, _read, parse_routes
from contracts.errors import ValidationFailed
from contracts.fakes import FakeDeadlineRuleParser
from contracts.ports import DeadlineRuleParserPort

FIXTURES = Path(__file__).parent / "fixtures/workflow"
RULESETS = Path(__file__).resolve().parents[2] / "rulesets"


def fixture_registry(tmp_path, text):
    folder = tmp_path / "test/r1"
    folder.mkdir(parents=True)
    (folder / "routes.yaml").write_text(text, encoding="utf-8")
    (folder / "deadlines.yaml").write_text((FIXTURES / "deadlines.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    provide(DeadlineRuleParserPort, FakeDeadlineRuleParser())
    return RulesetRegistry(tmp_path, "test@r1", demo_mode=False)


@pytest.mark.parametrize("fixture,match", [
    ("unknown_stage", "unknown stage"),
    ("unreachable_stage", "unreachable stage"),
    ("no_terminal", "no reachable terminal"),
    ("missing_timer", "unknown timer rule_id"),
    ("revert_no_reason", "revert requires reason code"),
    ("evc_without_shc", "pairs SHC with EVC"),
    ("shc_without_evc", "pairs SHC with EVC"),
    ("letter_no_type", "letter type"),
    ("legal_pause", "non-INTERNAL"),
    ("shc_always", "SHC must be as_applicable"),
    ("unknown_guard", "unknown or duplicate guard"),
    ("unknown_template", "unknown transition template"),
    ("submit_clock_mismatch", "submit timers must match"),
    ("no_terminal_declaration", "terminal_states"),
    ("dead_end_stage", "no path to terminal"),
])
def test_invalid_fixture_rejected_before_cache(tmp_path, fixture, match):
    text = (FIXTURES / f"{fixture}.yaml").read_text(encoding="utf-8")
    registry = fixture_registry(tmp_path, text)
    with pytest.raises(ValidationFailed, match=match):
        registry.get("test@r1")
    assert "test@r1" not in registry._cache


def test_small_valid_fixture_loads(tmp_path):
    registry = fixture_registry(tmp_path, (FIXTURES / "valid.yaml").read_text(encoding="utf-8"))
    assert registry.route_for("X", "test@r1").stages[0].stage == "SCRUTINY"


def test_all_22_stage_lists_preserved_exactly():
    raw = _read(RULESETS / "aph-2024-27/r1/routes.yaml")
    before = json.loads((FIXTURES / "r1_stage_lists_before_1_1.json").read_text(encoding="utf-8"))
    assert len(before) == len(raw["routes"]) == 22
    assert {key: value["stages"] for key, value in raw["routes"].items()} == before
    assert raw["clocks"]["on_submit"] == ["AICTE_PROCESSING"]
    assert raw["appeal"] == {"trigger": "decision.adverse_uploaded", "window": "APPEAL_7D", "max_appeals": 1}
    assert all(spec["transitions"] == raw["transitions"] for spec in raw["routes"].values())


def compiled_r1():
    raw = _read(RULESETS / "aph-2024-27/r1/routes.yaml")
    rules = FakeDeadlineRuleParser().parse(_read(RULESETS / "aph-2024-27/r1/deadlines.yaml"))
    return raw, rules, validate_workflow(raw, parse_routes(raw["routes"]), rules)


@pytest.mark.parametrize("category", list(json.loads((FIXTURES / "r1_stage_lists_before_1_1.json").read_text(encoding="utf-8"))))
def test_each_route_has_submission_and_typed_terminal(category):
    _, _, compiled = compiled_r1()
    edges = compiled.routes[category]
    assert any(e.source == "DRAFT" and e.transition.action == "submit" for e in edges)
    assert any(e.target == "APPROVED" and e.transition.letter is not None for e in edges)
    assert all(e.transition.reason_codes_required for e in edges if e.transition.action == "revert")


def test_optional_shc_and_rescrutiny_resume_expand_from_data():
    _, _, compiled = compiled_r1()
    new = compiled.routes["NEW_INSTITUTION"]
    assert any(e.source == "EVC" and e.target == "EC" for e in new)
    assert any(e.source == "EVC" and e.target == "SHC" for e in new)
    assert any(e.source == "RESCRUTINY" and e.target == "EVC" for e in new)
    assert not any(e.source == "EVC" and e.target == "APPROVED" for e in new)
    existing = compiled.routes["NEW_PROGRAMME"]
    assert any(e.source == "EVC" and e.target == "APPROVED" for e in existing)


def test_unrecognized_category_uses_same_generic_expansion():
    raw, rules, _ = compiled_r1()
    raw["routes"] = {"FICTIONAL_DEMO": deepcopy(raw["routes"]["NEW_INSTITUTION"])}
    compiled = validate_workflow(raw, parse_routes(raw["routes"]), rules)
    assert "FICTIONAL_DEMO" in compiled.routes


@pytest.mark.parametrize("fragment", ["routes: {}\nroutes: {}\n", "- not\n- a\n- mapping\n", "!!python/object:builtins.object {}\n"])
def test_malformed_or_unsafe_yaml_is_domain_error(tmp_path, fragment):
    registry = fixture_registry(tmp_path, fragment)
    with pytest.raises(ValidationFailed):
        registry.get("test@r1")


@pytest.mark.parametrize("change,match", [
    ({"to_stage": "NOT_A_STAGE"}, "unknown stage"),
    ({"allowed_roles": ["ADMIN"]}, "invalid transition"),
    ({"to_stage": "$previous"}, "reserved for revert"),
    ({"timers": [{"op": "open", "rule_id": "PROCESSING", "anchor": None}]}, "open needs an anchor"),
    ({"timers": [{"op": "close", "rule_id": "PROCESSING", "anchor": None}]}, "close needs outcome"),
    ({"letter": None}, "letter trigger"),
])
def test_invalid_template_semantics(tmp_path, change, match):
    raw = yaml.safe_load((FIXTURES / "valid.yaml").read_text(encoding="utf-8"))
    raw["templates"]["finish"].update(change)
    registry = fixture_registry(tmp_path, yaml.safe_dump(raw))
    with pytest.raises(ValidationFailed, match=match):
        registry.get("test@r1")


def test_guard_expressions_are_never_evaluated(tmp_path):
    raw = yaml.safe_load((FIXTURES / "valid.yaml").read_text(encoding="utf-8"))
    raw["templates"]["finish"]["guards"] = ["__import__('os').system('echo unsafe')"]
    registry = fixture_registry(tmp_path, yaml.safe_dump(raw))
    with pytest.raises(ValidationFailed, match="guard"):
        registry.get("test@r1")


def test_timer_cannot_borrow_rule_from_another_revision(tmp_path):
    registry = fixture_registry(tmp_path, (FIXTURES / "missing_timer.yaml").read_text(encoding="utf-8"))
    other = tmp_path / "test/r2"
    other.mkdir()
    (other / "deadlines.yaml").write_text("rules:\n  - id: MISSING_RULE\n", encoding="utf-8")
    with pytest.raises(ValidationFailed, match="unknown timer rule_id"):
        registry.get("test@r1")


def test_revert_has_only_earlier_candidate_stages():
    raw, _, compiled = compiled_r1()
    plan = [s.stage.value for s in parse_routes(raw["routes"])["NEW_INSTITUTION"].stages]
    for edge in compiled.routes["NEW_INSTITUTION"]:
        if edge.transition.action != "revert":
            continue
        anchor = raw["auxiliary_stages"].get(edge.source, edge.source)
        assert edge.target in plan
        assert plan.index(edge.target) <= plan.index(anchor)
        if edge.source in plan:
            assert plan.index(edge.target) < plan.index(edge.source)
        assert {"reason_code_present", "previous_stage_visited"} <= set(edge.transition.guards)


@pytest.mark.parametrize("clocks", [[], {"on_submit": "PROCESSING"}, {"on_submit": [{}]}])
def test_malformed_submit_clocks_are_domain_errors(tmp_path, clocks):
    raw = yaml.safe_load((FIXTURES / "valid.yaml").read_text(encoding="utf-8"))
    raw["clocks"] = clocks
    registry = fixture_registry(tmp_path, yaml.safe_dump(raw))
    with pytest.raises(ValidationFailed, match="clocks.on_submit"):
        registry.get("test@r1")
