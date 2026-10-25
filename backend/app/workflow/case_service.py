"""Scoped reads and intake projection bridge for the P1 case API."""
from dataclasses import replace
from types import SimpleNamespace
from typing import Mapping, Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session

from app.platform.registry import port
from app.workflow import engine, guards
from app.workflow.case_api_models import ActionIn, ActionOut, CaseActionOut, CaseOut, CasePageOut
from app.workflow.commands import CaseContext, Command, WorkflowConflict, WorkflowValidationFailed
from app.workflow.models import CaseState, RouteDefinition, Ruleset
from app.workflow.storage import applications, visits
from contracts.enums import ApplicationStatus, Role, Stage
from contracts.errors import Forbidden, NotFound
from contracts.ports import AuthzPort, CasePort, RulesetPort, UnitOfWork
from contracts.types import CaseRef, Principal, ResourceRef


def scope(session: Session, application_id: UUID, principal: Principal,
          action: str = "application.read") -> tuple[CaseRef, ResourceRef]:
    case = port(CasePort).lookup(session, application_id)
    resource = ResourceRef("application", application_id, case.institution_id, case.region)
    port(AuthzPort).check(principal, action, resource)
    # Defense in depth for policy adapters that do not yet implement object scope.
    if principal.role == Role.INSTITUTION and principal.institution_id != case.institution_id:
        raise Forbidden("institution may only access its own records")
    if principal.role == Role.RO_OFFICER and (not principal.region or principal.region != case.region):
        raise Forbidden("regional officer may only access their own region")
    return case, resource


def projection(session: Session, application_id: UUID, *, lock: bool = False) -> RowMapping:
    query = select(applications).where(applications.c.id == application_id)
    if lock:
        query = query.with_for_update()
    row = session.execute(query).mappings().one_or_none()
    if row is None:
        raise NotFound("application not found")
    return row


def state_for(session: Session, app: Mapping[str, Any]) -> CaseState:
    row = session.get(CaseState, app["id"], populate_existing=True)
    if row is not None:
        return row
    key = app["ruleset_rev"]
    if key is None:
        if app["status"] != ApplicationStatus.DRAFT:
            raise WorkflowValidationFailed("RULESET_PIN_MISSING")
        key = port(RulesetPort).default_key()
    return CaseState(application_id=app["id"], route_id=app["category"], ruleset_key=key,
                     current_stage=app["current_stage"], status=app["status"], version=1)


def context_for(session: Session, row: CaseState, principal: Principal,
                resource: ResourceRef) -> tuple[CaseContext, Ruleset]:
    uow = SimpleNamespace(session=session, principal=principal)
    command = Command(application_id=row.application_id, action="list_actions", expected_version=row.version, actor=principal)
    context, metadata = engine._context(uow, row, resource, command, engine.options())
    return replace(context, facts=guards.read_facts(uow, row, command)), metadata


def available(context: CaseContext, principal: Principal) -> list[ActionOut]:
    return [ActionOut.model_validate(a, from_attributes=True) for a in engine.list_available_actions(context, principal)]


def read_case(session: Session, application_id: UUID, principal: Principal) -> CaseOut:
    case, resource = scope(session, application_id, principal)
    app = projection(session, application_id)
    row = state_for(session, app)
    context, metadata = context_for(session, row, principal, resource)
    route = session.scalar(select(RouteDefinition).where(RouteDefinition.ruleset_key == row.ruleset_key,
                                                         RouteDefinition.route_id == row.route_id))
    history = session.execute(select(visits).where(visits.c.application_id == application_id)
                              .order_by(visits.c.entered_at, visits.c.id)).mappings().all()
    source = metadata.source_metadata.get("workflow_source") or {}
    draft = row.status == ApplicationStatus.DRAFT
    return CaseOut(case_id=application_id, institution_id=case.institution_id, region=case.region,
                   stage=row.current_stage, status=row.status, version=row.version, route_id=row.route_id,
                   ruleset_key=None if draft else row.ruleset_key, preview_ruleset_key=row.ruleset_key if draft else None,
                   route=route.stage_list, clause_citation=route.clause_citation, stage_history=history,
                   available_actions=available(context, principal),
                   assumption_status="DEMO_ASSUMPTION" if source.get("status") == "demo_assumption" else None)


def list_cases(session: Session, principal: Principal, *, region: str | None = None, stage: Stage | None = None,
               status: ApplicationStatus | None = None, offset: int = 0, limit: int = 50) -> CasePageOut:
    port(AuthzPort).check(principal, "application.read", ResourceRef("application"))
    if principal.role == Role.RO_OFFICER and (not principal.region or (region and region != principal.region)):
        raise Forbidden("regional officer may only query their own region")
    # Scope and filter before pagination: no foreign IDs, counts or offsets leak.
    visible = []
    for application_id in session.scalars(select(applications.c.id).order_by(applications.c.id)):
        case = port(CasePort).lookup(session, application_id)
        if principal.role == Role.INSTITUTION and principal.institution_id != case.institution_id:
            continue
        if principal.role == Role.RO_OFFICER and principal.region != case.region:
            continue
        if region is not None and region != case.region:
            continue
        try:
            scope(session, application_id, principal)
        except Forbidden:
            continue
        row = state_for(session, projection(session, application_id))
        if stage is not None and row.current_stage != stage:
            continue
        if status is not None and row.status != status:
            continue
        visible.append(application_id)
    return CasePageOut(items=[read_case(session, key, principal) for key in visible[offset:offset + limit]],
                       total=len(visible), offset=offset, limit=limit)


def apply_action(uow: UnitOfWork, application_id: UUID, body: ActionIn) -> CaseActionOut:
    _, resource = scope(uow.session, application_id, uow.principal, f"case.{engine.canonical(body.action)}")
    app = projection(uow.session, application_id, lock=True)
    row = state_for(uow.session, app)
    if row.version != body.expected_version:
        raise WorkflowConflict("VERSION_CONFLICT")
    if row not in uow.session:
        if row.status == ApplicationStatus.DRAFT and engine.canonical(body.action) != "submit":
            raise WorkflowValidationFailed("INVALID_TRANSITION")
        uow.session.add(row)
        uow.session.flush()
    command = Command(application_id=application_id, action=body.action, expected_version=body.expected_version,
                      reason_code=body.reason_code, note_body=body.note, payload=body.payload, actor=uow.principal)
    result = engine.handle(uow, command)
    route = uow.session.scalar(select(RouteDefinition).where(RouteDefinition.ruleset_key == row.ruleset_key,
                                                             RouteDefinition.route_id == row.route_id))
    values = dict(status=result.status, current_stage=result.current_stage, ruleset_rev=result.ruleset_key,
                  route=route.stage_list)
    if engine.canonical(body.action) == "submit":
        values["submitted_at"] = uow.session.scalar(select(visits.c.entered_at).where(
            visits.c.application_id == application_id, visits.c.exited_at.is_(None)))
    uow.session.execute(update(applications).where(applications.c.id == application_id).values(**values))
    context, _ = context_for(uow.session, row, uow.principal, resource)
    return CaseActionOut(case_id=application_id, stage=result.current_stage, status=result.status, version=result.version,
                         available_actions=available(context, uow.principal),
                         opened_deadlines=[vars(d) for d in result.opened_deadlines],
                         closed_deadlines=[vars(d) for d in result.closed_deadlines], assumption_status=result.assumption_status)
