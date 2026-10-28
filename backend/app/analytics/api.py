from fastapi import APIRouter, Depends, Header, Path, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.analytics.reports import REPORT_TYPES, catalogue, ocel_export, pendency, report, to_csv
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


@router.get("/reports", tags=["reports"])
def list_reports(principal: Principal = Depends(current_principal)):
    """The report types this deployment offers, with their titles, columns and what each is computed from."""
    port(AuthzPort).check(principal, "analytics.report", ResourceRef("analytics", region=_scoped_region(principal, None)))
    return catalogue()


@router.get("/reports/{report_type}", tags=["reports"],
            responses={200: {"content": {"application/json": {}, "text/csv": {}},
                             "description": "the report as JSON, or as CSV with format=csv or Accept: text/csv"}})
def get_report(report_type: str = Path(description="One of: " + ", ".join(sorted(REPORT_TYPES)) + "."),
               region: str | None = REGION,
               format: str | None = Query(default=None, pattern="^(json|csv)$",
                                          description="csv for a download; the default is JSON"),
               accept: str | None = Header(default=None, include_in_schema=False),
               principal: Principal = Depends(current_principal)):
    """A report scoped like pendency: national for oversight roles, a regional officer's own region otherwise.
    Every report states the ledger head it was computed from and a snapshot hash of its body."""
    region = _scoped_region(principal, region)
    port(AuthzPort).check(principal, "analytics.report", ResourceRef("analytics", region=region))
    if report_type not in REPORT_TYPES:
        raise NotFound(f"unknown report type; available: {', '.join(sorted(REPORT_TYPES))}")
    body = report(report_type, region)
    if format == "csv" or (format is None and "text/csv" in (accept or "")):
        name = f"{report_type}-{(region or 'all').replace(' ', '-').lower()}-{body['ledger_head']['seq']}.csv"
        return Response(to_csv(body), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}"',
                                 "X-Snapshot-Hash": body["snapshot_hash"]})
    return body


class ExportIn(BaseModel):
    format: str = Field(pattern="^ocel2$", description="OCEL 2.0 JSON; the only format so far.")


@router.post("/exports", tags=["reports"])
def create_export(body: ExportIn, principal: Principal = Depends(current_principal)):
    """The whole event log as OCEL 2.0, national scope, for oversight roles. No payloads or personal references."""
    port(AuthzPort).check(principal, "analytics.export", ResourceRef("analytics"))
    return ocel_export()


router.include_router(analytics)
