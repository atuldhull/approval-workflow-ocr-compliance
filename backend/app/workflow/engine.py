"""Pure transition planning plus a thin, rollback-safe transactional wrapper."""
from datetime import datetime, time
from dataclasses import replace
import os
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy import insert, select, update
from sqlalchemy.orm import object_session
from sqlalchemy.orm.exc import StaleDataError

from app.platform.db import unit_of_work
from app.platform.registry import port
from app.platform.settings import settings
from app.workflow import guards, deficiency
from app.workflow.commands import (
    ActionAvailability, CaseContext, ClosedDeadline, Command, Decision, OpenedDeadline, Options, Payload, Result,
    Spec, State, WorkflowConflict, WorkflowValidationFailed,
)
from app.workflow.grammar import ACTIONS, ALIASES, TERMINALS, Transition
from app.workflow.models import CaseState, RouteDefinition, Ruleset, TransitionDefinition
from app.workflow.storage import visits, applications
from contracts.enums import ApplicationStatus, ClockKind, Stage
from contracts.errors import ContractError, Forbidden, NotFound
from contracts.ports import AuthzPort, CasePort, ClockPort, CompliancePort, DeadlinePort, EvcPort, LedgerPort, NotesPort, RulesetPort, UnitOfWork
from contracts.types import Anchor, EventIn, LetterIn, Principal, ResourceRef, SubjectRef


def options() -> Options:
    enabled = os.environ.get("WF_ENABLE_LETTER_ISSUANCE", "false").lower() in {"true", "1", "yes", "on"}
    return Options(demo_mode=settings.demo_mode, enable_letter_issuance=enabled)


def parse_command(command: Command | dict) -> Command:
    try:
        return Command.model_validate(command.model_dump(warnings=False) if isinstance(command, Command) else command)
    except ValidationError as exc:
        raise WorkflowValidationFailed("INVALID_COMMAND") from exc


def canonical(action: str) -> str:
    return ALIASES.get(action, action)


def plan_transition(case: CaseContext, command: Command, config: Options, *, preview: bool = False) -> Decision:
    """No I/O, mutation, time, random values or category-specific route branches."""
    if case.state.version != command.expected_version:
        raise WorkflowConflict("VERSION_CONFLICT")
    action = canonical(command.action)
    if case.state.status in TERMINALS:
        raise WorkflowValidationFailed("INVALID_TRANSITION")
    candidates = [t for t in case.transitions if t.source == case.state.source and t.action == action]
    if not candidates:
        raise WorkflowValidationFailed("INVALID_TRANSITION")
    if command.payload.target_stage is not None and action != "revert":
        raise WorkflowValidationFailed("UNEXPECTED_TARGET_STAGE")
    current_condition = dict(case.stages).get(case.state.current_stage)
    if current_condition == "as_applicable":
        selected = case.facts.applicability.get(case.state.current_stage)
        if selected is None:
            raise WorkflowValidationFailed("APPLICABILITY_UNAVAILABLE")
        if not selected:
            raise WorkflowValidationFailed("APPLICABILITY_CONFLICT")
    allowed, failures = [], []
    for transition in sorted(candidates, key=lambda t: (t.position, t.target)):
        try:
            if dict(case.stages).get(transition.target) == "as_applicable":
                selected = case.facts.applicability.get(transition.target)
                if selected is None:
                    raise WorkflowValidationFailed("APPLICABILITY_UNAVAILABLE")
                if not selected:
                    continue
            selector = transition.definition.get("to_stage")
            if selector == "$next" and transition.target != guards.next_stage(case):
                continue
            if selector == "$previous" and command.payload.target_stage != transition.target:
                continue
            if selector == "$first" and transition.target != case.stages[0][0]:
                continue
            if transition.letter is not None and not config.enable_letter_issuance:
                raise WorkflowValidationFailed("LETTER_ISSUANCE_DISABLED")
            guards.evaluate(guards.Context(case, command, transition, preview))
            if any(timer.get("if_live") for timer in transition.timers) and case.facts.live_clock_rules is None:
                raise WorkflowValidationFailed("CLOCK_CONTEXT_UNAVAILABLE")
            allowed.append(transition)
        except WorkflowValidationFailed as exc:
            failures.append(exc)
    if len(allowed) > 1:
        raise WorkflowValidationFailed("AMBIGUOUS_TRANSITION")
    if not allowed:
        if failures:
            raise failures[0]
        raise WorkflowValidationFailed("INVALID_TRANSITION")
    transition = allowed[0]
    terminal = transition.target in TERMINALS
    return Decision(transition, ApplicationStatus(transition.target) if terminal else ApplicationStatus.IN_PROCESS,
                    None if terminal else transition.target)


def list_available_actions(case: CaseContext | CaseState, principal: Principal) -> tuple[ActionAvailability, ...]:
    """UI metadata from a pure context or an attached, authorized case model."""
    results = []
    config = options()
    if isinstance(case, CaseState):
        session = object_session(case)
        if session is None:
            raise WorkflowValidationFailed("CASE_CONTEXT_REQUIRED")
        ref = _get_port(CasePort).lookup(session, case.application_id)
        resource = ResourceRef("application", case.application_id, ref.institution_id, ref.region)
        _get_port(AuthzPort).check(principal, "application.read", resource)
        command = Command(application_id=case.application_id, action="list_actions", expected_version=case.version, actor=principal)
        uow = SimpleNamespace(session=session, principal=principal)
        context, _ = _context(uow, case, resource, command, config)
        case = replace(context, facts=guards.read_facts(uow, case, command))
    for action in sorted({t.action for t in case.transitions if t.source == case.state.source}):
        try:
            port(AuthzPort).check(principal, f"case.{action}", case.resource)
        except Forbidden:
            continue
        candidates = [t for t in case.transitions if t.source == case.state.source and t.action == action and principal.role in t.roles]
        if not candidates:
            continue
        targets, failure = [], None
        for target in sorted({t.target for t in candidates}):
            payload = Payload(target_stage=Stage(target)) if action == "revert" else Payload()
            command = Command(application_id=case.state.application_id, action=action, expected_version=case.state.version,
                              actor=principal, payload=payload)
            try:
                decision = plan_transition(case, command, config, preview=True)
                if decision.transition.target == target:
                    targets.append(target)
            except WorkflowValidationFailed as exc:
                failure = failure or exc.reason_code
        aliases = sorted({alias for t in candidates for alias in t.definition.get("aliases", [])})
        results.append(ActionAvailability(action, tuple(targets), bool(targets), None if targets else failure,
                                          any(t.reason_required for t in candidates), tuple(aliases)))
    return tuple(results)


def _spec(row: TransitionDefinition) -> Spec:
    try:
        definition = Transition.model_validate(row.definition).model_dump(mode="json")
        if row.action not in ACTIONS or row.from_stage not in ({s.value for s in Stage} | {"DRAFT"}) or row.to_stage not in ({s.value for s in Stage} | TERMINALS):
            raise WorkflowValidationFailed("INVALID_PERSISTED_TRANSITION")
        if (row.action, row.roles, row.guards, row.timers, row.letter, row.reason_codes_required, row.emits_event) != (
            definition["action"], definition["allowed_roles"], definition["guards"], definition["timers"],
            definition["letter"], definition["reason_codes_required"], definition["emits_event"],
        ):
            raise WorkflowValidationFailed("INVALID_PERSISTED_TRANSITION")
        return Spec(row.position, row.action, row.from_stage, row.to_stage, tuple(row.roles), tuple(row.guards),
                    tuple(row.timers), row.letter, row.reason_codes_required, definition, row.emits_event)
    except (ValidationError, TypeError, KeyError) as exc:
        raise WorkflowValidationFailed("INVALID_PERSISTED_TRANSITION") from exc


def _context(uow: UnitOfWork, row: CaseState, resource: ResourceRef, command: Command, config: Options) -> tuple[CaseContext, Ruleset]:
    metadata = uow.session.scalar(select(Ruleset).where(Ruleset.key == row.ruleset_key))
    route = uow.session.scalar(select(RouteDefinition).where(
        RouteDefinition.ruleset_key == row.ruleset_key, RouteDefinition.route_id == row.route_id))
    if metadata is None or route is None:
        raise WorkflowValidationFailed("PINNED_DEFINITION_MISSING")
    if metadata.demo_only and not config.demo_mode:
        raise Forbidden("DEMO_RULESET_REFUSED")
    if metadata.status not in {"APPROVED", "ACTIVE"} and not config.demo_mode:
        raise WorkflowValidationFailed("RULESET_NOT_APPROVED")
    rows = uow.session.scalars(select(TransitionDefinition).where(TransitionDefinition.route_def_id == route.id)
                               .order_by(TransitionDefinition.position, TransitionDefinition.id)).all()
    try:
        state = State(row.application_id, row.route_id, row.ruleset_key, row.current_stage, ApplicationStatus(row.status), row.version)
        stages = tuple((Stage(s["stage"]).value, s["when"]) for s in route.stage_list)
    except (ValueError, KeyError, TypeError) as exc:
        raise WorkflowValidationFailed("INVALID_PERSISTED_STATE") from exc
    if not stages:
        raise WorkflowValidationFailed("INVALID_PERSISTED_ROUTE")
    history = frozenset(uow.session.scalars(select(visits.c.stage).where(visits.c.application_id == row.application_id)).all())
    from app.workflow.commands import GuardFacts
    context = CaseContext(state, resource, stages, tuple(_spec(r) for r in rows), history, GuardFacts())
    return context, metadata


def _get_port(kind):
    try:
        return port(kind)
    except RuntimeError as exc:
        raise WorkflowValidationFailed("DEPENDENCY_UNAVAILABLE") from exc


def _timers(uow: UnitOfWork, context: CaseContext, decision: Decision, command: Command,
            now: datetime) -> tuple[tuple[OpenedDeadline, ...], tuple[ClosedDeadline, ...]]:
    opened, closed = [], []
    if not decision.transition.timers:
        return (), ()
    rules = _get_port(RulesetPort).get(context.state.ruleset_key)
    if rules.key != context.state.ruleset_key:
        raise WorkflowValidationFailed("RULESET_PIN_MISMATCH")
    deadlines = _get_port(DeadlinePort)
    subject = SubjectRef("application", context.state.application_id)
    for timer in decision.transition.timers:
        rule = rules.deadline_rules.get(timer["rule_id"])
        if rule is None:
            raise WorkflowValidationFailed("DEADLINE_RULE_MISSING")
        kind = rule.get("clock_kind") if isinstance(rule, dict) else getattr(rule, "clock_kind", None)
        if kind not in {ClockKind.LEGAL, ClockKind.INTERNAL}:
            raise WorkflowValidationFailed("DEADLINE_RULE_INVALID")
        op = timer["op"]
        if op in {"pause_internal", "resume_internal"} and kind == ClockKind.LEGAL:
            raise WorkflowConflict("LEGAL_CLOCK_CANNOT_PAUSE")
        if timer.get("if_live"):
            if context.facts.live_clock_rules is None:
                raise WorkflowValidationFailed("CLOCK_CONTEXT_UNAVAILABLE")
            if timer["rule_id"] not in context.facts.live_clock_rules:
                continue
        if op == "open":
            at = now
            if timer["anchor"] == "letter.issue_date":
                if command.payload.letter is None:
                    raise WorkflowValidationFailed("LETTER_DATA_REQUIRED")
                at = datetime.combine(command.payload.letter.issue_date, time.min, ZoneInfo("Asia/Kolkata"))
            deadline_id = deadlines.open(uow, subject, timer["rule_id"], Anchor(at=at), context.state.ruleset_key)
            opened.append(OpenedDeadline(deadline_id, timer["rule_id"]))
        elif op == "close":
            deadlines.close(uow, subject, timer["rule_id"], timer["outcome"])
            closed.append(ClosedDeadline(subject.id, timer["rule_id"], timer["outcome"]))
        elif op == "pause_internal":
            deadlines.pause_internal(uow, subject, timer["rule_id"])
        elif op == "resume_internal":
            deadlines.resume_internal(uow, subject, timer["rule_id"])
        else:
            raise WorkflowValidationFailed("INVALID_TIMER_OPERATION")
    return tuple(opened), tuple(closed)


def _handle(uow: UnitOfWork, command: Command) -> Result:
    # This scope-only port lookup does not load case_state or mutate anything.
    case_ref = _get_port(CasePort).lookup(uow.session, command.application_id)
    resource = ResourceRef("application", command.application_id, case_ref.institution_id, case_ref.region)
    _get_port(AuthzPort).check(uow.principal, f"case.{canonical(command.action)}", resource)
    if command.actor != uow.principal:
        raise Forbidden("ACTOR_MISMATCH")
    row = uow.session.get(CaseState, command.application_id, with_for_update=True, populate_existing=True)
    if row is None:
        raise NotFound("case state not found")
    if row.version != command.expected_version:
        raise WorkflowConflict("VERSION_CONFLICT")
    config = options()
    context, metadata = _context(uow, row, resource, command, config)
    if context.state.status in TERMINALS or not any(t.source == context.state.source and t.action == canonical(command.action)
                                                   for t in context.transitions):
        raise WorkflowValidationFailed("INVALID_TRANSITION")
    context = replace(context, facts=guards.read_facts(uow, row, command))
    decision = plan_transition(context, command, config)
    expected_event = "wf.application_submitted" if decision.transition.action == "submit" else "wf.transition_applied"
    if decision.transition.emits_event != expected_event:
        raise WorkflowValidationFailed("EVENT_SCHEMA_UNSUPPORTED")
    note_ref, note_hash = None, None
    if command.note_body:
        note_ref, note_hash = _get_port(NotesPort).create(uow, command.note_body)
    now = _get_port(ClockPort).now()
    if now.tzinfo is None or now.utcoffset() is None:
        raise WorkflowValidationFailed("CLOCK_MUST_BE_AWARE")
    current = uow.session.execute(select(visits).where(visits.c.application_id == row.application_id,
                                                      visits.c.exited_at.is_(None)).with_for_update()).mappings().all()
    if context.state.source == "DRAFT":
        if current:
            raise WorkflowConflict("STAGE_VISIT_CONFLICT")
    elif len(current) != 1 or current[0]["stage"] != context.state.current_stage:
        raise WorkflowConflict("STAGE_VISIT_CONFLICT")
    next_version = row.version + 1
    if current:
        if now < current[0]["entered_at"]:
            raise WorkflowConflict("CLOCK_BEFORE_STAGE_ENTRY")
        uow.session.execute(update(visits).where(visits.c.id == current[0]["id"]).values(
            exited_at=now, outcome=decision.transition.action.upper(), reason_code=command.reason_code, note_ref=note_ref))
    new_visit = None
    if decision.current_stage is not None:
        new_visit = uuid5(NAMESPACE_URL, f"sih26262:wf:stage:{row.application_id}:{next_version}:{decision.current_stage}")
        uow.session.execute(insert(visits).values(id=new_visit, application_id=row.application_id, stage=decision.current_stage,
                                                 entered_at=now, exited_at=None, outcome=None, reason_code=command.reason_code, note_ref=note_ref))
    row.current_stage, row.status, row.version = decision.current_stage, decision.status, next_version
    if decision.transition.action == "submit":
        uow.session.execute(update(applications).where(applications.c.id == row.application_id)
                            .values(dsc_present=context.facts.dsc_present))
    uow.session.flush()
    deficiency_common = dict(aggregate_type="application", aggregate_id=row.application_id, reason_code=command.reason_code,
                             ruleset_rev=row.ruleset_key, note_ref=note_ref, note_hash=note_hash)
    deficiency_events = deficiency.apply(uow, row, command, now, deficiency_common)
    evc_config = metadata.source_metadata.get("evc")
    if evc_config is None and "EVC" in (context.state.current_stage, decision.current_stage):
        raise WorkflowValidationFailed("EVC_CONFIG_UNAVAILABLE")
    if evc_config is not None:
        evc = _get_port(EvcPort)
        kwargs = dict(ruleset_key=row.ruleset_key, rule_id=evc_config["rule_id"], action=decision.transition.action)
        if context.state.current_stage != "EVC" and decision.current_stage == "EVC":
            evc.enter(uow, case_ref, category=row.route_id, stage_visit_id=new_visit, anchor=Anchor(at=now), **kwargs)
        elif context.state.current_stage == "EVC" and (decision.current_stage != "EVC" or decision.transition.action == "complete_evc"):
            if evc.status(uow.session, row.application_id) != "DONE":
                if decision.transition.action in {"reject", "withdraw", "revert"}:
                    evc.cancel(uow, case_ref, reason_code=command.reason_code, **kwargs)
                else:
                    evc.complete(uow, case_ref, **kwargs)
    opened, closed = _timers(uow, context, decision, command, now)
    letter_ref = None
    if decision.transition.letter is not None:
        letter = command.payload.letter
        if letter is None:
            raise WorkflowValidationFailed("LETTER_DATA_REQUIRED")
        letter_ref = _get_port(CompliancePort).register_letter(uow, LetterIn(
            application_id=row.application_id, institution_id=case_ref.institution_id, letter_type=letter.type,
            academic_year=letter.academic_year, issue_date=letter.issue_date, issue_date_source=letter.issue_date_source,
            lists_deficiencies=letter.lists_deficiencies, issue_date_fact_id=letter.issue_date_fact_id,
            document_version_id=letter.document_version_id,
        ))
    common = dict(aggregate_type="application", aggregate_id=row.application_id, reason_code=command.reason_code,
                  ruleset_rev=row.ruleset_key, note_ref=note_ref, note_hash=note_hash)
    ledger = _get_port(LedgerPort)
    payload = dict(application_id=row.application_id, action=decision.transition.action,
                   from_state=context.state.source, to_state=decision.transition.target,
                   from_version=context.state.version, to_version=row.version,
                   from_status=context.state.status, to_status=decision.status, ruleset_rev=row.ruleset_key, letter_ref=letter_ref)
    event_type = decision.transition.emits_event
    if decision.transition.action == "submit":
        event_type = "wf.application_submitted"
        payload = dict(application_id=row.application_id, institution_id=case_ref.institution_id, category=row.route_id,
                       ruleset_rev=row.ruleset_key, first_stage=decision.current_stage, route=[s for s, _ in context.stages],
                       dsc_present=context.facts.dsc_present, provided_item_keys=list(context.facts.provided_item_keys))
    event_version = 2 if decision.transition.action == "submit" else 1
    seqs = [ledger.append(uow, EventIn(event_type=event_type, event_version=event_version, payload=payload, **common))]
    seqs.extend(ledger.append(uow, event) for event in deficiency_events)
    if current:
        seqs.append(ledger.append(uow, EventIn(event_type="wf.stage_exited", payload=dict(
            application_id=row.application_id, stage_visit_id=current[0]["id"], stage=current[0]["stage"],
            exited_at=now.isoformat(), outcome=decision.transition.action.upper(), version=row.version), **common)))
    if new_visit is not None:
        seqs.append(ledger.append(uow, EventIn(event_type="wf.stage_entered", payload=dict(
            application_id=row.application_id, stage_visit_id=new_visit, stage=decision.current_stage,
            entered_at=now.isoformat(), version=row.version), **common)))
    assumption = metadata.source_metadata.get("workflow_source") or {}
    return Result(row.application_id, row.route_id, row.ruleset_key, row.current_stage, ApplicationStatus(row.status), row.version,
                  tuple(seqs), letter_ref, "DEMO_ASSUMPTION" if assumption.get("status") == "demo_assumption" else None,
                  opened, closed)


def handle(uow: UnitOfWork, command: Command | dict) -> Result:
    """Caller owns commit; any failure rolls back the entire command transaction."""
    try:
        return _handle(uow, parse_command(command))
    except StaleDataError as exc:
        uow.session.rollback()
        raise WorkflowConflict("VERSION_CONFLICT") from exc
    except BaseException:
        uow.session.rollback()
        raise


def execute(command: Command | dict) -> Result:
    """Internal entry point; actor must already be resolved by trusted P3 auth."""
    command = parse_command(command)
    with unit_of_work(command.actor) as uow:
        return handle(uow, command)
