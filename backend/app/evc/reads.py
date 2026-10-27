"""Read-only views over stored EVC runs and one case's expert-visit requests.

Runs are read by the roles that read the expert pool (evc.expert.read). A regional officer sees only runs planned for
their own region; runs planned for every region are bureau/oversight reading. A case's requests are read like the
case itself (application.read with the case's institution and region). Nothing here writes.
"""
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.evc.models import Assignment, EvcRequest, ScheduleRun, ScheduleRunRequest, Slot
from app.evc.schedule_service import LABELS
from app.evc.selector import SELECTOR_LABEL
from app.evc.service import duration
from app.platform.registry import port
from contracts.enums import Role
from contracts.errors import Conflict, Forbidden, NotFound, ValidationFailed
from contracts.ports import AuthzPort, CasePort, ClockPort
from contracts.types import Principal, ResourceRef

RUN_STATUSES = ("PROPOSED", "PUBLISHED", "DISCARDED")


def _reader(principal: Principal, region: str | None = None, run_id: UUID | None = None) -> str | None:
    """Authorize a run read; returns the upper-case region the caller is limited to (regional officers), else None."""
    if principal.role == Role.RO_OFFICER:
        if not principal.region or (region is not None and region.upper() != principal.region.upper()):
            raise Forbidden("EVC_RUN_REGION_FORBIDDEN")
        port(AuthzPort).check(principal, "evc.expert.read", ResourceRef("evc", run_id, region=principal.region))
        return principal.region.upper()
    port(AuthzPort).check(principal, "evc.expert.read", ResourceRef("evc", run_id))
    return None


def _summary(run: ScheduleRun) -> dict:
    parameters = run.parameters
    return dict(run_id=run.run_id, algorithm=run.algorithm, status=run.status, region_scope=run.region_scope,
                horizon_start=date.fromordinal(parameters["horizon_start_ordinal"]),
                horizon_end=date.fromordinal(parameters["horizon_end_ordinal"]), created_at=run.created_at,
                input_fingerprint=bytes(parameters["input_fingerprint_bytes"]).hex(), metrics=run.metrics,
                expert_daily_cap=parameters.get("expert_daily_cap"), slot_capacity=parameters.get("default_slot_capacity"),
                candidate_slots=parameters.get("cpsat_candidate_slots"),
                outcomes_recorded=parameters.get("outcomes_recorded") is True, **LABELS)


def list_runs(session: Session, principal: Principal, *, status: str | None = None, algorithm: str | None = None,
              region: str | None = None, offset: int = 0, limit: int = 50) -> dict:
    limited = _reader(principal, region)
    query = select(ScheduleRun)
    if limited is not None:
        query = query.where(ScheduleRun.region_scope == limited)
    elif region is not None:
        query = query.where(ScheduleRun.region_scope == region.upper())
    if status is not None:
        query = query.where(ScheduleRun.status == status)
    if algorithm is not None:
        query = query.where(ScheduleRun.algorithm == algorithm)
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    rows = session.scalars(query.order_by(ScheduleRun.created_at.desc(), ScheduleRun.run_id).offset(offset).limit(limit))
    return dict(items=[_summary(run) for run in rows], total=total, offset=offset, limit=limit)


def read_run(session: Session, principal: Principal, run_id: UUID) -> dict:
    limited = _reader(principal, run_id=run_id)
    run = session.get(ScheduleRun, run_id)
    if run is None:
        raise NotFound("EVC_RUN_NOT_FOUND")
    if limited is not None and run.region_scope != limited:
        raise Forbidden("EVC_RUN_REGION_FORBIDDEN")
    result = _summary(run)
    solver = {key.removeprefix("cpsat_"): value for key, value in run.parameters.items() if key.startswith("cpsat_")}
    proposals = []
    for assignment, slot, request in session.execute(
            select(Assignment, Slot, EvcRequest).join(Slot, Slot.id == Assignment.slot_id)
            .join(EvcRequest, EvcRequest.id == Assignment.evc_request_id)
            .where(Assignment.schedule_run_id == run_id).order_by(Slot.date, Slot.slot_part, Assignment.id)):
        proposals.append(dict(application_id=request.application_id, request_id=request.id, assignment_id=assignment.id,
                              slot_id=slot.id, date=slot.date, slot_part=slot.slot_part, expert_ids=list(assignment.expert_ids),
                              due_by=request.due_by, lateness_days=max(0, (slot.date - request.due_by).days),
                              published=assignment.published))
    outcomes = session.execute(select(ScheduleRunRequest, EvcRequest.application_id)
                               .join(EvcRequest, EvcRequest.id == ScheduleRunRequest.request_id)
                               .where(ScheduleRunRequest.run_id == run_id).order_by(ScheduleRunRequest.ordinal)).all()
    unscheduled = [dict(request_id=row.request_id, application_id=application_id, reason_code="NO_FEASIBLE_SLOT",
                        explanation_code=row.explanation_code) for row, application_id in outcomes if row.outcome == "UNSCHEDULED"]
    withdrawn = [dict(request_id=row.request_id, application_id=application_id) for row, application_id in outcomes
                 if row.outcome == "PROPOSED"] if run.status == "DISCARDED" else []
    return dict(result, solver=solver or None, proposals=proposals, unscheduled=unscheduled, withdrawn=withdrawn)


def _days_waiting(row: EvcRequest, now: datetime) -> int:
    if now < row.requested_at:
        raise Conflict("EVC_CLOCK_BEFORE_REQUEST")
    stop = min(now, row.closed_at) if row.closed_at else now
    return int((stop - row.requested_at).total_seconds() // 86400)


def case_evc(session: Session, principal: Principal, application_id: UUID) -> dict:
    """Every EVC request of one case (newest first) with its published visit, scoped like the case."""
    case = port(CasePort).lookup(session, application_id)
    port(AuthzPort).check(principal, "application.read", ResourceRef("application", case.application_id,
                                                                     case.institution_id, case.region))
    # Defense in depth, as in the case API, for policy adapters without object scope.
    if principal.role == Role.INSTITUTION and principal.institution_id != case.institution_id:
        raise Forbidden("institution may only access its own records")
    if principal.role == Role.RO_OFFICER and (not principal.region or principal.region != case.region):
        raise Forbidden("regional officer may only access their own region")
    now = port(ClockPort).now()
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValidationFailed("EVC_CLOCK_MUST_BE_AWARE")
    rows = list(session.scalars(select(EvcRequest).where(EvcRequest.application_id == application_id)
                                .order_by(EvcRequest.requested_at.desc(), EvcRequest.id.desc())))
    visits = {}
    if rows:
        for assignment, slot, run in session.execute(
                select(Assignment, Slot, ScheduleRun).join(Slot, Slot.id == Assignment.slot_id)
                .join(ScheduleRun, ScheduleRun.run_id == Assignment.schedule_run_id)
                .where(Assignment.evc_request_id.in_([row.id for row in rows]), Assignment.published.is_(True))):
            visits[assignment.evc_request_id] = dict(
                assignment_id=assignment.id, run_id=run.run_id, algorithm=run.algorithm, date=slot.date,
                slot_part=slot.slot_part, panel_role=assignment.panel_role, expert_ids=list(assignment.expert_ids),
                simulation_status="SIMULATED", selector_label=SELECTOR_LABEL)
    requests = [dict(id=row.id, status=row.status, category=row.category, requested_at=row.requested_at,
                     earliest_date=row.earliest_date, due_by=row.due_by, closed_at=row.closed_at, ruleset_key=row.ruleset_key,
                     rule_id=row.rule_id, days_waiting=_days_waiting(row, now),
                     duration_days=duration(row.ruleset_key, row.rule_id) if row.ruleset_key and row.rule_id else None,
                     visit=visits.get(row.id)) for row in rows]
    return dict(application_id=application_id, region=case.region, current=requests[0] if requests else None,
                requests=requests)
