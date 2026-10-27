from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.deadlines.alerts import engine as alerts
from app.deadlines.models import Alert, Deadline
from app.deadlines.wiring import clock
from app.deadlines.worker import TimerWorker
from app.platform.auth import current_principal
from app.platform.db import new_session
from app.platform.idempotency import idempotency_key, idempotent_response
from app.platform.registry import port
from contracts.enums import Role
from contracts.errors import Forbidden, NotFound, ValidationFailed
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


# ---- alerts ----

ALERT_STATUSES = {"OPEN", "VACANT", "ESCALATED", "ACKNOWLEDGED"}


class AlertOut(BaseModel):
    id: UUID
    deadline_id: UUID
    level: int
    due_version: int
    role: str
    subject_type: str
    subject_id: UUID
    institution_id: UUID | None
    region: str | None
    template: str
    status: str
    reason: str | None
    from_alert_id: UUID | None
    raised_at: str
    escalated_at: str | None
    acknowledged_at: str | None


class TimerRunOut(BaseModel):
    processed: int


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def _alert_out(a: Alert) -> AlertOut:
    return AlertOut(
        id=a.id, deadline_id=a.deadline_id, level=a.level, due_version=a.due_version, role=a.role,
        subject_type=a.subject_type, subject_id=a.subject_id, institution_id=a.institution_id, region=a.region,
        template=a.template, status=a.status, reason=a.reason, from_alert_id=a.from_alert_id,
        raised_at=a.raised_at.isoformat(), escalated_at=_iso(a.escalated_at), acknowledged_at=_iso(a.acknowledged_at),
    )


@router.get("/alerts", response_model=list[AlertOut])
def list_alerts(status: str | None = None, deadline_id: UUID | None = None, region: str | None = None,
                principal: Principal = Depends(current_principal)):
    """Alerts the caller may see: an institution its own (addressed to it), a regional officer its region,
    a committee member those addressed to the committee, bureau and audit roles all (optionally by region)."""
    if status is not None and status not in ALERT_STATUSES:
        raise ValidationFailed(f"status must be one of {sorted(ALERT_STATUSES)}")
    scope_region = principal.region if principal.role == Role.RO_OFFICER else region
    port(AuthzPort).check(principal, "alert.read", ResourceRef(
        "alert", owner_institution_id=principal.institution_id, region=scope_region))
    q = select(Alert).order_by(Alert.raised_at.desc(), Alert.level.desc())
    if principal.role == Role.INSTITUTION:
        q = q.where(Alert.institution_id == principal.institution_id, Alert.role == Role.INSTITUTION.value)
    elif principal.role == Role.SCRUTINY_COMMITTEE:
        q = q.where(Alert.role == Role.SCRUTINY_COMMITTEE.value)
    if scope_region is not None:
        q = q.where(Alert.region == scope_region)
    if status is not None:
        q = q.where(Alert.status == status)
    if deadline_id is not None:
        q = q.where(Alert.deadline_id == deadline_id)
    with new_session() as session:
        return [_alert_out(a) for a in session.scalars(q.limit(500)).all()]


@router.post("/alerts/{alert_id}/ack", response_model=AlertOut)
def acknowledge_alert(alert_id: UUID, principal: Principal = Depends(current_principal),
                      key: str | None = Depends(idempotency_key)):
    """Stops further escalation for the alert's deadline and due_version. Repeating it changes nothing."""
    return idempotent_response(
        principal, key, "POST", "/alerts/{alert_id}/ack", {"alert_id": str(alert_id)}, None,
        lambda uow: alerts.acknowledge(uow, alert_id), lambda a: _alert_out(a).model_dump(mode="json"))


@router.post("/sim/timers/run", response_model=TimerRunOut)
def run_timers(principal: Principal = Depends(current_principal)):
    """Demo only: run the timer worker once in this process, so time travel shows its alerts straight away."""
    port(AuthzPort).check(principal, "sim.clock", ResourceRef("clock"))
    return TimerRunOut(processed=TimerWorker(worker_id="api-sim").run_once(limit=500))
