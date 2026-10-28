"""Exhaustive data-driven pure-core cases: no database or external services."""
from dataclasses import replace
from datetime import date
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest

from app.platform.registry import provide
from app.workflow import engine, guards
from app.workflow.commands import CaseContext, Command, GuardFacts, LetterPayload, Options, Payload, Spec, State, WorkflowConflict, WorkflowValidationFailed
from app.workflow.grammar import ACTIONS, GUARDS, validate_workflow
from app.workflow.registry import _read, parse_routes
from contracts.enums import ApplicationStatus, Role, Stage
from contracts.fakes import AllowAllAuthz, FakeDeadlineRuleParser
from contracts.ports import AuthzPort
from contracts.types import Principal, ResourceRef

ROOT = Path(__file__).resolve().parents[2]
R1 = "aph-2024-27@r1"
CATEGORIES = ("EOA_SELF_DISCLOSURE", "CHANGE_OF_NAME", "NEW_INSTITUTION")
INST = uuid5(NAMESPACE_URL, "engine:institution")
ITEM = uuid5(NAMESPACE_URL, "engine:item")
RESPONSE = uuid5(NAMESPACE_URL, "engine:response")
DECISION = uuid5(NAMESPACE_URL, "engine:decision")
SECOND = uuid5(NAMESPACE_URL, "engine:second")


def definitions():
    raw = _read(ROOT / "rulesets/aph-2024-27/r1/routes.yaml")
    routes = parse_routes(raw["routes"])
    rules = FakeDeadlineRuleParser().parse(_read(ROOT / "rulesets/aph-2024-27/r1/deadlines.yaml"))
    return routes, validate_workflow(raw, routes, rules)


ROUTES, COMPILED = definitions()


def specs(category):
    result = []
    for position, edge in enumerate(COMPILED.routes[category]):
        value = edge.transition.model_dump(mode="json")
        result.append(Spec(position, value["action"], edge.source, edge.target, tuple(value["allowed_roles"]),
                           tuple(value["guards"]), tuple(value["timers"]), value["letter"],
                           value["reason_codes_required"], value, value["emits_event"]))
    return tuple(result)


def letter(kind="LOA", deficiencies=False):
    return LetterPayload(type=kind, academic_year="2027-28", issue_date=date(2026, 7, 1),
                         issue_date_source="PORTAL_EVENT", lists_deficiencies=deficiencies)


def appeal_facts(action: str, source: str, letter_data) -> tuple[str | None, bool | None]:
    """The appeal record each appeal transition needs (status, window lapsed)."""
    if action == "file_appeal":
        return "WINDOW_OPEN", False
    if action == "close_appeal_window":
        return "WINDOW_OPEN", True
    if action.startswith("sac_"):
        return "FILED", None
    if action == "return_to_sac":
        return "REFERRED_BACK", None
    if source == "SAC" and letter_data is not None:
        return "RECOMMENDED", None
    return None, None


def context_and_command(category, spec):
    application_id = uuid5(NAMESPACE_URL, f"engine:{category}:{spec.position}")
    actor = Principal(uuid5(NAMESPACE_URL, "engine:actor"), Role(spec.roles[0]), institution_id=INST)
    data = letter(spec.letter["type"], spec.letter["lists_deficiencies"]) if spec.letter else None
    payload = Payload(target_stage=Stage(spec.target) if spec.action == "revert" else None,
                      item_refs=(ITEM,), response_ref=RESPONSE, decision_ref=DECISION, letter=data)
    command = Command(application_id=application_id, action=spec.action, expected_version=1,
                      reason_code="DEMO_REASON", actor=actor, payload=payload,
                      note_body="DEMO speaking order" if spec.action == "issue_lor" else None)
    status, lapsed = appeal_facts(spec.action, spec.source, data)
    facts = GuardFacts(evc_request_status="PUBLISHED", open_item_count=0, checklist_complete=True, has_assignment=True,
                       dsc_required=True, dsc_present=True, missing_item_keys=(),
                       reason_codes=frozenset({"DEMO_REASON"}), item_refs=frozenset({ITEM}),
                       response_refs=frozenset({RESPONSE}), decision_refs=frozenset({DECISION}), confirmed_letter=data,
                       applicability={"SHC": spec.source == "SHC" or spec.target == "SHC"},
                       live_clock_rules=frozenset({"AICTE_PROCESSING", "INSTITUTION_RESPONSE"}),
                       second_approval_required=False, second_approver_refs=frozenset({SECOND}),
                       appeal_status=status, appeal_window_lapsed=lapsed)
    state = State(application_id, category, R1, None if spec.source == "DRAFT" else spec.source,
                  ApplicationStatus.DRAFT if spec.source == "DRAFT" else ApplicationStatus.IN_PROCESS, 1)
    case = CaseContext(state, ResourceRef("application", application_id, INST),
                       tuple((s.stage.value, s.when) for s in ROUTES[category].stages), specs(category),
                       frozenset(s.stage.value for s in ROUTES[category].stages), facts)
    return case, command


VALID = [(category, spec) for category in CATEGORIES for spec in specs(category)]
INVALID = [(category, stage, action) for category in CATEGORIES
           for stage in ["DRAFT", *(s.value for s in Stage), "APPROVED", "REJECTED", "WITHDRAWN", "BROKEN"]
           for action in [*sorted(ACTIONS), "not_an_action"]
           if stage in {"APPROVED", "REJECTED", "WITHDRAWN", "BROKEN"}
           or not any(t.source == stage and t.action == action for t in specs(category))]


@pytest.mark.parametrize("category,spec", VALID,
                         ids=[f"{c}:{s.source}:{s.action}:{s.target}:{s.position}" for c, s in VALID])
def test_every_expanded_transition_on_three_representative_routes(category, spec):
    case, command = context_and_command(category, spec)
    decision = engine.plan_transition(case, command, Options(True, True))
    assert decision.transition == spec
    assert decision.current_stage == (None if spec.target in {"APPROVED", "REJECTED", "WITHDRAWN"} else spec.target)


@pytest.mark.parametrize("category,stage,action", INVALID)
def test_every_unsupported_stage_action_pair_is_invalid_transition(category, stage, action):
    case, command = context_and_command(category, specs(category)[0])
    status = ApplicationStatus(stage) if stage in {"DRAFT", "APPROVED", "REJECTED", "WITHDRAWN"} else ApplicationStatus.IN_PROCESS
    case = replace(case, state=replace(case.state, current_stage=None if status != ApplicationStatus.IN_PROCESS else stage, status=status))
    command = command.model_copy(update={"action": action, "payload": Payload()})
    with pytest.raises(WorkflowValidationFailed) as raised:
        engine.plan_transition(case, command, Options(True, True))
    assert raised.value.reason_code == "INVALID_TRANSITION" and raised.value.status_code == 422


def advance_case():
    spec = next(s for s in specs("NEW_INSTITUTION") if s.source == "SCRUTINY" and s.action == "advance")
    return context_and_command("NEW_INSTITUTION", spec)


def test_version_conflict_and_deterministic_repeated_planning():
    case, command = advance_case()
    assert engine.plan_transition(case, command, Options()) == engine.plan_transition(case, command, Options())
    with pytest.raises(WorkflowConflict, match="VERSION_CONFLICT"):
        engine.plan_transition(case, command.model_copy(update={"expected_version": 2}), Options())


@pytest.mark.parametrize("name,value,reason", [("open_item_count", 1, "OPEN_DEFICIENCY_ITEMS"),
    ("open_item_count", None, "GUARD_CONTEXT_UNAVAILABLE"), ("has_assignment", False, "ASSIGNMENT_REQUIRED")])
def test_guard_failures_are_coded(name, value, reason):
    case, command = advance_case()
    case = replace(case, facts=replace(case.facts, **{name: value}))
    with pytest.raises(WorkflowValidationFailed, match=reason):
        engine.plan_transition(case, command, Options())


def test_guard_registry_matches_grammar_and_rejects_unknown_guard():
    assert set(guards.REGISTRY) == GUARDS
    case, command = advance_case()
    changed = replace(next(t for t in case.transitions if t.source == "SCRUTINY" and t.action == "advance"), guards=("unregistered",))
    case = replace(case, transitions=(changed,))
    with pytest.raises(WorkflowValidationFailed, match="GUARD_NOT_REGISTERED"):
        engine.plan_transition(case, command, Options())


def test_missing_future_shc_decision_does_not_block_scrutiny_to_evc():
    case, command = advance_case()
    case = replace(case, facts=replace(case.facts, applicability={}))
    assert engine.plan_transition(case, command, Options()).current_stage == "EVC"


def test_letter_flag_defaults_off_and_requires_independent_confirmation():
    spec = next(s for s in specs("EOA_SELF_DISCLOSURE") if s.action == "issue_loa")
    case, command = context_and_command("EOA_SELF_DISCLOSURE", spec)
    with pytest.raises(WorkflowValidationFailed, match="LETTER_ISSUANCE_DISABLED"):
        engine.plan_transition(case, command, Options())
    case = replace(case, facts=replace(case.facts, confirmed_letter=None))
    with pytest.raises(WorkflowValidationFailed, match="LETTER_CONTEXT_UNAVAILABLE"):
        engine.plan_transition(case, command, Options(True, True))


def test_client_cannot_supply_guard_facts_or_free_text_payload():
    _, command = advance_case()
    for payload in [{"open_item_count": 0}, {"checklist_complete": True}, {"remarks": "text"}]:
        with pytest.raises(WorkflowValidationFailed, match="INVALID_COMMAND"):
            engine.parse_command({**command.model_dump(), "payload": payload})


def test_copy_constructed_commands_are_revalidated():
    _, command = advance_case()
    invalid = command.model_copy(update={"payload": {"remarks": "untyped text"}})
    with pytest.raises(WorkflowValidationFailed, match="INVALID_COMMAND"):
        engine.parse_command(invalid)


def test_checklist_guard_is_registered_and_fail_closed():
    case, command = advance_case()
    transition = replace(next(t for t in case.transitions if t.source == "SCRUTINY" and t.action == "advance"), guards=("checklist_complete",))
    for value, reason in [(None, "GUARD_CONTEXT_UNAVAILABLE"), (False, "CHECKLIST_INCOMPLETE")]:
        changed = replace(case, transitions=(transition,), facts=replace(case.facts, checklist_complete=value))
        with pytest.raises(WorkflowValidationFailed, match=reason):
            engine.plan_transition(changed, command, Options())


def test_action_listing_stable_role_scoped_and_side_effect_free(monkeypatch):
    case, command = advance_case()
    provide(AuthzPort, AllowAllAuthz())
    monkeypatch.setattr(engine, "options", lambda: Options(True, True))
    first = engine.list_available_actions(case, command.actor)
    assert first == engine.list_available_actions(case, command.actor)
    assert [a.action for a in first] == sorted(a.action for a in first)
    assert any(a.action == "advance" and a.enabled and a.targets == ("EVC",) for a in first)
    auditor = Principal(command.actor.user_id, Role.AUDITOR)
    assert engine.list_available_actions(case, auditor) == ()
