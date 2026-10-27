"""Expert directory and audited pool-management HTTP commands."""
from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints, field_validator, model_validator
from sqlalchemy import select

from app.evc.models import AssignmentExpert, Availability, Expert
from app.evc.pool import authorize, policy, record_coi, register_expert, set_availability
from app.platform.auth import current_principal
from app.platform.db import new_session
from app.platform.idempotency import idempotency_key, idempotent_response
from contracts.enums import Role
from contracts.errors import ValidationFailed
from contracts.types import Principal

router = APIRouter(tags=["evc"])
Code = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]*$", max_length=100)]
SlotPart = Literal["AM", "PM"]
CoiCode = Literal["INSTITUTION_LINK", "PRIOR_ENGAGEMENT", "RECUSAL"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PersonalDetails(Input):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    phone: str | None = Field(default=None, min_length=1, max_length=40)
    email: str | None = Field(default=None, min_length=1, max_length=254)

    @model_validator(mode="after")
    def nonempty(self):
        if not any(value and value.strip() for value in (self.name, self.phone, self.email)):
            raise ValueError("PERSONAL_DETAILS_EMPTY")
        return self


class ExpertCreate(Input):
    user_ref: UUID
    region: Code
    expertise_tags: list[Code] = Field(min_length=1, max_length=50)
    active: StrictBool = True
    personal_details: PersonalDetails | None = None

    @field_validator("region", mode="before")
    @classmethod
    def canonical_region(cls, value):
        return value.upper() if isinstance(value, str) else value

    @field_validator("expertise_tags")
    @classmethod
    def canonical_tags(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("EXPERT_TAG_DUPLICATE")
        return sorted(value)


class ExpertOut(BaseModel):
    id: UUID
    user_ref: UUID
    region: str
    expertise_tags: list[str]
    active: bool
    personal_ref: UUID | None
    identity_status: Literal["P3_USER_REF_UNVERIFIED"] = "P3_USER_REF_UNVERIFIED"
    available_parts: list[SlotPart] | None = None


def expert_result(row: Expert, available_parts: list[str] | None = None) -> ExpertOut:
    return ExpertOut(id=row.id, user_ref=row.user_ref, region=row.region.upper(), expertise_tags=sorted(row.expertise_tags),
                     active=row.active, personal_ref=row.personal_ref, available_parts=available_parts)


class AvailabilityItem(Input):
    date: date
    slot_part: SlotPart
    available: StrictBool


class AvailabilitySet(Input):
    items: list[AvailabilityItem] = Field(min_length=1, max_length=732)

    @model_validator(mode="after")
    def unique_slots(self):
        if len({(row.date, row.slot_part) for row in self.items}) != len(self.items):
            raise ValueError("EXPERT_AVAILABILITY_DUPLICATE")
        return self


class AvailabilityResult(BaseModel):
    expert_id: UUID
    changed_count: int
    items: list[AvailabilityItem]
    ruleset_key: str
    source_status: Literal["DEMO_ASSUMPTION"]
    assumption_code: Literal["EXPERT_POLICY_UNCONFIRMED"]


class CoiCreate(Input):
    expert_id: UUID
    institution_ref: UUID
    source: CoiCode
    reason_code: CoiCode

    @model_validator(mode="after")
    def matching_codes(self):
        if self.source != self.reason_code:
            raise ValueError("EXPERT_COI_REASON_MISMATCH")
        return self


class CoiResult(CoiCreate):
    created: bool
    ruleset_key: str
    source_status: Literal["DEMO_ASSUMPTION"]
    assumption_code: Literal["EXPERT_POLICY_UNCONFIRMED"]


class ExpertPage(BaseModel):
    items: list[ExpertOut]
    total: int
    offset: int
    limit: int
    ruleset_key: str
    region_rule: Literal["SAME_REGION", "ANY_REGION", "OTHER_REGION"]
    source_status: Literal["DEMO_ASSUMPTION"] = "DEMO_ASSUMPTION"
    assumption_code: Literal["EXPERT_POLICY_UNCONFIRMED"] = "EXPERT_POLICY_UNCONFIRMED"


IDEMPOTENT = " Optional Idempotency-Key: same key and body replays (Idempotent-Replayed: true), a different body is 422."


@router.post("/evc/experts", response_model=ExpertOut, status_code=201,
             description="Register an opaque P3 user_ref. User-master existence/role validation is pending P3's lookup port. "
             "Optional personal details are stored exclusively through PersonalDataPort. Duplicate user_ref returns 409." + IDEMPOTENT)
def create_expert(body: ExpertCreate, principal: Principal = Depends(current_principal),
                  key: str | None = Depends(idempotency_key)):
    return idempotent_response(principal, key, "POST", "/evc/experts", {}, body.model_dump(mode="json"),
        lambda uow: expert_result(register_expert(uow, body)), lambda out: out.model_dump(mode="json"), status_code=201)


@router.post("/evc/experts/{id}/availability", response_model=AvailabilityResult,
             description="Set up to 732 unique date/AM-PM entries atomically. Identical repeats are no-ops without new events." + IDEMPOTENT)
def availability(id: UUID, body: AvailabilitySet, principal: Principal = Depends(current_principal),
                 key: str | None = Depends(idempotency_key)):
    return idempotent_response(principal, key, "POST", "/evc/experts/{id}/availability", {"id": str(id)},
        body.model_dump(mode="json"), lambda uow: set_availability(uow, id, body),
        lambda out: AvailabilityResult.model_validate(out).model_dump(mode="json"))


@router.post("/evc/coi", response_model=CoiResult,
             description="Manager records a controlled COI, including recusal on behalf of the expert. Identical repeats are no-ops." + IDEMPOTENT)
def coi(body: CoiCreate, principal: Principal = Depends(current_principal), key: str | None = Depends(idempotency_key)):
    return idempotent_response(principal, key, "POST", "/evc/coi", {}, body.model_dump(mode="json"),
        lambda uow: record_coi(uow, body), lambda out: CoiResult.model_validate(out).model_dump(mode="json"))


@router.get("/evc/experts", response_model=ExpertPage,
            description="Scoped directory in UUID order. available_on filters active experts with at least one unreserved available part; "
            "slot_part optionally narrows it. Includes proposed reservations. This directory has no institution context and does not apply COI eligibility.")
def experts(region: str | None = Query(default=None, pattern=r"^[A-Za-z][A-Za-z0-9_]*$", max_length=100),
            available_on: date | None = None, slot_part: SlotPart | None = None,
            offset: int = Query(default=0, ge=0), limit: int = Query(default=50, ge=1, le=100),
            principal: Principal = Depends(current_principal)):
    authorize(principal, "evc.expert.read", region=region)
    if slot_part is not None and available_on is None:
        raise ValidationFailed("EXPERT_AVAILABLE_ON_REQUIRED")
    rules, selected = policy()
    with new_session() as session:
        available = set()
        reserved = set()
        if available_on is not None:
            available = {(row.expert_id, row.slot_part) for row in session.scalars(select(Availability)
                         .where(Availability.date == available_on, Availability.available.is_(True)))}
            reserved = {(row.expert_id, row.slot_part) for row in session.scalars(select(AssignmentExpert)
                        .where(AssignmentExpert.date == available_on))}
        visible = []
        for row in session.scalars(select(Expert).order_by(Expert.id)):
            if region is not None and row.region.upper() != region.upper():
                continue
            if principal.role == Role.RO_OFFICER and row.region.upper() != principal.region.upper():
                continue
            parts = sorted(part for part in selected.slot_parts if (row.id, part) in available - reserved
                           and (slot_part is None or part == slot_part)) if available_on is not None else None
            if available_on is not None and (not row.active or not parts):
                continue
            visible.append(expert_result(row, parts))
        return ExpertPage(items=visible[offset:offset + limit], total=len(visible), offset=offset, limit=limit,
                          ruleset_key=rules.key, region_rule=selected.region_rule)
