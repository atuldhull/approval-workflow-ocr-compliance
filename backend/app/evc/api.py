"""Role-scoped EVC queue. Scheduling/publishing remain separate commands."""
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.evc.models import EvcRequest
from app.evc.service import duration
from app.platform.auth import current_principal
from app.platform.db import new_session
from app.platform.registry import port
from contracts.enums import Role
from contracts.errors import Conflict, Forbidden, ValidationFailed
from contracts.ports import AuthzPort, CasePort, ClockPort
from contracts.types import Principal, ResourceRef

router = APIRouter(tags=["evc"])
RequestStatus = Literal["QUEUED", "PROPOSED", "PUBLISHED", "DONE", "CANCELLED"]


class QueueItem(BaseModel):
    id: UUID
    application_id: UUID
    institution_ref: UUID
    region: str
    category: str
    requested_at: datetime
    earliest_date: date
    due_by: date
    status: RequestStatus
    priority_key: str
    ruleset_key: str
    rule_id: str
    deadline_ref: UUID
    closed_at: datetime | None
    days_waiting: int
    duration_days: int
    source_status: Literal["DEMO_ASSUMPTION"] = "DEMO_ASSUMPTION"
    assumption_code: Literal["EVC_DURATION_UNCONFIRMED"] = "EVC_DURATION_UNCONFIRMED"


class QueuePage(BaseModel):
    items: list[QueueItem]
    total: int
    offset: int
    limit: int


@router.get("/evc/queue", response_model=QueuePage, description="Role-scoped queue/history. from/to inclusively filter due_by dates. "
            "days_waiting counts whole elapsed 24-hour periods, stopped at completion/cancellation. EVC duration is a DEMO ASSUMPTION.")
def queue(region: str | None = Query(default=None, min_length=1, max_length=100), status: RequestStatus | None = None,
          from_date: date | None = Query(default=None, alias="from"), to_date: date | None = Query(default=None, alias="to"),
          offset: int = Query(default=0, ge=0), limit: int = Query(default=50, ge=1, le=100),
          principal: Principal = Depends(current_principal)):
    port(AuthzPort).check(principal, "application.read", ResourceRef("application"))
    if principal.role == Role.RO_OFFICER and (not principal.region or region not in (None, principal.region)):
        raise Forbidden("regional officer may only query their own region")
    if from_date and to_date and from_date > to_date:
        raise ValidationFailed("EVC_DATE_RANGE_INVALID")
    now = port(ClockPort).now()
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValidationFailed("EVC_CLOCK_MUST_BE_AWARE")
    with new_session() as session:
        query = select(EvcRequest).order_by(EvcRequest.due_by, EvcRequest.priority_key, EvcRequest.requested_at, EvcRequest.id)
        if status:
            query = query.where(EvcRequest.status == status)
        if from_date:
            query = query.where(EvcRequest.due_by >= from_date)
        if to_date:
            query = query.where(EvcRequest.due_by <= to_date)
        visible = []
        for row in session.scalars(query):
            case = port(CasePort).lookup(session, row.application_id)
            if principal.role == Role.INSTITUTION and case.institution_id != principal.institution_id:
                continue
            if principal.role == Role.RO_OFFICER and case.region != principal.region:
                continue
            if region is not None and case.region != region:
                continue
            port(AuthzPort).check(principal, "application.read", ResourceRef("application", case.application_id,
                case.institution_id, case.region))
            visible.append((row, case))
        items = []
        for row, case in visible[offset:offset + limit]:
            if not row.ruleset_key or not row.rule_id or not row.deadline_ref or case.institution_id != row.institution_ref:
                raise Conflict("EVC_REQUEST_METADATA_UNAVAILABLE")
            if now < row.requested_at:
                raise Conflict("EVC_CLOCK_BEFORE_REQUEST")
            stop = min(now, row.closed_at) if row.closed_at else now
            items.append(QueueItem(**{name: getattr(row, name) for name in (
                "id", "application_id", "institution_ref", "category", "requested_at", "earliest_date", "due_by", "status",
                "priority_key", "ruleset_key", "rule_id", "deadline_ref", "closed_at")}, region=case.region,
                days_waiting=int((stop - row.requested_at).total_seconds() // 86400), duration_days=duration(row.ruleset_key, row.rule_id)))
        return QueuePage(items=items, total=len(visible), offset=offset, limit=limit)
