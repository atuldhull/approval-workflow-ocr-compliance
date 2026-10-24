from fastapi import APIRouter, Depends, Query

from app.analytics.scorecard import scorecard
from app.analytics.service import dashboard
from app.platform.auth import current_principal
from app.platform.registry import port
from contracts.enums import Role
from contracts.ports import AuthzPort
from contracts.types import Principal, ResourceRef

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/dashboard")
def get_dashboard(region: str | None = Query(default=None, pattern=r"^[A-Za-z][A-Za-z -]{0,39}$"),
                  principal: Principal = Depends(current_principal)):
    """National view for bureau, committee and audit roles; a regional officer always gets their own region."""
    if principal.role == Role.RO_OFFICER and region is None:
        region = principal.region
    port(AuthzPort).check(principal, "analytics.dashboard", ResourceRef("analytics", region=region))
    return dashboard(region)


@router.get("/scorecard")
def get_scorecard(principal: Principal = Depends(current_principal)):
    port(AuthzPort).check(principal, "analytics.scorecard", ResourceRef("analytics"))
    return scorecard()
