"""Named pure guards and explicit workflow-local authoritative fact injection."""
from dataclasses import dataclass, replace
from typing import Callable
from sqlalchemy import select

from app.workflow.commands import CaseContext, Command, GuardFacts, Spec, WorkflowValidationFailed
from app.workflow.models import Ruleset
from app.workflow.storage import applications, application_items
from contracts.ports import UnitOfWork


@dataclass(frozen=True)
class Context:
    case: CaseContext
    command: Command
    transition: Spec
    preview: bool = False


REGISTRY: dict[str, Callable[[Context], None]] = {}
_fact_loader: Callable[[UnitOfWork, object, Command], GuardFacts] | None = None


def register(name: str):
    def decorate(function):
        if name in REGISTRY:
            raise ValueError(f"duplicate guard {name}")
        REGISTRY[name] = function
        return function
    return decorate


def register_fact_loader(loader: Callable[[UnitOfWork, object, Command], GuardFacts] | None) -> None:
    """Workflow-owned server wiring only; never bind this to command payload data."""
    global _fact_loader
    _fact_loader = loader


def read_facts(uow: UnitOfWork, case, command: Command) -> GuardFacts:
    facts = _fact_loader(uow, case, command) if _fact_loader else GuardFacts()
    if not isinstance(facts, GuardFacts):
        raise WorkflowValidationFailed("GUARD_CONTEXT_UNAVAILABLE")
    if case.status == "DRAFT" and command.action in {"submit", "list_actions"}:
        metadata = uow.session.scalar(select(Ruleset.source_metadata).where(Ruleset.key == case.ruleset_key))
        config = (metadata or {}).get("intake", {}).get(case.route_id)
        if config is None:
            raise WorkflowValidationFailed("INTAKE_RULESET_NOT_LOADED")
        provided = tuple(uow.session.scalars(select(application_items.c.item_key).where(
            application_items.c.application_id == case.application_id, application_items.c.state == "PROVIDED")
            .order_by(application_items.c.item_key)))
        missing = [i["item_key"] for i in config["items"] if i["mandatory"] and i["item_key"] not in provided]
        present = command.payload.dsc_present
        if present is None:
            present = uow.session.scalar(select(applications.c.dsc_present).where(applications.c.id == case.application_id))
        if config["dsc_required"] and not present:
            missing.append("DSC")
        facts = replace(facts, checklist_complete=not any(key != "DSC" for key in missing),
                        missing_item_keys=tuple(sorted(missing)), provided_item_keys=provided,
                        dsc_required=config["dsc_required"], dsc_present=bool(present))
    return facts


def require(value, reason: str) -> None:
    if value is None:
        raise WorkflowValidationFailed("GUARD_CONTEXT_UNAVAILABLE")
    if not value:
        raise WorkflowValidationFailed(reason)


def applicable_stages(case: CaseContext) -> tuple[str, ...]:
    result = []
    for stage, when in case.stages:
        if when == "as_applicable":
            selected = case.facts.applicability.get(stage)
            if selected is None:
                raise WorkflowValidationFailed("APPLICABILITY_UNAVAILABLE")
            if not selected:
                continue
        result.append(stage)
    return tuple(result)


def effective_stage(case: CaseContext) -> str:
    source = case.state.source
    names = {stage for stage, _ in case.stages}
    if source in names:
        return source
    # Infer auxiliary anchors from explicit persisted edges, not timestamp ties
    # or hardcoded category/RESCRUTINY branches.
    pending, seen, anchors = [source], set(), set()
    while pending:
        node = pending.pop()
        if node in seen:
            continue
        seen.add(node)
        for edge in case.transitions:
            if edge.target != node or edge.definition.get("to_stage", "").startswith("$"):
                continue
            if edge.source in names:
                anchors.add(edge.source)
            elif edge.source != "DRAFT":
                pending.append(edge.source)
    if len(anchors) != 1:
        raise WorkflowValidationFailed("AUXILIARY_CONTEXT_UNAVAILABLE")
    return next(iter(anchors))


def next_stage(case: CaseContext) -> str | None:
    plan = tuple(s for s, _ in case.stages)
    source = effective_stage(case)
    if source not in plan:
        raise WorkflowValidationFailed("APPLICABILITY_CONFLICT")
    index = plan.index(source)
    for stage, when in case.stages[index + 1:]:
        if when == "always":
            return stage
        selected = case.facts.applicability.get(stage)
        if selected is None:
            raise WorkflowValidationFailed("APPLICABILITY_UNAVAILABLE")
        if selected:
            return stage
    return None


def evaluate(context: Context) -> None:
    if context.command.actor.role not in context.transition.roles:
        raise WorkflowValidationFailed("ROLE_NOT_ALLOWED")
    if context.transition.reason_required or context.command.reason_code is not None:
        reason_code_present(context)
    for name in context.transition.guards:
        function = REGISTRY.get(name)
        if function is None:
            raise WorkflowValidationFailed("GUARD_NOT_REGISTERED")
        function(context)


@register("application_is_draft")
def application_is_draft(c: Context) -> None:
    require(c.case.state.status == "DRAFT", "APPLICATION_NOT_DRAFT")


@register("open_items_zero")
def open_items_zero(c: Context) -> None:
    count = c.case.facts.open_item_count
    require(None if count is None else count == 0, "OPEN_DEFICIENCY_ITEMS")


@register("checklist_complete")
def checklist_complete(c: Context) -> None:
    if c.case.facts.missing_item_keys and not (c.preview and c.case.facts.missing_item_keys == ("DSC",)):
        raise WorkflowValidationFailed("MANDATORY_ITEMS_MISSING", c.case.facts.missing_item_keys)
    require(c.case.facts.checklist_complete, "CHECKLIST_INCOMPLETE")


@register("dsc_required")
def dsc_required(c: Context) -> None:
    require(c.case.facts.dsc_required is not None, "GUARD_CONTEXT_UNAVAILABLE")
    if c.preview:
        return  # UI may collect the required presence flag in the submit form.
    if c.case.facts.dsc_required and not c.case.facts.dsc_present:
        raise WorkflowValidationFailed("MANDATORY_ITEMS_MISSING", c.case.facts.missing_item_keys or ("DSC",))


@register("actor_has_assignment")
def actor_has_assignment(c: Context) -> None:
    require(c.case.facts.has_assignment, "ASSIGNMENT_REQUIRED")


@register("reason_code_present")
def reason_code_present(c: Context) -> None:
    require(c.case.facts.reason_codes is not None, "REASON_CATALOG_UNAVAILABLE")
    if c.preview and c.command.reason_code is None:
        return
    require(c.command.reason_code is not None, "REASON_CODE_REQUIRED")
    require(c.command.reason_code in c.case.facts.reason_codes, "REASON_CODE_INVALID")


@register("deficiency_items_present")
def deficiency_items_present(c: Context) -> None:
    require(c.case.facts.item_refs is not None, "ITEM_CONTEXT_UNAVAILABLE")
    if c.preview and not c.command.payload.item_refs:
        return
    require(bool(c.command.payload.item_refs), "DEFICIENCY_ITEMS_REQUIRED")
    require(len(c.command.payload.item_refs) == len(set(c.command.payload.item_refs)), "DEFICIENCY_ITEMS_DUPLICATED")
    require(set(c.command.payload.item_refs) <= c.case.facts.item_refs, "DEFICIENCY_ITEM_INVALID")


@register("response_received")
def response_received(c: Context) -> None:
    require(c.case.facts.response_refs is not None, "RESPONSE_CONTEXT_UNAVAILABLE")
    if c.preview and c.command.payload.response_ref is None:
        return
    require(c.command.payload.response_ref in c.case.facts.response_refs, "RESPONSE_REQUIRED")


@register("at_last_applicable_stage")
def at_last_applicable_stage(c: Context) -> None:
    require(next_stage(c.case) is None, "NOT_LAST_APPLICABLE_STAGE")


@register("decision_authorised")
def decision_authorised(c: Context) -> None:
    require(c.case.facts.decision_refs is not None, "DECISION_CONTEXT_UNAVAILABLE")
    if c.preview and c.command.payload.decision_ref is None:
        return
    require(c.command.payload.decision_ref in c.case.facts.decision_refs, "DECISION_NOT_AUTHORISED")


@register("letter_type_matches_decision")
def letter_type_matches_decision(c: Context) -> None:
    if c.preview and c.command.payload.letter is None:
        return
    letter = c.command.payload.letter
    require(letter is not None, "LETTER_DATA_REQUIRED")
    require(c.case.facts.confirmed_letter is not None, "LETTER_CONTEXT_UNAVAILABLE")
    require(letter == c.case.facts.confirmed_letter, "LETTER_DATA_NOT_CONFIRMED")
    require(c.transition.letter is not None and letter.type == c.transition.letter["type"]
            and letter.lists_deficiencies == c.transition.letter["lists_deficiencies"], "LETTER_DECISION_MISMATCH")


@register("previous_stage_visited")
def previous_stage_visited(c: Context) -> None:
    target = c.command.payload.target_stage
    require(target is not None and target == c.transition.target and target in c.case.visited, "REVERT_TARGET_NOT_VISITED")


@register("second_approval_if_required")
def second_approval_if_required(c: Context) -> None:
    require(c.case.facts.second_approval_required is not None, "APPROVAL_POLICY_UNAVAILABLE")
    if c.case.facts.second_approval_required:
        require(c.case.facts.second_approver_refs is not None, "APPROVAL_CONTEXT_UNAVAILABLE")
        require(c.command.payload.second_approver_ref in c.case.facts.second_approver_refs, "SECOND_APPROVAL_REQUIRED")
        require(c.command.payload.second_approver_ref != c.command.actor.user_id, "SECOND_APPROVER_MUST_DIFFER")
