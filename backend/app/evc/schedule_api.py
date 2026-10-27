"""EVC scheduling commands: propose a dated run (EDF baseline or CP-SAT), publish it atomically or discard it."""
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from app.evc.pool_api import SlotPart
from app.evc.schedule_service import discard, propose, publish
from app.evc.scheduler_edf import MAX_SLOT_DAYS, ScheduleCommand
from app.platform.auth import current_principal
from app.platform.idempotency import idempotency_key, idempotent_response
from contracts.types import Principal

router = APIRouter(tags=["evc"])
Algorithm = Literal["EDF", "CPSAT"]
ExplanationCode = Literal["NO_AVAILABILITY", "PANEL_INCOMPLETE", "COI_ONLY", "CAPACITY_EXHAUSTED", "EXPERT_DAILY_CAP",
                          "NO_FEASIBLE_SLOT"]


class ProposeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    algorithm: Algorithm = "EDF"
    horizon_start: date
    horizon_end: date
    region: str | None = Field(default=None, pattern=r"^[A-Za-z][A-Za-z0-9_]*$", max_length=100)
    slot_capacity: StrictInt | None = Field(default=None, ge=1, le=50)

    @model_validator(mode="after")
    def bounded_horizon(self):
        if not 0 <= (self.horizon_end - self.horizon_start).days < MAX_SLOT_DAYS:
            raise ValueError(f"horizon_end must be on or after horizon_start and within {MAX_SLOT_DAYS} days")
        return self

    def command(self) -> ScheduleCommand:
        return ScheduleCommand(self.run_id, self.horizon_start, self.horizon_end, self.region, self.algorithm, self.slot_capacity)


class PublishBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID


class DiscardBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID


class Labelled(BaseModel):
    selector_label: Literal["SIMULATED authorised selector (stand-in)"]
    simulation_status: Literal["SIMULATED"]
    source_status: Literal["DEMO_ASSUMPTION"]
    assumption_code: Literal["EDF_PLANNING_UNCONFIRMED"]


class Metrics(BaseModel):
    queue_count: int
    scheduled: int
    unscheduled: int
    late_count: int
    total_lateness: int
    max_lateness: int
    total_waiting: int
    hard_constraint_violations: int
    lateness_days: list[int | None]


class SolverOut(BaseModel):
    solver_status: int
    objective_value: int
    best_bound: int
    repair_rounds: int
    candidate_count: int
    edf_scheduled: int
    fallback_to_edf: bool
    candidate_slots: int = Field(description="Pinned expert_pool.scheduler.cpsat_candidate_slots: earliest feasible slots "
                                 "modelled per request, plus EDF's own (DEMO ASSUMPTION).")


class ProposedAssignment(BaseModel):
    application_id: UUID
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
    reason_code: Literal["NO_FEASIBLE_SLOT"] = Field(description="Shared umbrella reason for every unscheduled request.")
    explanation_code: ExplanationCode = Field(description="Specific cause judged against the final plan: NO_AVAILABILITY, "
        "PANEL_INCOMPLETE, COI_ONLY, CAPACITY_EXHAUSTED (slot capacity or expert time taken), EXPERT_DAILY_CAP, or "
        "NO_FEASIBLE_SLOT when no slot exists in the window or no specific cause applies.")


class ProposalOut(Labelled):
    run_id: UUID
    algorithm: Algorithm
    status: Literal["PROPOSED"]
    region_scope: str | None
    horizon_start: date
    horizon_end: date
    created_at: datetime
    input_fingerprint: str
    metrics: Metrics
    expert_daily_cap: int = Field(description="Pinned expert_pool.scheduler.expert_daily_cap used for this run "
                                  "(visits per expert per date, DEMO ASSUMPTION).")
    solver: SolverOut | None
    proposals: list[ProposedAssignment]
    unscheduled: list[Unscheduled]


class PublishedAssignment(BaseModel):
    application_id: UUID
    request_id: UUID
    assignment_id: UUID
    run_id: UUID
    algorithm: Algorithm
    slot_id: UUID
    date: date
    slot_part: SlotPart
    due_by: date
    lateness_days: int
    expert_ids: list[UUID]
    panel_role: str
    ruleset_key: str
    request_status: Literal["PUBLISHED"]
    simulation_status: Literal["SIMULATED"]
    selector_policy_version: Literal["DEMO_SELECTOR_V1"]
    source_status: Literal["DEMO_ASSUMPTION"]


class PublishOut(Labelled):
    run_id: UUID
    algorithm: Algorithm
    status: Literal["PUBLISHED"]
    published_count: int
    assignments: list[PublishedAssignment]


class WithdrawnAssignment(BaseModel):
    application_id: UUID
    request_id: UUID
    assignment_id: UUID


class DiscardOut(Labelled):
    run_id: UUID
    algorithm: Algorithm
    status: Literal["DISCARDED"]
    discarded_count: int
    withdrawn: list[WithdrawnAssignment]


@router.post("/evc/schedule:propose", response_model=ProposalOut, status_code=201,
             description="Plan dates/AM-PM slots for QUEUED requests in scope with the EDF baseline (default) or CP-SAT over "
             "the same locked input; both are scored by the same metrics. Panels come from the SIMULATED authorised "
             "selector (stand-in); optimisation never picks experts. Writes a schedule_run, unpublished DEMO_PANEL "
             "assignments (which reserve their experts and slot capacity) and PROPOSED requests; unscheduled requests stay "
             "QUEUED with the umbrella reason NO_FEASIBLE_SLOT and a specific explanation_code. Each expert takes at most the "
             "pinned expert_daily_cap visits per date (DEMO ASSUMPTION, default 1). run_id is chosen by the caller and "
             "conflicts if reused. slot_capacity (DEMO ASSUMPTION, the demo path for slots) only creates AM/PM slot rows for "
             "horizon date/parts that have none; existing slot rows and their capacity are never changed. RO users are "
             "limited to their own region (another region is 403); a bureau region no expert or request names is 422 "
             "SCHEDULE_REGION_UNKNOWN. Regions match case-insensitively. Optional Idempotency-Key.")
def schedule_propose(body: ProposeBody, principal: Principal = Depends(current_principal),
                     key: str | None = Depends(idempotency_key)):
    command = body.command()
    return idempotent_response(principal, key, "POST", "/evc/schedule:propose", {}, body.model_dump(mode="json"),
        lambda uow: propose(uow, command), lambda result: ProposalOut(**result).model_dump(mode="json"), status_code=201)


@router.post("/evc/schedule:publish", response_model=PublishOut,
             description="Publish every proposal of one run in a single transaction after rechecking eligibility, COI, "
             "activity, expertise, panel size, window, slot capacity and the expert daily cap against published commitments. "
             "Any double booking (EVC_EXPERT_DOUBLE_BOOKED), exhausted slot (EVC_SLOT_CAPACITY_EXHAUSTED), exceeded daily "
             "cap (EVC_EXPERT_DAILY_CAP_EXCEEDED) or other failed recheck returns 409 and publishes nothing. Requests become PUBLISHED, which EvcPort.status reports. "
             "Optional Idempotency-Key.")
def schedule_publish(body: PublishBody, principal: Principal = Depends(current_principal),
                     key: str | None = Depends(idempotency_key)):
    return idempotent_response(principal, key, "POST", "/evc/schedule:publish", {}, body.model_dump(mode="json"),
        lambda uow: publish(uow, body.run_id), lambda result: PublishOut(**result).model_dump(mode="json"))


@router.post("/evc/schedule:discard", response_model=DiscardOut,
             description="Withdraw an unpublished PROPOSED run so its requests can be re-planned: its draft assignments "
             "are deleted, their requests return to QUEUED and the run becomes DISCARDED, with one evc.schedule_discarded "
             "event. Published or already discarded runs are 409 EVC_RUN_NOT_DISCARDABLE. Bureau only "
             "(evc.schedule.publish). Optional Idempotency-Key.")
def schedule_discard(body: DiscardBody, principal: Principal = Depends(current_principal),
                     key: str | None = Depends(idempotency_key)):
    return idempotent_response(principal, key, "POST", "/evc/schedule:discard", {}, body.model_dump(mode="json"),
        lambda uow: discard(uow, body.run_id), lambda result: DiscardOut(**result).model_dump(mode="json"))
