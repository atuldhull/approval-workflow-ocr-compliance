from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.compliance import service
from app.compliance.models import ApprovalLetter, Evidence, Obligation
from app.platform.auth import current_principal
from app.platform.db import new_session
from app.platform.idempotency import idempotency_key, idempotent_response
from app.platform.registry import port
from contracts.enums import LetterType, ObligationKind, Role
from contracts.errors import NotFound
from contracts.ports import AuthzPort, CasePort
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


def _obligation_out(o: Obligation, evidence: list[Evidence] = ()) -> ObligationOut:
    return ObligationOut(
        id=o.id, application_id=o.application_id, institution_id=o.institution_id, region=o.region, kind=o.kind,
        source_letter_id=o.source_letter_id, source_clause=o.source_clause, source_status=o.source_status,
        state_origin=o.state_origin, rule_id=o.rule_id, deadline_id=o.deadline_id, due_date=_iso(o.due_date),
        status=o.status, met_at=_iso(o.met_at), evidence=[_evidence_out(e) for e in evidence],
    )


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
                     principal: Principal = Depends(current_principal)):
    with new_session() as session:
        filters = _scope(session, principal, application_id, region)
        q = select(Obligation).filter_by(**filters).order_by(Obligation.due_date.nulls_last(), Obligation.id)
        if status:
            q = q.where(Obligation.status == status)
        return [_obligation_out(o) for o in session.scalars(q).all()]


@router.get("/compliance/obligations/{obligation_id}", response_model=ObligationOut)
def get_obligation(obligation_id: UUID, principal: Principal = Depends(current_principal)):
    with new_session() as session:
        o = session.get(Obligation, obligation_id)
        if o is None:
            raise NotFound("obligation not found")
        port(AuthzPort).check(principal, "compliance.read", service.resource(o))
        evidence = session.scalars(select(Evidence).where(Evidence.obligation_id == o.id)
                                   .order_by(Evidence.submitted_at, Evidence.id)).all()
        return _obligation_out(o, evidence)


@router.post("/compliance/obligations/{obligation_id}/evidence", response_model=EvidenceOut,
             status_code=status.HTTP_201_CREATED)
def submit_evidence(obligation_id: UUID, body: EvidenceIn, principal: Principal = Depends(current_principal),
                    key: str | None = Depends(idempotency_key)):
    return idempotent_response(
        principal, key, "POST", "/compliance/obligations/{obligation_id}/evidence",
        {"obligation_id": str(obligation_id)}, body.model_dump(mode="json"),
        lambda uow: service.submit_evidence(uow, obligation_id, body.document_version_id),
        lambda e: _evidence_out(e).model_dump(mode="json"), status_code=201)


@router.post("/compliance/evidence/{evidence_id}/verify", response_model=EvidenceOut)
def verify_evidence(evidence_id: UUID, body: VerifyIn, principal: Principal = Depends(current_principal),
                    key: str | None = Depends(idempotency_key)):
    return idempotent_response(
        principal, key, "POST", "/compliance/evidence/{evidence_id}/verify",
        {"evidence_id": str(evidence_id)}, body.model_dump(mode="json"),
        lambda uow: service.verify_evidence(uow, evidence_id, body.decision, body.reason_code, body.note),
        lambda e: _evidence_out(e).model_dump(mode="json"))
