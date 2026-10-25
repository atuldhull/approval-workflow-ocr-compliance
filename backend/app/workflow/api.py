from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel

from app.platform.auth import current_principal
from app.platform.db import new_session, unit_of_work
from app.platform.registry import port
from app.workflow.loader import sync_at_startup
from app.workflow import case_service
from app.workflow.case_api_models import ActionIn, CaseActionOut, CaseOut, CasePageOut, ERROR_RESPONSES
from contracts.enums import ApplicationStatus, Stage
from contracts.ports import AuthzPort, RulesetPort
from contracts.types import Principal, ResourceRef

router = APIRouter()
router.add_event_handler("startup", sync_at_startup)


class StageOut(BaseModel):
    stage: str
    when: str


class RouteOut(BaseModel):
    category: str
    label: str
    stages: list[StageOut]


class RulesetOut(BaseModel):
    key: str
    status: str
    banner: str | None
    is_default: bool
    routes: list[RouteOut]


@router.get("/rulesets/{key}", response_model=RulesetOut, tags=["rulesets"])
def get_ruleset(key: str, principal: Principal = Depends(current_principal)):
    port(AuthzPort).check(principal, "ruleset.read", ResourceRef("ruleset"))
    registry = port(RulesetPort)
    rs = registry.get(key)
    return RulesetOut(
        key=rs.key, status=rs.status, banner=rs.banner, is_default=rs.key == registry.default_key(),
        routes=[RouteOut(category=r.category, label=r.label,
                         stages=[StageOut(stage=s.stage, when=s.when) for s in r.stages])
                for r in rs.routes.values()],
    )


@router.get("/rulesets", response_model=list[str], tags=["rulesets"])
def list_rulesets(principal: Principal = Depends(current_principal)):
    port(AuthzPort).check(principal, "ruleset.read", ResourceRef("ruleset"))
    return port(RulesetPort).available()


@router.post("/cases/{application_id}/actions", response_model=CaseActionOut, tags=["cases"], responses=ERROR_RESPONSES,
             description="Apply one versioned action atomically. Idempotency-Key is accepted for future P3 middleware; "
                         "this handler does not cache/replay responses. Reusing a consumed expected_version returns 409. "
                         "Guard facts must come from trusted server providers; unavailable facts reject the action.")
def case_action(application_id: UUID, body: ActionIn,
                idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", min_length=1, max_length=200,
                    description="Reserved for P3 idempotency middleware; not enforced by this handler."),
                principal: Principal = Depends(current_principal)):
    with unit_of_work(principal) as uow:
        return case_service.apply_action(uow, application_id, body)


@router.get("/cases", response_model=CasePageOut, tags=["cases"], responses=ERROR_RESPONSES)
def cases(region: str | None = Query(default=None, min_length=1, max_length=100), stage: Stage | None = None,
          status: ApplicationStatus | None = None, offset: int = Query(default=0, ge=0),
          limit: int = Query(default=50, ge=1, le=100), principal: Principal = Depends(current_principal)):
    with new_session() as session:
        return case_service.list_cases(session, principal, region=region, stage=stage, status=status, offset=offset, limit=limit)


@router.get("/cases/{application_id}", response_model=CaseOut, tags=["cases"], responses=ERROR_RESPONSES)
def case_detail(application_id: UUID, principal: Principal = Depends(current_principal)):
    with new_session() as session:
        return case_service.read_case(session, application_id, principal)
