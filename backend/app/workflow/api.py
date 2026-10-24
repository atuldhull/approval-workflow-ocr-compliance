from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.platform.auth import current_principal
from app.platform.registry import port
from app.workflow.loader import sync_at_startup
from contracts.ports import AuthzPort, RulesetPort
from contracts.types import Principal, ResourceRef

router = APIRouter(tags=["rulesets"])
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


@router.get("/rulesets/{key}", response_model=RulesetOut)
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


@router.get("/rulesets", response_model=list[str])
def list_rulesets(principal: Principal = Depends(current_principal)):
    port(AuthzPort).check(principal, "ruleset.read", ResourceRef("ruleset"))
    return port(RulesetPort).available()
