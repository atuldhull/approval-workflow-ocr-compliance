from uuid import UUID

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.intake import service
from app.intake.models import Application, Institution
from app.intake.rules import SubmissionBlocked, plan
from app.intake.shapes import (ApplicationChecklistOut, ItemIn, ItemsIn, ItemsOut, SubmissionIn, SubmissionErrorOut,
                                SubmissionInputErrorOut)
from app.platform.auth import current_principal
from app.platform.db import new_session
from app.platform.idempotency import idempotency_key, idempotent_response
from app.platform.registry import port
from contracts.enums import Role
from contracts.errors import Forbidden, NotFound
from contracts.ports import AuthzPort, CasePort
from contracts.types import Principal, ResourceRef

router = APIRouter(tags=["applications"])


class InstitutionOut(BaseModel):
    id: UUID
    name: str
    ro_region: str
    is_demo: bool


class ApplicationIn(BaseModel):
    institution_id: UUID
    category: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    academic_year: str = Field(pattern=r"^[0-9]{4}-[0-9]{2}$")
    items: list[ItemIn] = Field(default_factory=list)
    submit: bool = Field(default=False, strict=True, description="Create and submit in one transaction when true.")
    dsc_present: bool = Field(default=False, strict=True)


class ApplicationOut(BaseModel):
    id: UUID
    institution_id: UUID
    category: str
    academic_year: str
    status: str
    current_stage: str | None
    ruleset_rev: str | None
    route: list[dict] | None
    created_at: str
    submitted_at: str | None
    dsc_present: bool


class SubmissionOut(ApplicationOut):
    route_id: str
    stages: list[dict]
    clause_citation: dict
    ruleset_key: str
    assumptions: list[str]


def _out(a: Application) -> ApplicationOut:
    return ApplicationOut(
        id=a.id, institution_id=a.institution_id, category=a.category, academic_year=a.academic_year,
        status=a.status, current_stage=a.current_stage, ruleset_rev=a.ruleset_rev, route=a.route,
        created_at=a.created_at.isoformat(), submitted_at=a.submitted_at.isoformat() if a.submitted_at else None,
        dsc_present=a.dsc_present,
    )


def _submitted(a: Application, session) -> SubmissionOut:
    route = plan(session, a.category, a.ruleset_rev)
    return SubmissionOut(**_out(a).model_dump(), route_id=route.route_id, stages=route.stages,
                         clause_citation=route.clause_citation, ruleset_key=route.ruleset_key, assumptions=route.assumptions)


def _blocked(exc: SubmissionBlocked) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": "ValidationFailed", "detail": exc.reason_code,
        "reason_code": exc.reason_code, "missing_item_keys": list(exc.missing_item_keys)})


@router.get("/institutions", response_model=list[InstitutionOut])
def list_institutions(principal: Principal = Depends(current_principal)):
    port(AuthzPort).check(principal, "institution.list", ResourceRef("institution"))
    with new_session() as session:
        rows = session.scalars(select(Institution).order_by(Institution.name)).all()
        return [InstitutionOut(id=i.id, name=i.name, ro_region=i.ro_region, is_demo=i.is_demo) for i in rows]


IDEMPOTENT = "Optional Idempotency-Key: same key and body replays (Idempotent-Replayed: true), a different body is 422."


def _json(model: BaseModel):
    return model.model_dump(mode="json")


@router.post("/applications", response_model=SubmissionOut | ApplicationOut, status_code=status.HTTP_201_CREATED,
             responses={422: {"model": SubmissionErrorOut | SubmissionInputErrorOut}}, description=IDEMPOTENT)
def create(body: ApplicationIn, principal: Principal = Depends(current_principal),
           key: str | None = Depends(idempotency_key)):
    def command(uow):
        app = service.create_application(uow, body.institution_id, body.category, body.academic_year)
        if body.items:
            service.mark_items(uow, app.id, body.items)
        if body.submit:
            app = service.submit_application(uow, app.id, dsc_present=body.dsc_present)
            return _submitted(app, uow.session)
        return _out(app)
    try:
        return idempotent_response(principal, key, "POST", "/applications", {}, body.model_dump(mode="json"),
                                   command, _json, status_code=status.HTTP_201_CREATED)
    except SubmissionBlocked as exc:
        return _blocked(exc)


@router.post("/applications/{application_id}/submit", response_model=SubmissionOut,
             responses={422: {"model": SubmissionErrorOut | SubmissionInputErrorOut}}, description=IDEMPOTENT)
def submit(application_id: UUID, body: SubmissionIn | None = None, principal: Principal = Depends(current_principal),
           key: str | None = Depends(idempotency_key)):
    def command(uow):
        app = service.submit_application(uow, application_id, dsc_present=body.dsc_present if body else False)
        return _submitted(app, uow.session)
    try:
        return idempotent_response(principal, key, "POST", "/applications/{application_id}/submit",
            {"application_id": str(application_id)}, body.model_dump(mode="json") if body else None, command, _json)
    except SubmissionBlocked as exc:
        return _blocked(exc)


@router.post("/applications/{application_id}/items", response_model=ItemsOut, description=IDEMPOTENT)
def provide_items(application_id: UUID, body: ItemsIn, principal: Principal = Depends(current_principal),
                  key: str | None = Depends(idempotency_key)):
    return idempotent_response(principal, key, "POST", "/applications/{application_id}/items",
        {"application_id": str(application_id)}, body.model_dump(mode="json"),
        lambda uow: service.mark_items(uow, application_id, body.items), _json)


@router.get("/applications", response_model=list[ApplicationOut])
def list_applications(principal: Principal = Depends(current_principal)):
    port(AuthzPort).check(principal, "application.read", ResourceRef("application"))
    with new_session() as session:
        q = select(Application).order_by(Application.created_at.desc())
        if principal.role == Role.INSTITUTION:
            q = q.where(Application.institution_id == principal.institution_id)
        return [_out(a) for a in session.scalars(q).all()]


@router.get("/applications/{application_id}", response_model=ApplicationOut,
            description="One application, scoped like the case: institutions their own, regional officers their region.")
def get_application(application_id: UUID, principal: Principal = Depends(current_principal)):
    with new_session() as session:
        a = session.get(Application, application_id)
        if a is None:
            raise NotFound("application not found")
        case = port(CasePort).lookup(session, application_id)
        port(AuthzPort).check(principal, "application.read",
                              ResourceRef("application", a.id, owner_institution_id=a.institution_id, region=case.region))
        if principal.role == Role.RO_OFFICER and (not principal.region or principal.region != case.region):
            raise Forbidden("regional officer may only access their own region")
        return _out(a)


@router.get("/applications/{application_id}/checklist", response_model=ApplicationChecklistOut,
            description="Read-only checklist for this application with the state of each item, against its pinned "
                        "ruleset (the default ruleset while it is a draft). Items are DEMO ASSUMPTION stand-ins.")
def application_checklist(application_id: UUID, principal: Principal = Depends(current_principal)):
    with new_session() as session:
        return service.checklist(session, principal, application_id)
