import re

import pytest

from app.workflow import engine
from app.workflow.commands import Options, WorkflowValidationFailed
from app.workflow.grammar import ACTIONS as CANONICAL_ACTIONS
from acceptance.route_support import ACTIONS, ALIASES, MATRIX, RAW, core_input, matrix_counts, raw_pair_allowed


@pytest.mark.parametrize("category,stage,action", MATRIX, ids=["/".join(pair) for pair in MATRIX])
def test_complete_stage_action_product(category, stage, action):
    expected = raw_pair_allowed(category, stage, action)
    context, command, compiled = core_input(category, stage, action)
    assert compiled == expected, "production expansion disagrees with raw-YAML selector oracle"
    if expected:
        decision = engine.plan_transition(context, command, Options(demo_mode=True, enable_letter_issuance=True))
        assert decision.transition.source == stage and decision.transition.action == ALIASES.get(action, action)
    else:
        with pytest.raises(WorkflowValidationFailed) as error:
            engine.plan_transition(context, command, Options(demo_mode=True, enable_letter_issuance=True))
        assert error.value.status_code == 422
        assert error.value.reason_code == "INVALID_TRANSITION"
        assert re.fullmatch(r"[A-Z][A-Z0-9_]*", error.value.reason_code)


def test_matrix_is_complete_and_includes_every_canonical_action():
    assert {t["action"] for t in RAW["templates"].values()} == set(CANONICAL_ACTIONS)
    counts = matrix_counts()
    assert counts["routes"] == 24 and counts["total"] == counts["routes"] * counts["stages"] * len(ACTIONS)
    assert counts["invalid"] > 0 and counts["valid"] > 0
