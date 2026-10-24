from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.deadlines.models import Deadline
from app.deadlines.wiring import clock
from app.platform.auth import current_principal
from app.platform.db import new_session
from app.platform.registry import port
from contracts.enums import Role
from contracts.errors import Forbidden, NotFound
from contracts.ports import AuthzPort, CasePort
from contracts.types import Principal, ResourceRef

router = APIRouter(tags=["deadlines"])


class DeadlineOut(BaseModel):
    id: UUID
    subject_type: str
    subject_id: UUID
    rule_id: str
    ruleset: str
    revision: str
    clause: str | None
    source_status: str
    clock_kind: str
    clock_owner: str
    status: str
    due_date: str
    due_version: int
    explanation: str


class ClockOut(BaseModel):
    now: str
    offset_days: float


class AdvanceIn(BaseModel):
    days: int = Field(ge=1, le=3650)


def _out(d: Deadline) -> DeadlineOut:
    return DeadlineOut(
        id=d.id, subject_type=d.subject_type, subject_id=d.subject_id, rule_id=d.rule_id, ruleset=d.ruleset,
        revision=d.revision, clause=d.clause, source_status=d.source_status, clock_kind=d.clock_kind,
        clock_owner=d.clock_owner, status=d.status, due_date=d.due_date.isoformat(), due_version=d.due_version,
        explanation=d.explanation,
    )


def _check_subject(session, principal: Principal, subject_type: str, subject_id: UUID) -> None:
    owner = None
    if subject_type == "application":
        owner = port(CasePort).lookup(session, subject_id).institution_id
    port(AuthzPort).check(principal, "deadline.read", ResourceRef(subject_type, subject_id, owner))


@router.get("/deadlines", response_model=list[DeadlineOut])
def list_deadlines(subject_id: UUID | None = None, status: str | None = None, owner: str | None = None,
                   principal: Principal = Depends(current_principal)):
    with new_session() as session:
        if subject_id is not None:
            _check_subject(session, principal, "application", subject_id)
        elif principal.role == Role.INSTITUTION:
            raise Forbidden("institution users must ask for one application's deadlines")
        else:
            port(AuthzPort).check(principal, "deadline.read", ResourceRef("deadline"))
        q = select(Deadline).order_by(Deadline.due_at)
        if subject_id is not None:
            q = q.where(Deadline.subject_id == subject_id)
        if status:
            q = q.where(Deadline.status == status)
        if owner:
            q = q.where(Deadline.clock_owner == owner)
        return [_out(d) for d in session.scalars(q).all()]


@router.get("/deadlines/{deadline_id}/explain", response_model=DeadlineOut)
def explain_deadline(deadline_id: UUID, principal: Principal = Depends(current_principal)):
    with new_session() as session:
        d = session.get(Deadline, deadline_id)
        if d is None:
            raise NotFound("deadline not found")
        _check_subject(session, principal, d.subject_type, d.subject_id)
        return _out(d)


@router.get("/sim/clock", response_model=ClockOut)
def read_clock(principal: Principal = Depends(current_principal)):
    return ClockOut(now=clock.now().isoformat(), offset_days=clock.offset.total_seconds() / 86400)


@router.post("/sim/clock", response_model=ClockOut)
def advance_clock(body: AdvanceIn, principal: Principal = Depends(current_principal)):
    port(AuthzPort).check(principal, "sim.clock", ResourceRef("clock"))
    clock.advance(body.days)
    return read_clock(principal)
