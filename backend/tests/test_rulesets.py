from pathlib import Path

import pytest

from app.platform.registry import provide
from app.workflow.registry import RulesetRegistry, parse_routes
from contracts.enums import Stage
from contracts.errors import Forbidden, ValidationFailed
from contracts.fakes import FakeDeadlineRuleParser
from contracts.ports import DeadlineRuleParserPort

RULESETS = Path(__file__).resolve().parents[2] / "rulesets"


@pytest.fixture
def registry():
    provide(DeadlineRuleParserPort, FakeDeadlineRuleParser())
    return RulesetRegistry(RULESETS, "aph-2024-27@r1", demo_mode=False)


def stages(registry, category):
    return [s.stage for s in registry.route_for(category, "aph-2024-27@r1").stages]


def test_r1_has_all_table_2_3_rows_plus_new_institution(registry):
    assert len(registry.get("aph-2024-27@r1").routes) == 22


def test_shc_is_optional_exactly_where_evc_is_required(registry):
    for route in registry.get("aph-2024-27@r1").routes.values():
        names = [s.stage for s in route.stages]
        assert (Stage.EVC in names) == (Stage.SHC in names), route.category
        for s in route.stages:
            if s.stage == Stage.SHC:
                assert s.when == "as_applicable"


def test_rows_corrected_from_the_page_image(registry):
    assert stages(registry, "EOA_SELF_DISCLOSURE") == [Stage.SELF_DISCLOSURE]
    assert stages(registry, "NRI_SEATS") == [Stage.SELF_DISCLOSURE]
    assert stages(registry, "CHANGE_OF_NAME") == [Stage.SCRUTINY]
    assert stages(registry, "MERGER") == [Stage.SCRUTINY, Stage.EVC, Stage.SHC]


def test_new_institution_follows_chapter_one(registry):
    assert stages(registry, "NEW_INSTITUTION") == [Stage.SCRUTINY, Stage.EVC, Stage.SHC, Stage.EC, Stage.COUNCIL]


def test_unknown_category_is_rejected(registry):
    with pytest.raises(ValidationFailed):
        registry.route_for("NOT_A_CATEGORY", "aph-2024-27@r1")


def test_static_validation_rejects_bad_routes():
    with pytest.raises(ValidationFailed, match="unknown stage"):
        parse_routes({"X": {"stages": ["SCRUTINY", "INSPECTION"]}})
    with pytest.raises(ValidationFailed, match="pairs SHC with EVC"):
        parse_routes({"X": {"stages": ["SCRUTINY", {"stage": "SHC", "when": "as_applicable"}]}})


def test_unverified_overlay_is_refused_outside_demo_mode(registry):
    with pytest.raises(Forbidden):
        registry.get("aph-2024-27@r3-DEMO")


def test_overlay_changes_roles_but_not_routes():
    provide(DeadlineRuleParserPort, FakeDeadlineRuleParser())
    demo = RulesetRegistry(RULESETS, "aph-2024-27@r1", demo_mode=True)
    r1, r3 = demo.get("aph-2024-27@r1"), demo.get("aph-2024-27@r3-DEMO")
    assert r1.roles["evc_constituted_by"] == "REGIONAL_OFFICER"
    assert r3.roles["evc_constituted_by"] == "COUNCIL"
    assert r3.routes == r1.routes
    assert r3.banner and "SIMULATION" in r3.banner
