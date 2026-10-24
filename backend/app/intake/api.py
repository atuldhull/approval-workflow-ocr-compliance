from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.intake import service
from app.intake.models import Application, Institution
from app.platform.auth import current_principal
from app.platform.db import new_session, unit_of_work
from app.platform.registry import port
from contracts.enums import Role
from contracts.errors import NotFound
from contracts.ports import AuthzPort
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


def _out(a: Application) -> ApplicationOut:
    return ApplicationOut(
        id=a.id, institution_id=a.institution_id, category=a.category, academic_year=a.academic_year,
        status=a.status, current_stage=a.current_stage, ruleset_rev=a.ruleset_rev, route=a.route,
        created_at=a.created_at.isoformat(), submitted_at=a.submitted_at.isoformat() if a.submitted_at else None,
    )


@router.get("/institutions", response_model=list[InstitutionOut])
def list_institutions(principal: Principal = Depends(current_principal)):
    port(AuthzPort).check(principal, "institution.list", ResourceRef("institution"))
    with new_session() as session:
        rows = session.scalars(select(Institution).order_by(Institution.name)).all()
        return [InstitutionOut(id=i.id, name=i.name, ro_region=i.ro_region, is_demo=i.is_demo) for i in rows]


@router.post("/applications", response_model=ApplicationOut, status_code=status.HTTP_201_CREATED)
def create(body: ApplicationIn, principal: Principal = Depends(current_principal)):
    with unit_of_work(principal) as uow:
        return _out(service.create_application(uow, body.institution_id, body.category, body.academic_year))


@router.post("/applications/{application_id}/submit", response_model=ApplicationOut)
def submit(application_id: UUID, principal: Principal = Depends(current_principal)):
    with unit_of_work(principal) as uow:
        return _out(service.submit_application(uow, application_id))


@router.get("/applications", response_model=list[ApplicationOut])
def list_applications(principal: Principal = Depends(current_principal)):
    port(AuthzPort).check(principal, "application.read", ResourceRef("application"))
    with new_session() as session:
        q = select(Application).order_by(Application.created_at.desc())
        if principal.role == Role.INSTITUTION:
            q = q.where(Application.institution_id == principal.institution_id)
        return [_out(a) for a in session.scalars(q).all()]


@router.get("/applications/{application_id}", response_model=ApplicationOut)
def get_application(application_id: UUID, principal: Principal = Depends(current_principal)):
    with new_session() as session:
        a = session.get(Application, application_id)
        if a is None:
            raise NotFound("application not found")
        port(AuthzPort).check(principal, "application.read",
                              ResourceRef("application", a.id, owner_institution_id=a.institution_id))
        return _out(a)
