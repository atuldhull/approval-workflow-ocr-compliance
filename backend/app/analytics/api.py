from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.analytics.reports import REPORT_TYPES, ocel_export, pendency, report
from app.analytics.scorecard import scorecard
from app.analytics.service import dashboard
from app.platform.auth import current_principal
from app.platform.registry import port
from contracts.enums import Role
from contracts.errors import NotFound
from contracts.ports import AuthzPort
from contracts.types import Principal, ResourceRef

router = APIRouter()
analytics = APIRouter(prefix="/analytics", tags=["analytics"])
REGION = Query(default=None, pattern=r"^[A-Za-z][A-Za-z -]{0,39}$")


def _scoped_region(principal: Principal, region: str | None) -> str | None:
    """A regional officer always gets their own region unless they name one (which the policy then checks)."""
    return principal.region if principal.role == Role.RO_OFFICER and region is None else region


@analytics.get("/dashboard")
def get_dashboard(region: str | None = REGION, principal: Principal = Depends(current_principal)):
    """National view for bureau, committee and audit roles; a regional officer always gets their own region."""
    region = _scoped_region(principal, region)
    port(AuthzPort).check(principal, "analytics.dashboard", ResourceRef("analytics", region=region))
    return dashboard(region)


@analytics.get("/scorecard")
def get_scorecard(principal: Principal = Depends(current_principal)):
    port(AuthzPort).check(principal, "analytics.scorecard", ResourceRef("analytics"))
    return scorecard()


@router.get("/dashboards/pendency", tags=["reports"])
def get_pendency(region: str | None = REGION, principal: Principal = Depends(current_principal)):
    """Applications in process by regional office and stage, with the ledger head and a snapshot hash."""
    region = _scoped_region(principal, region)
    port(AuthzPort).check(principal, "analytics.report", ResourceRef("analytics", region=region))
    return pendency(region)


@router.get("/reports/{report_type}", tags=["reports"])
def get_report(report_type: str, region: str | None = REGION, principal: Principal = Depends(current_principal)):
    region = _scoped_region(principal, region)
    port(AuthzPort).check(principal, "analytics.report", ResourceRef("analytics", region=region))
    if report_type not in REPORT_TYPES:
        raise NotFound(f"unknown report type; available: {', '.join(sorted(REPORT_TYPES))}")
    return report(report_type, region)


class ExportIn(BaseModel):
    format: str = Field(pattern="^ocel2$", description="OCEL 2.0 JSON; the only format so far.")


@router.post("/exports", tags=["reports"])
def create_export(body: ExportIn, principal: Principal = Depends(current_principal)):
    """The whole event log as OCEL 2.0, national scope, for oversight roles. No payloads or personal references."""
    port(AuthzPort).check(principal, "analytics.export", ResourceRef("analytics"))
    return ocel_export()


router.include_router(analytics)
