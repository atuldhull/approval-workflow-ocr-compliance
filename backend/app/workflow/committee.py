"""Member-only committee writes, protected notes and append-only report versions."""
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID, NAMESPACE_URL, uuid5

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.platform.auth import current_principal
from app.platform.db import new_session
from app.platform.idempotency import idempotency_key, idempotent_response
from app.platform.registry import port
from app.workflow.case_service import projection, scope
from app.workflow.case_api_models import CaseErrorOut, CaseInputErrorOut
from app.workflow.models import Committee, CommitteeMember, CommitteeTask, Observation, ReportVersion
from contracts.errors import Conflict, Forbidden, NotFound, ValidationFailed
from contracts.ports import AuthzPort, ClockPort, LedgerPort, NotesPort, UnitOfWork
from contracts.types import EventIn, Principal, ResourceRef

CommitteeType = Literal["SCRUTINY", "RESCRUTINY", "EVC", "SHC", "EC", "COUNCIL"]
MemberRole = Literal["CHAIR", "MEMBER", "SECRETARY"]
TaskTitle = Literal["REVIEW_DOCUMENTS", "REVIEW_RESPONSES", "PREPARE_REPORT"]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
TextBody = Annotated[str, Field(min_length=1)]
router = APIRouter(tags=["committees"])
ERROR_RESPONSES = {code: {"model": CaseErrorOut} for code in (403, 404, 409)}
ERROR_RESPONSES[422] = {"model": CaseErrorOut | CaseInputErrorOut}


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MemberIn(Input):
    user_ref: UUID
    role: MemberRole


class CommitteeIn(Input):
    type: CommitteeType
    members: list[MemberIn] = Field(min_length=1)


class TaskIn(Input):
    title_key: TaskTitle
    assignee_user_ref: UUID


class ObservationIn(Input):
    body: TextBody


class ReportIn(Input):
    content: TextBody
    parent_version: UUID | None = None


class Output(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ObservationOut(Output):
    id: UUID
    task_id: UUID
    author_user_ref: UUID
    body_note_ref: UUID
    body_note_hash: Digest


class TaskOut(Output):
    id: UUID
    title_key: TaskTitle
    assignee_user_ref: UUID
    status: Literal["ASSIGNED", "DONE"]
    observations: list[ObservationOut]


class CommitteeOut(Output):
    id: UUID
    application_id: UUID
    type: CommitteeType
    status: Literal["ACTIVE", "CLOSED"]
    members: list[MemberIn]
    tasks: list[TaskOut]
    report_count: int
    assumption_status: Literal["DEMO_ASSUMPTION"] = "DEMO_ASSUMPTION"


class ReportDiff(BaseModel):
    comparison: Literal["INITIAL", "HASH_ONLY"]
    parent_version_no: int | None
    previous_content_hash: Digest | None
    content_changed: bool
    author_changed: bool


class ReportOut(Output):
    id: UUID
    committee_id: UUID
    version_no: int
    content_note_ref: UUID
    content_note_hash: Digest
    author_user_ref: UUID
    created_at: datetime
    parent_version: UUID | None
    diff: ReportDiff


def _check(principal: Principal, action: str) -> None:
    port(AuthzPort).check(principal, action, ResourceRef("application"))


def _committee(session: Session, committee_id: UUID, principal: Principal, action: str, *, write: bool) -> Committee:
    if write:
        _check(principal, action)
    # Reads are checked by the case's own scope below, which states its institution and region (so regional
    # officers can read their region's committees, as with the case committee list).
    row = session.get(Committee, committee_id)
    if row is None:
        raise NotFound("committee not found")
    scope(session, row.application_id, principal, action)
    if write:
        row = session.scalar(select(Committee).where(Committee.id == committee_id)
                             .with_for_update().execution_options(populate_existing=True))
        if session.get(CommitteeMember, (committee_id, principal.user_id)) is None:
            raise Forbidden("COMMITTEE_MEMBERSHIP_REQUIRED")
        if row.status != "ACTIVE":
            raise Conflict("COMMITTEE_CLOSED")
    return row


def _event(uow: UnitOfWork, row: Committee, event_type: str, payload: dict,
           *, note_ref: UUID | None = None, note_hash: str | None = None) -> None:
    port(LedgerPort).append(uow, EventIn(aggregate_type="application", aggregate_id=row.application_id,
        event_type=event_type, payload={"application_id": row.application_id, "committee_id": row.id, **payload},
        ruleset_rev=projection(uow.session, row.application_id)["ruleset_rev"], note_ref=note_ref, note_hash=note_hash))


def _id(kind: str, parent: UUID, ordinal: int) -> UUID:
    return uuid5(NAMESPACE_URL, f"sih26262:committee:{kind}:{parent}:{ordinal}")


def _note(uow: UnitOfWork, body: str) -> tuple[UUID, str]:
    if not body.strip():
        raise ValidationFailed("EMPTY_COMMITTEE_NOTE")
    return port(NotesPort).create(uow, body)


def _task_out(session: Session, task: CommitteeTask) -> TaskOut:
    observations = session.scalars(select(Observation).where(Observation.task_id == task.id).order_by(Observation.id))
    return TaskOut(id=task.id, title_key=task.title_key, assignee_user_ref=task.assignee_user_ref, status=task.status,
                   observations=[ObservationOut.model_validate(row) for row in observations])


def _out(session: Session, row: Committee) -> CommitteeOut:
    members = session.scalars(select(CommitteeMember).where(CommitteeMember.committee_id == row.id)
                              .order_by(CommitteeMember.user_ref))
    tasks = session.scalars(select(CommitteeTask).where(CommitteeTask.committee_id == row.id).order_by(CommitteeTask.id))
    count = session.scalar(select(func.count()).select_from(ReportVersion).where(ReportVersion.committee_id == row.id))
    return CommitteeOut(id=row.id, application_id=row.application_id, type=row.type, status=row.status,
        members=[MemberIn(user_ref=member.user_ref, role=member.role) for member in members],
        tasks=[_task_out(session, task) for task in tasks], report_count=count)


def form(uow: UnitOfWork, case_id: UUID, body: CommitteeIn) -> CommitteeOut:
    _check(uow.principal, "committee.create")
    scope(uow.session, case_id, uow.principal, "committee.create")
    projection(uow.session, case_id, lock=True)
    users = [member.user_ref for member in body.members]
    if uow.principal.user_id not in users:
        raise Forbidden("COMMITTEE_MEMBERSHIP_REQUIRED")
    if len(users) != len(set(users)):
        raise ValidationFailed("COMMITTEE_MEMBERS_DUPLICATED")
    ordinal = uow.session.scalar(select(func.count()).select_from(Committee).where(Committee.application_id == case_id)) + 1
    row = Committee(id=_id("formation", case_id, ordinal), application_id=case_id, type=body.type, status="ACTIVE")
    uow.session.add(row)
    uow.session.flush()
    for member in sorted(body.members, key=lambda member: str(member.user_ref)):
        uow.session.add(CommitteeMember(committee_id=row.id, user_ref=member.user_ref, role=member.role))
    uow.session.flush()
    _event(uow, row, "wf.committee_formed", {"type": body.type,
        "members": [member.model_dump() for member in sorted(body.members, key=lambda member: str(member.user_ref))]})
    return _out(uow.session, row)


def assign(uow: UnitOfWork, committee_id: UUID, body: TaskIn) -> TaskOut:
    row = _committee(uow.session, committee_id, uow.principal, "committee.task.assign", write=True)
    if uow.session.get(CommitteeMember, (committee_id, body.assignee_user_ref)) is None:
        raise ValidationFailed("TASK_ASSIGNEE_NOT_MEMBER")
    ordinal = uow.session.scalar(select(func.count()).select_from(CommitteeTask).where(CommitteeTask.committee_id == row.id)) + 1
    task = CommitteeTask(id=_id("task", row.id, ordinal), committee_id=row.id, title_key=body.title_key,
                         assignee_user_ref=body.assignee_user_ref, status="ASSIGNED")
    uow.session.add(task)
    uow.session.flush()
    _event(uow, row, "wf.task_assigned", {"task_id": task.id, "title_key": task.title_key,
                                         "assignee_user_ref": task.assignee_user_ref})
    return _task_out(uow.session, task)


def observe(uow: UnitOfWork, task_id: UUID, body: ObservationIn) -> ObservationOut:
    _check(uow.principal, "committee.observation.add")
    task = uow.session.get(CommitteeTask, task_id)
    if task is None:
        raise NotFound("task not found")
    row = _committee(uow.session, task.committee_id, uow.principal, "committee.observation.add", write=True)
    ref, digest = _note(uow, body.body)
    ordinal = uow.session.scalar(select(func.count()).select_from(Observation).where(Observation.task_id == task_id)) + 1
    observation = Observation(id=_id("observation", task_id, ordinal), committee_id=row.id, task_id=task_id,
                              author_user_ref=uow.principal.user_id, body_note_ref=ref, body_note_hash=digest)
    uow.session.add(observation)
    uow.session.flush()
    _event(uow, row, "wf.observation_added", {"observation_id": observation.id, "task_id": task_id,
        "author_user_ref": observation.author_user_ref, "body_note_ref": ref, "body_note_hash": digest},
        note_ref=ref, note_hash=digest)
    return ObservationOut.model_validate(observation)


def _report_out(row: ReportVersion, parent: ReportVersion | None) -> ReportOut:
    return ReportOut(id=row.id, committee_id=row.committee_id, version_no=row.version_no,
        content_note_ref=row.content_note_ref, content_note_hash=row.content_note_hash, author_user_ref=row.author_user_ref,
        created_at=row.created_at, parent_version=row.parent_version,
        diff=ReportDiff(comparison="HASH_ONLY" if parent else "INITIAL", parent_version_no=parent.version_no if parent else None,
            previous_content_hash=parent.content_note_hash if parent else None,
            content_changed=parent is None or parent.content_note_hash != row.content_note_hash,
            author_changed=parent is not None and parent.author_user_ref != row.author_user_ref))


def append_report(uow: UnitOfWork, committee_id: UUID, body: ReportIn) -> ReportOut:
    row = _committee(uow.session, committee_id, uow.principal, "committee.report.add", write=True)
    parent = uow.session.scalar(select(ReportVersion).where(ReportVersion.committee_id == row.id)
                                .order_by(ReportVersion.version_no.desc()).limit(1))
    parent_id = parent.id if parent else None
    if "parent_version" in body.model_fields_set and body.parent_version != parent_id:
        raise Conflict("REPORT_PARENT_CONFLICT")
    ref, digest = _note(uow, body.content)
    number = parent.version_no + 1 if parent else 1
    now = port(ClockPort).now()
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValidationFailed("CLOCK_MUST_BE_AWARE")
    if parent is not None and now < parent.created_at:
        raise Conflict("CLOCK_BEFORE_REPORT_PARENT")
    report = ReportVersion(id=_id("report", row.id, number), committee_id=row.id, version_no=number,
        content_note_ref=ref, content_note_hash=digest, author_user_ref=uow.principal.user_id, created_at=now,
        parent_version=parent_id)
    uow.session.add(report)
    uow.session.flush()
    _event(uow, row, "wf.report_version_added", {"report_version_id": report.id, "version_no": number,
        "parent_version": parent_id, "author_user_ref": report.author_user_ref,
        "content_note_ref": ref, "content_note_hash": digest}, note_ref=ref, note_hash=digest)
    return _report_out(report, parent)


class LatestReportOut(BaseModel):
    id: UUID
    version_no: int
    created_at: datetime
    author_user_ref: UUID
    content_note_hash: Digest


class CommitteeSummaryOut(BaseModel):
    id: UUID
    application_id: UUID
    ordinal: int
    type: CommitteeType
    status: Literal["ACTIVE", "CLOSED"]
    members: list[MemberIn]
    task_count: int
    report_count: int
    latest_report: LatestReportOut | None
    assumption_status: Literal["DEMO_ASSUMPTION"] = "DEMO_ASSUMPTION"


def case_committees(session: Session, case_id: UUID, principal: Principal) -> list[CommitteeSummaryOut]:
    """Every committee formed for one case, in formation order, scoped like the case."""
    # The case's own scope states its institution and region, so regional officers can read their region's cases.
    scope(session, case_id, principal, "committee.read")
    rows = {row.id: row for row in session.scalars(select(Committee).where(Committee.application_id == case_id))}
    # Committee IDs are derived from the formation ordinal, so formation order is recovered without a timestamp.
    by_ordinal = {_id("formation", case_id, n): n for n in range(1, len(rows) + 1)}
    ordered = sorted(rows.values(), key=lambda row: (by_ordinal.get(row.id, len(rows) + 1), str(row.id)))
    result = []
    for ordinal, row in enumerate(ordered, start=1):
        members = session.scalars(select(CommitteeMember).where(CommitteeMember.committee_id == row.id)
                                  .order_by(CommitteeMember.user_ref))
        tasks = session.scalar(select(func.count()).select_from(CommitteeTask).where(CommitteeTask.committee_id == row.id))
        reports = session.scalar(select(func.count()).select_from(ReportVersion).where(ReportVersion.committee_id == row.id))
        latest = session.scalar(select(ReportVersion).where(ReportVersion.committee_id == row.id)
                                .order_by(ReportVersion.version_no.desc()).limit(1))
        result.append(CommitteeSummaryOut(id=row.id, application_id=row.application_id, ordinal=ordinal, type=row.type,
            status=row.status, members=[MemberIn(user_ref=m.user_ref, role=m.role) for m in members], task_count=tasks,
            report_count=reports, latest_report=LatestReportOut(id=latest.id, version_no=latest.version_no,
                created_at=latest.created_at, author_user_ref=latest.author_user_ref,
                content_note_hash=latest.content_note_hash) if latest else None))
    return result


def read(session: Session, committee_id: UUID, principal: Principal) -> CommitteeOut:
    row = _committee(session, committee_id, principal, "committee.read", write=False)
    return _out(session, row)


def reports(session: Session, committee_id: UUID, principal: Principal) -> list[ReportOut]:
    row = _committee(session, committee_id, principal, "committee.read", write=False)
    rows = list(session.scalars(select(ReportVersion).where(ReportVersion.committee_id == row.id)
                                .order_by(ReportVersion.version_no)))
    by_id = {version.id: version for version in rows}
    return [_report_out(version, by_id.get(version.parent_version)) for version in rows]


IDEMPOTENT = "Optional Idempotency-Key: same key and body replays (Idempotent-Replayed: true), a different body is 422."


def _json(model: BaseModel):
    return model.model_dump(mode="json")


@router.post("/cases/{application_id}/committees", response_model=CommitteeOut, status_code=201, responses=ERROR_RESPONSES,
             description=IDEMPOTENT)
def create_committee(application_id: UUID, body: CommitteeIn, principal: Principal = Depends(current_principal),
                     key: str | None = Depends(idempotency_key)):
    return idempotent_response(principal, key, "POST", "/cases/{application_id}/committees",
        {"application_id": str(application_id)}, body.model_dump(mode="json"),
        lambda uow: form(uow, application_id, body), _json, status_code=201)


@router.post("/committees/{committee_id}/tasks", response_model=TaskOut, status_code=201, responses=ERROR_RESPONSES,
             description=IDEMPOTENT)
def create_task(committee_id: UUID, body: TaskIn, principal: Principal = Depends(current_principal),
                key: str | None = Depends(idempotency_key)):
    return idempotent_response(principal, key, "POST", "/committees/{committee_id}/tasks",
        {"committee_id": str(committee_id)}, body.model_dump(mode="json"),
        lambda uow: assign(uow, committee_id, body), _json, status_code=201)


@router.post("/tasks/{task_id}/observations", response_model=ObservationOut, status_code=201, responses=ERROR_RESPONSES,
             description=IDEMPOTENT)
def create_observation(task_id: UUID, body: ObservationIn, principal: Principal = Depends(current_principal),
                       key: str | None = Depends(idempotency_key)):
    return idempotent_response(principal, key, "POST", "/tasks/{task_id}/observations",
        {"task_id": str(task_id)}, body.model_dump(mode="json"),
        lambda uow: observe(uow, task_id, body), _json, status_code=201)


@router.post("/committees/{committee_id}/reports", response_model=ReportOut, status_code=201, responses=ERROR_RESPONSES,
             description=IDEMPOTENT)
def create_report(committee_id: UUID, body: ReportIn, principal: Principal = Depends(current_principal),
                  key: str | None = Depends(idempotency_key)):
    # exclude_unset keeps "parent_version omitted" (append to head) distinct from an explicit null parent.
    return idempotent_response(principal, key, "POST", "/committees/{committee_id}/reports",
        {"committee_id": str(committee_id)}, body.model_dump(mode="json", exclude_unset=True),
        lambda uow: append_report(uow, committee_id, body), _json, status_code=201)


@router.get("/cases/{application_id}/committees", response_model=list[CommitteeSummaryOut], responses=ERROR_RESPONSES,
            description="Committees formed for one case in formation order: type, status, members as user references, "
                        "task and report counts and the latest report version (hash only). Scoped like the case.")
def list_committees(application_id: UUID, principal: Principal = Depends(current_principal)):
    with new_session() as session:
        return case_committees(session, application_id, principal)


@router.get("/committees/{committee_id}", response_model=CommitteeOut, responses=ERROR_RESPONSES)
def get_committee(committee_id: UUID, principal: Principal = Depends(current_principal)):
    with new_session() as session:
        return read(session, committee_id, principal)


@router.get("/committees/{committee_id}/reports", response_model=list[ReportOut], responses=ERROR_RESPONSES)
def get_reports(committee_id: UUID, principal: Principal = Depends(current_principal)):
    with new_session() as session:
        return reports(session, committee_id, principal)
