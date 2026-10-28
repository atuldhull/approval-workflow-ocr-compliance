from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.compliance import service, validity
from app.compliance.models import ApprovalLetter, Evidence, Obligation
from app.deadlines.models import Deadline
from app.documents.models import DocumentVersion
from app.platform.auth import current_principal
from app.platform.db import new_session
from app.platform.idempotency import idempotency_key, idempotent_response
from app.platform.registry import port
from contracts.enums import DeadlineStatus, LetterType, ObligationKind, Role
from contracts.errors import NotFound
from contracts.ports import AuthzPort, CasePort, RulesetPort
from contracts.types import LetterIn, Principal, ResourceRef

router = APIRouter(tags=["compliance"])


class LetterRegisterIn(BaseModel):
    application_id: UUID
    institution_id: UUID
    letter_type: LetterType
    academic_year: str = Field(pattern=r"^[0-9]{4}-[0-9]{2}$")
    issue_date: date
    issue_date_source: Literal["PORTAL_EVENT", "CONFIRMED_FACT"]
    lists_deficiencies: bool
    f_no: str | None = Field(default=None, max_length=100)
    issue_date_fact_id: UUID | None = None
    document_version_id: UUID | None = None


class EvidenceIn(BaseModel):
    document_version_id: UUID


class VerifyIn(BaseModel):
    decision: Literal["ACCEPTED", "REJECTED"]
    reason_code: str | None = Field(default=None, max_length=64)
    # stored in the note store; events carry only its hash
    note: str | None = Field(default=None, max_length=4000)


class EvidenceOut(BaseModel):
    id: UUID
    obligation_id: UUID
    document_version_id: UUID
    status: str
    submitted_at: str
    verified_role: str | None
    verified_at: str | None
    reason_code: str | None
    has_note: bool


class EvidenceNoteOut(BaseModel):
    evidence_id: UUID
    has_note: bool
    note: str | None  # None when there is no note or it was redacted
    redacted: bool
    verified_role: str | None
    verified_at: str | None


class ObligationOut(BaseModel):
    id: UUID
    application_id: UUID
    institution_id: UUID
    region: str
    kind: ObligationKind
    source_letter_id: UUID | None
    source_clause: str | None
    source_status: str
    state_origin: str
    rule_id: str | None
    deadline_id: UUID | None
    due_date: str | None
    status: str
    met_at: str | None
    evidence: list[EvidenceOut] = []
    # read from the obligation's clock: RUNNING, BREACHED, MET, ...; overdue = its clock ran out and it is not met
    deadline_status: str | None = None
    overdue: bool = False
    # DOCUMENT_VALIDITY: the document version, the date it is valid until and where that date comes from
    # (DOCUMENT_FACT, OFFICER_RECORDED, APH_PERIOD); validity_state is VALID, EXPIRING_SOON, EXPIRED,
    # RENEWAL_UNDER_REVIEW or RENEWED, and days_left counts from today on the system clock
    document_id: UUID | None = None
    document_version_id: UUID | None = None
    document_version_no: int | None = None
    doc_type: str | None = None
    valid_until: str | None = None
    validity_basis: str | None = None
    validity_state: str | None = None
    days_left: int | None = None
    # land lease only: first academic year an EoA is blocked (APH 2.1(e)) and whether the live lease covered the
    # longest course when the application was submitted (6.17(a))
    eoa_stop_year: str | None = None
    live_lease_ok: bool | None = None
    # an obligation an officer recorded: what it asks for and the evidence that meets it
    title: str | None = None
    evidence_required: str | None = None
    # penalty tiers the rule lists, for the competent authority; never applied by the system
    penalty_notes: list[str] = []


class ObligationRecordIn(BaseModel):
    application_id: UUID
    kind: ObligationKind
    title: str = Field(min_length=1, max_length=200)
    evidence_required: str = Field(min_length=1, max_length=500)
    source_clause: str | None = Field(default=None, max_length=32)
    due_date: date | None = None
    rule_id: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*$")
    anchor_date: date | None = None


class ValidityRecordIn(BaseModel):
    document_version_id: UUID
    valid_until: date | None = None
    issue_date: date | None = None
    max_course_duration_years: int | None = Field(default=None, ge=1, le=10)


class LetterOut(BaseModel):
    id: UUID
    application_id: UUID
    institution_id: UUID
    region: str
    letter_type: LetterType
    academic_year: str
    issue_date: str
    issue_date_source: str
    issue_date_fact_id: UUID | None
    document_version_id: UUID | None
    f_no: str | None
    lists_deficiencies: bool
    ruleset_rev: str
    valid_until: str | None
    registered_at: str
    obligation_ids: list[UUID]


def _iso(v) -> str | None:
    return v.isoformat() if v is not None else None


def _evidence_out(e: Evidence) -> EvidenceOut:
    return EvidenceOut(id=e.id, obligation_id=e.obligation_id, document_version_id=e.document_version_id,
                       status=e.status, submitted_at=e.submitted_at.isoformat(), verified_role=e.verified_role,
                       verified_at=_iso(e.verified_at), reason_code=e.reason_code, has_note=e.note_ref is not None)


class _Reading:
    """What every obligation in one response is read against: today on the system clock and the pinned rules."""

    def __init__(self, session, obligations):
        rules = port(RulesetPort).get(port(RulesetPort).default_key()).deadline_rules
        self.today, self.window, self.rules = service._today(), validity.expiring_window_days(), rules
        ids = [o.document_version_id for o in obligations if o.document_version_id is not None]
        self.version_no = dict(session.execute(select(DocumentVersion.document_version_id, DocumentVersion.version_no)
                                               .where(DocumentVersion.document_version_id.in_(ids))).all()) if ids else {}


def _obligation_out(o: Obligation, reading: _Reading, evidence: list[Evidence] = (),
                    clock: str | None = None) -> ObligationOut:
    is_validity = o.kind == ObligationKind.DOCUMENT_VALIDITY and o.valid_until is not None
    return ObligationOut(
        id=o.id, application_id=o.application_id, institution_id=o.institution_id, region=o.region, kind=o.kind,
        source_letter_id=o.source_letter_id, source_clause=o.source_clause, source_status=o.source_status,
        state_origin=o.state_origin, rule_id=o.rule_id, deadline_id=o.deadline_id, due_date=_iso(o.due_date),
        status=o.status, met_at=_iso(o.met_at), evidence=[_evidence_out(e) for e in evidence],
        deadline_status=clock, overdue=clock == DeadlineStatus.BREACHED and o.status != "MET",
        document_id=o.document_id, document_version_id=o.document_version_id,
        document_version_no=reading.version_no.get(o.document_version_id), doc_type=o.doc_type,
        valid_until=_iso(o.valid_until), validity_basis=o.validity_basis,
        validity_state=validity.validity_state(o, reading.today, reading.window) if is_validity else None,
        days_left=(o.valid_until - reading.today).days if is_validity else None,
        eoa_stop_year=o.eoa_stop_year, live_lease_ok=o.live_lease_ok, title=o.title,
        evidence_required=o.evidence_required, penalty_notes=service.penalty_notes(reading.rules.get(o.rule_id)),
    )


def _read_one(session, o: Obligation) -> ObligationOut:
    evidence = session.scalars(select(Evidence).where(Evidence.obligation_id == o.id)
                               .order_by(Evidence.submitted_at, Evidence.id)).all()
    return _obligation_out(o, _Reading(session, [o]), evidence, _clocks(session, [o]).get(o.deadline_id))


def _clocks(session, obligations) -> dict[UUID, str]:
    """Status of each obligation's deadline; overdue is derived from it rather than kept as an obligation status."""
    ids = [o.deadline_id for o in obligations if o.deadline_id is not None]
    if not ids:
        return {}
    return dict(session.execute(select(Deadline.id, Deadline.status).where(Deadline.id.in_(ids))).all())


def _letter_out(session, a: ApprovalLetter) -> LetterOut:
    ids = session.scalars(select(Obligation.id).where(Obligation.source_letter_id == a.id)
                          .order_by(Obligation.created_at, Obligation.kind)).all()
    return LetterOut(
        id=a.id, application_id=a.application_id, institution_id=a.institution_id, region=a.region,
        letter_type=a.letter_type, academic_year=a.academic_year, issue_date=a.issue_date.isoformat(),
        issue_date_source=a.issue_date_source, issue_date_fact_id=a.issue_date_fact_id,
        document_version_id=a.document_version_id, f_no=a.f_no, lists_deficiencies=a.lists_deficiencies,
        ruleset_rev=a.ruleset_rev, valid_until=_iso(a.valid_until), registered_at=a.registered_at.isoformat(),
        obligation_ids=list(ids),
    )


def _scope(session, principal: Principal, application_id: UUID | None, region: str | None):
    """Authorises a list query and returns the column filters that keep it inside the caller's scope."""
    if application_id is not None:
        case = port(CasePort).lookup(session, application_id)
        port(AuthzPort).check(principal, "compliance.read", ResourceRef(
            "compliance", owner_institution_id=case.institution_id, region=case.region))
        return {"application_id": application_id}
    if principal.role == Role.INSTITUTION:
        port(AuthzPort).check(principal, "compliance.read",
                              ResourceRef("compliance", owner_institution_id=principal.institution_id))
        return {"institution_id": principal.institution_id}
    if region is None and principal.role == Role.RO_OFFICER:
        region = principal.region
    port(AuthzPort).check(principal, "compliance.read", ResourceRef("compliance", region=region))
    return {"region": region} if region is not None else {}


@router.post("/compliance/letters", response_model=LetterOut, status_code=status.HTTP_201_CREATED)
def register_letter(body: LetterRegisterIn, principal: Principal = Depends(current_principal),
                    key: str | None = Depends(idempotency_key)):
    letter = LetterIn(**body.model_dump())
    return idempotent_response(
        principal, key, "POST", "/compliance/letters", {}, body.model_dump(mode="json"),
        lambda uow: (uow.session, service.register_letter(uow, letter)),
        lambda r: _letter_out(*r).model_dump(mode="json"), status_code=201)


@router.get("/compliance/letters", response_model=list[LetterOut])
def list_letters(application_id: UUID | None = None, region: str | None = None,
                 principal: Principal = Depends(current_principal)):
    with new_session() as session:
        filters = _scope(session, principal, application_id, region)
        q = select(ApprovalLetter).filter_by(**filters).order_by(ApprovalLetter.issue_date.desc(), ApprovalLetter.id)
        return [_letter_out(session, a) for a in session.scalars(q).all()]


@router.get("/compliance/letters/{letter_id}", response_model=LetterOut)
def get_letter(letter_id: UUID, principal: Principal = Depends(current_principal)):
    with new_session() as session:
        a = session.get(ApprovalLetter, letter_id)
        if a is None:
            raise NotFound("letter not found")
        port(AuthzPort).check(principal, "compliance.read", service.resource(a))
        return _letter_out(session, a)


@router.get("/compliance/obligations", response_model=list[ObligationOut])
def list_obligations(application_id: UUID | None = None, region: str | None = None, status: str | None = None,
                     kind: ObligationKind | None = None, principal: Principal = Depends(current_principal)):
    with new_session() as session:
        filters = _scope(session, principal, application_id, region)
        q = select(Obligation).filter_by(**filters).order_by(Obligation.due_date.nulls_last(), Obligation.id)
        if status:
            q = q.where(Obligation.status == status)
        if kind:
            q = q.where(Obligation.kind == kind)
        obligations = session.scalars(q).all()
        # each row carries its evidence, as the single read does, so a list never shows "none submitted" for a met one
        evidence: dict[UUID, list[Evidence]] = {o.id: [] for o in obligations}
        if obligations:
            for e in session.scalars(select(Evidence).where(Evidence.obligation_id.in_(list(evidence)))
                                     .order_by(Evidence.submitted_at, Evidence.id)):
                evidence[e.obligation_id].append(e)
        clocks = _clocks(session, obligations)
        reading = _Reading(session, obligations)
        return [_obligation_out(o, reading, evidence[o.id], clocks.get(o.deadline_id)) for o in obligations]


@router.get("/compliance/obligations/{obligation_id}", response_model=ObligationOut)
def get_obligation(obligation_id: UUID, principal: Principal = Depends(current_principal)):
    with new_session() as session:
        o = session.get(Obligation, obligation_id)
        if o is None:
            raise NotFound("obligation not found")
        port(AuthzPort).check(principal, "compliance.read", service.resource(o))
        return _read_one(session, o)


@router.post("/compliance/obligations", response_model=ObligationOut, status_code=status.HTTP_201_CREATED)
def record_obligation(body: ObligationRecordIn, principal: Principal = Depends(current_principal),
                      key: str | None = Depends(idempotency_key)):
    """An officer records an undertaking (or another obligation) with its clause, due date or rule, and the
    evidence that meets it."""
    return idempotent_response(
        principal, key, "POST", "/compliance/obligations", {}, body.model_dump(mode="json"),
        lambda uow: (uow.session, service.record_obligation(uow, **body.model_dump())),
        lambda r: _read_one(*r).model_dump(mode="json"), status_code=201)


@router.post("/compliance/validity", response_model=ObligationOut, status_code=status.HTTP_201_CREATED)
def record_validity(body: ValidityRecordIn, principal: Principal = Depends(current_principal),
                    key: str | None = Depends(idempotency_key)):
    """An officer records the date a document version is valid until (or its issue date, for a document the APH
    gives a validity period); this opens its DOCUMENT_VALIDITY obligation."""
    return idempotent_response(
        principal, key, "POST", "/compliance/validity", {}, body.model_dump(mode="json"),
        lambda uow: (uow.session, validity.record_validity(uow, **body.model_dump())),
        lambda r: _read_one(*r).model_dump(mode="json"), status_code=201)


@router.post("/compliance/obligations/{obligation_id}/evidence", response_model=EvidenceOut,
             status_code=status.HTTP_201_CREATED)
def submit_evidence(obligation_id: UUID, body: EvidenceIn, principal: Principal = Depends(current_principal),
                    key: str | None = Depends(idempotency_key)):
    return idempotent_response(
        principal, key, "POST", "/compliance/obligations/{obligation_id}/evidence",
        {"obligation_id": str(obligation_id)}, body.model_dump(mode="json"),
        lambda uow: service.submit_evidence(uow, obligation_id, body.document_version_id),
        lambda e: _evidence_out(e).model_dump(mode="json"), status_code=201)


@router.get("/compliance/evidence/{evidence_id}/note", response_model=EvidenceNoteOut)
def read_evidence_note(evidence_id: UUID, principal: Principal = Depends(current_principal)):
    """The verifying officer's note. Officers who may verify this evidence and the owning institution only;
    auditors and other roles get 403 (they see has_note on the evidence)."""
    with new_session() as session:
        ev, note, redacted = service.read_evidence_note(session, principal, evidence_id)
        return EvidenceNoteOut(evidence_id=ev.id, has_note=ev.note_ref is not None, note=note, redacted=redacted,
                               verified_role=ev.verified_role, verified_at=_iso(ev.verified_at))


@router.post("/compliance/evidence/{evidence_id}/verify", response_model=EvidenceOut)
def verify_evidence(evidence_id: UUID, body: VerifyIn, principal: Principal = Depends(current_principal),
                    key: str | None = Depends(idempotency_key)):
    return idempotent_response(
        principal, key, "POST", "/compliance/evidence/{evidence_id}/verify",
        {"evidence_id": str(evidence_id)}, body.model_dump(mode="json"),
        lambda uow: service.verify_evidence(uow, evidence_id, body.decision, body.reason_code, body.note),
        lambda e: _evidence_out(e).model_dump(mode="json"))
