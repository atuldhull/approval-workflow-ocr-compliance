"""EVC scheduling commands: propose a dated run (EDF or CP-SAT) and publish it atomically."""
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.evc.pool_api import SlotPart
from app.evc.schedule_service import propose, publish
from app.evc.scheduler import SchedulerParameters
from app.platform.auth import current_principal
from app.platform.idempotency import idempotency_key, idempotent_response
from contracts.types import Principal

router = APIRouter(tags=["evc"])
Reason = Literal["NO_AVAILABILITY", "PANEL_INCOMPLETE", "COI_ONLY", "CAPACITY_EXHAUSTED"]


class ProposeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    algorithm: Literal["EDF", "CPSAT"]
    region: str | None = Field(default=None, pattern=r"^[A-Za-z][A-Za-z0-9_]*$", max_length=100)
    default_slot_capacity: StrictInt = Field(default=4, ge=1, le=50)
    expert_daily_capacity: StrictInt = Field(default=1, ge=1, le=2)
    max_lateness_days: StrictInt = Field(default=0, ge=0, le=30)
    time_limit_seconds: float = Field(default=60.0, gt=0, le=120)

    def parameters(self) -> SchedulerParameters:
        return SchedulerParameters(default_slot_capacity=self.default_slot_capacity,
                                   expert_daily_capacity=self.expert_daily_capacity,
                                   max_lateness_days=self.max_lateness_days, time_limit_seconds=self.time_limit_seconds)


class PublishBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID


class Labelled(BaseModel):
    selector_label: Literal["SIMULATED authorised selector (stand-in)"]
    simulation_status: Literal["SIMULATED"]
    source_status: Literal["DEMO_ASSUMPTION"]
    assumption_code: Literal["EVC_SCHEDULING_POLICY_UNCONFIRMED"]


class ProposedAssignment(BaseModel):
    request_id: UUID
    assignment_id: UUID
    slot_id: UUID
    date: date
    slot_part: SlotPart
    expert_ids: list[UUID]
    due_by: date
    lateness_days: int


class Unscheduled(BaseModel):
    request_id: UUID
    reason_code: Reason
    slots_considered: int
    best_qualified_count: int
    panel_size: int
    slot_reasons: dict[Reason, int]


class ProposalOut(Labelled):
    run_id: UUID
    algorithm: Literal["EDF", "CPSAT"]
    status: Literal["PROPOSED"]
    region_scope: str | None
    created_at: datetime
    parameters: dict[str, float | int]
    metrics: dict[str, float | int | bool]
    proposals: list[ProposedAssignment]
    unscheduled: list[Unscheduled]


class PublishedAssignment(Labelled):
    run_id: UUID
    algorithm: Literal["EDF", "CPSAT"]
    application_id: UUID
    request_id: UUID
    assignment_id: UUID
    slot_id: UUID
    date: date
    slot_part: SlotPart
    due_by: date
    lateness_days: int
    expert_ids: list[UUID]
    panel_role: str


class PublishOut(Labelled):
    run_id: UUID
    algorithm: Literal["EDF", "CPSAT"]
    status: Literal["PUBLISHED"]
    published_count: int
    assignments: list[PublishedAssignment]


@router.post("/evc/schedule:propose", response_model=ProposalOut, status_code=201,
             description="Choose dates/AM-PM parts for queued requests in scope (EDF greedy baseline or CP-SAT). "
             "Panels come from the SIMULATED authorised selector (stand-in); optimisation never picks experts. "
             "Writes unpublished proposals and a schedule_run, supersedes earlier drafts of the same requests and "
             "explains every unscheduled request with a coded reason. RO users are limited to their own region. "
             "Capacities and lateness allowance are DEMO ASSUMPTION parameters. Optional Idempotency-Key.")
def schedule_propose(body: ProposeBody, principal: Principal = Depends(current_principal),
                     key: str | None = Depends(idempotency_key)):
    params = body.parameters()
    return idempotent_response(principal, key, "POST", "/evc/schedule:propose", {}, body.model_dump(mode="json"),
        lambda uow: propose(uow, algorithm=body.algorithm, region=body.region, params=params),
        lambda result: ProposalOut(**result).model_dump(mode="json"), status_code=201)


@router.post("/evc/schedule:publish", response_model=PublishOut,
             description="Publish every proposal of one run in a single transaction after rechecking availability, COI, "
             "activity, panel size, slot and expert capacity. Any double booking or failed recheck returns 409 and "
             "publishes nothing. Requests become PUBLISHED, which EvcPort.status reports. Optional Idempotency-Key.")
def schedule_publish(body: PublishBody, principal: Principal = Depends(current_principal),
                     key: str | None = Depends(idempotency_key)):
    return idempotent_response(principal, key, "POST", "/evc/schedule:publish", {}, body.model_dump(mode="json"),
        lambda uow: publish(uow, body.run_id), lambda result: PublishOut(**result).model_dump(mode="json"))
