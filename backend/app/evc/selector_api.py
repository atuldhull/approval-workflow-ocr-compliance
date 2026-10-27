"""Read-only API for the SIMULATED authorised selector (stand-in)."""
from datetime import date as DateValue
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.evc.models import EvcRequest
from app.evc.pool import authorize
from app.evc.selector import PanelSelection, select_panel
from app.evc.selector_service import selector_request
from app.platform.auth import current_principal
from app.platform.db import new_session
from app.platform.registry import port
from contracts.enums import Role
from contracts.errors import Forbidden, NotFound
from contracts.ports import AuthzPort, CasePort
from contracts.types import Principal, ResourceRef

router = APIRouter(tags=["evc"])


@router.get("/evc/requests/{id}/panel-preview", response_model=PanelSelection,
            description="SIMULATED authorised selector (stand-in). Read-only DEMO ranking, not a panel appointment or reservation. "
            "Returns exactly N experts or an explained shortage. Ordered criteria: eligibility, expertise, workload, rotation, UUID. "
            "RO readers require their own case and SAME_REGION policy; cross-region preview requires a global pool-reader role.")
def panel_preview(id: UUID, on_date: DateValue = Query(alias="date"), slot_part: Literal["AM", "PM"] = Query(),
                  principal: Principal = Depends(current_principal)) -> PanelSelection:
    authorize(principal, "evc.expert.read")
    with new_session() as session:
        row = session.get(EvcRequest, id)
        if row is None:
            raise NotFound("EVC_REQUEST_NOT_FOUND")
        case = port(CasePort).lookup(session, row.application_id)
        port(AuthzPort).check(principal, "case.timeline", ResourceRef("application", case.application_id,
                              case.institution_id, case.region))
        request = selector_request(session, id)
        if principal.role == Role.RO_OFFICER and request.eligibility.policy.region_rule != "SAME_REGION":
            raise Forbidden("SELECTOR_CROSS_REGION_SCOPE_FORBIDDEN")
        return select_panel(request, on_date, slot_part)
