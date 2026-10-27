"""Document services: upload, malware scan, fact extraction, review and confirmation.

Every command runs in one unit of work with its ledger event, so the state
change and its doc.* event commit or roll back together. Authorization always
uses a ResourceRef built from the owning application (CasePort), never from
request fields. Event payloads carry identifiers, hashes and verdicts only.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.documents.config import DocumentConfigurationError
from app.documents.extraction import TextEngine, TextEngineError, candidate_confidence, candidate_script
from app.documents.candidates import extract_field_candidates
from app.documents.facts import mark_conflicting_candidates, propose_fact
from app.documents.models import Document, DocumentVersion, Fact, OcrRun
from app.documents.ocr import enqueue_retry, make_ocr_run, transition_ocr_run
from app.documents.ownership import resolve_document_owner
from app.documents.review import RevealedSuggestion, enter_value_before_reveal, finalize_review, reveal_suggestion
from app.documents.scanning import (SIGNATURE_PATTERN, ClamdScanner, MalwareScanner, ScannerUnavailable,
                                    ScanVerdict)
from app.documents.states import OcrErrorCode, OcrRunStatus
from app.documents.storage import (DocumentStorage, LocalQuarantineStorage, StagedObject,
                                   StorageConfigurationError, StorageError)
from app.platform.db import new_session, unit_of_work
from app.platform.errors import ServiceUnavailable
from app.platform.registry import port
from contracts.enums import FactState, Role
from contracts.errors import Conflict, Forbidden, NotFound, ValidationFailed
from contracts.ports import AuthzPort, ClockPort, LedgerPort, NotesPort, UnitOfWork
from contracts.types import CaseRef, EventIn, Principal, ResourceRef

DOC_TYPE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
SYSTEM = Principal(UUID(int=0), Role.SYSTEM)  # actor for scans started automatically after an upload

REVIEWERS = frozenset({Role.SCRUTINY_COMMITTEE, Role.RO_OFFICER})
# Review decisions as the API and doc.fact_reviewed name them, and the stored FactState they map to.
DECISIONS = {"ACCEPTED": FactState.CONFIRMED, "CORRECTED": FactState.CORRECTED, "REJECTED": FactState.REJECTED}
DECISION_OF_STATE = {state.value: name for name, state in DECISIONS.items()}


class FourEyesViolation(Conflict):
    """The officer who reviewed a fact may not also confirm it."""


# ---- replaceable adapters (tests and deployments call configure()) ----

_UNSET: Any = object()
_storage: DocumentStorage | None = None
_scanner: MalwareScanner | None = None
_engine: TextEngine | None = None


def configure(*, storage: DocumentStorage | None = _UNSET, scanner: MalwareScanner | None = _UNSET,
              engine: TextEngine | None = _UNSET) -> None:
    """Install adapters; None restores the default for that slot."""
    global _storage, _scanner, _engine
    if storage is not _UNSET:
        _storage = storage
    if scanner is not _UNSET:
        _scanner = scanner
    if engine is not _UNSET:
        _engine = engine


def storage() -> DocumentStorage:
    global _storage
    if _storage is None:
        try:
            _storage = LocalQuarantineStorage.from_environment()
        except (StorageConfigurationError, DocumentConfigurationError) as exc:
            raise ServiceUnavailable(f"document storage is not configured: {exc}") from None
    return _storage


def scanner() -> MalwareScanner:
    global _scanner
    if _scanner is None:
        try:
            _scanner = ClamdScanner.from_environment()
        except ValueError as exc:
            raise ServiceUnavailable(f"malware scanner is not configured: {exc}") from None
    return _scanner


def engine() -> TextEngine:
    if _engine is None:
        raise ServiceUnavailable("no text engine is configured, so facts cannot be extracted yet")
    return _engine


# ---- ownership and authorization ----

def authorize(session: Session, principal: Principal, action: str, application_id: UUID,
              document_id: UUID | None = None) -> CaseRef:
    case = resolve_document_owner(session, application_id)
    port(AuthzPort).check(principal, action, ResourceRef(
        type="document", id=document_id, owner_institution_id=case.institution_id, region=case.region))
    return case


def _now():
    return port(ClockPort).now()


def value_hash(value: str | None) -> str:
    """sha256 of a reviewed value; a rejection (no value) hashes the empty string."""
    return sha256((value or "").encode("utf-8")).hexdigest()


def _event(uow: UnitOfWork, document_id: UUID, event_type: str, payload: dict[str, Any],
           note_ref: UUID | None = None, note_hash: str | None = None) -> None:
    port(LedgerPort).append(uow, EventIn(aggregate_type="document", aggregate_id=document_id,
                                         event_type=event_type, payload=payload,
                                         note_ref=note_ref, note_hash=note_hash))


def _version_for_update(session: Session, version_id: UUID) -> DocumentVersion:
    version = session.scalars(select(DocumentVersion).where(DocumentVersion.document_version_id == version_id)
                              .with_for_update()).one_or_none()
    if version is None:
        raise NotFound("document version not found")
    return version


def _fact_for_update(session: Session, fact_id: UUID) -> tuple[Fact, DocumentVersion]:
    fact = session.scalars(select(Fact).where(Fact.fact_id == fact_id).with_for_update()).one_or_none()
    if fact is None:
        raise NotFound("fact not found")
    return fact, session.get(DocumentVersion, fact.document_version_id)


# ---- upload ----

def check_doc_type(doc_type: str) -> str:
    if not isinstance(doc_type, str) or not DOC_TYPE.fullmatch(doc_type):
        raise ValidationFailed("doc_type must be a checklist item code such as LAND_DEED (A-Z, 0-9, _)")
    return doc_type


@dataclass(frozen=True)
class UploadResult:
    document: Document
    version: DocumentVersion
    created: bool  # False: the same bytes were already uploaded for this item; nothing was added


def record_upload(uow: UnitOfWork, *, application_id: UUID, doc_type: str, filename: str,
                  staged: StagedObject) -> UploadResult:
    """Add version n+1 of (application, doc_type), or return the version that already has these bytes."""
    session = uow.session
    check_doc_type(doc_type)
    case = authorize(session, uow.principal, "document.upload", application_id)
    now = _now()
    session.execute(pg_insert(Document).values(
        document_id=uuid4(), application_id=application_id, institution_id=case.institution_id,
        doc_type=doc_type, created_at=now, updated_at=now,
    ).on_conflict_do_nothing(constraint="uq_doc_document_application_doc_type"))
    # The document row lock serialises version numbering and duplicate detection per checklist item.
    document = session.scalars(select(Document).where(
        Document.application_id == application_id, Document.doc_type == doc_type).with_for_update()).one()

    existing = session.scalars(select(DocumentVersion).where(
        DocumentVersion.application_id == application_id,
        DocumentVersion.institution_id == case.institution_id,
        DocumentVersion.sha256 == staged.sha256)).one_or_none()
    if existing is not None:
        if existing.document_id != document.document_id:
            raise Conflict("this file is already uploaded for this application under another checklist item")
        return UploadResult(document, existing, created=False)

    last = session.scalar(select(func.max(DocumentVersion.version_no))
                          .where(DocumentVersion.document_id == document.document_id)) or 0
    version = DocumentVersion(
        document_version_id=uuid4(), document_id=document.document_id, application_id=application_id,
        institution_id=case.institution_id, version_no=last + 1, original_filename=filename,
        media_type=staged.media_type, size_bytes=staged.size_bytes, sha256=staged.sha256,
        storage_ref=staged.storage_ref, status="QUARANTINED", scan_status="scan_pending",
        uploaded_by=uow.principal.user_id, created_at=now, updated_at=now,
    )
    session.add(version)
    document.updated_at = now
    session.flush()
    _event(uow, document.document_id, "doc.document_uploaded", {
        "document_id": str(document.document_id), "version_id": str(version.document_version_id),
        "version_no": version.version_no, "application_id": str(application_id),
        "institution_id": str(case.institution_id), "doc_type": doc_type, "sha256": version.sha256,
        "size_bytes": version.size_bytes, "media_type": version.media_type,
    })
    return UploadResult(document, version, created=True)


# ---- malware scan ----

def scan_version(principal: Principal, version_id: UUID) -> DocumentVersion:
    """Scan a scan_pending version and record the verdict; other versions are returned unchanged.

    The scanner is called outside any transaction. If it cannot answer, nothing
    changes (the version stays scan_pending and unserved) and 503 is raised.
    """
    with new_session() as session:
        version = session.get(DocumentVersion, version_id)
        if version is None:
            raise NotFound("document version not found")
        if principal.role != Role.SYSTEM:
            authorize(session, principal, "document.upload", version.application_id, version.document_id)
        if version.scan_status != "scan_pending":
            return version
        storage_ref = version.storage_ref

    engine_ = scanner()
    try:
        with storage().open_private(storage_ref) as source:
            result = engine_.scan(source)
    except (ScannerUnavailable, StorageError) as exc:
        raise ServiceUnavailable("malware scanner unavailable; the version stays scan_pending") from exc

    with unit_of_work(principal) as uow:
        version = _version_for_update(uow.session, version_id)
        if version.scan_status != "scan_pending":
            return version  # a concurrent scan recorded its verdict first
        now = _now()
        version.scanned_at = now
        version.updated_at = now
        payload: dict[str, Any] = {
            "document_id": str(version.document_id), "version_id": str(version.document_version_id),
            "sha256": version.sha256, "verdict": result.verdict.value, "scanner": engine_.scanner_key,
        }
        if result.verdict is ScanVerdict.CLEAN:
            version.scan_status, version.status = "clean", "AVAILABLE"
        else:
            version.scan_status, version.status = "infected", "REJECTED"
            version.scan_signature = (result.signature or "unknown")[:200]
            if SIGNATURE_PATTERN.fullmatch(version.scan_signature):
                payload["signature"] = version.scan_signature
        uow.session.flush()
        _event(uow, version.document_id, "doc.document_scanned", payload)
    return version


def scan_after_upload(version_id: UUID) -> None:
    """Background step after an upload commits. Failure leaves the version scan_pending (fail closed)."""
    try:
        scan_version(SYSTEM, version_id)
    except ServiceUnavailable:
        pass


# ---- fact extraction ----

@dataclass(frozen=True)
class ExtractionResult:
    run: OcrRun
    fact_ids: tuple[UUID, ...]
    created: bool


def _build_facts(run: OcrRun, version: DocumentVersion, pages, at) -> list[Fact]:
    facts: list[Fact] = []
    for page in pages:
        for candidate in extract_field_candidates(
                page_text=page.text, tokens=page.tokens, page_number=page.page_number,
                ocr_run_id=run.ocr_run_id, document_version_id=version.document_version_id):
            facts.append(propose_fact(
                ocr_run_id=run.ocr_run_id, document_version_id=version.document_version_id,
                field_key=candidate.field_key, value=candidate.value,
                script=candidate_script(candidate.source_tokens),
                confidence=candidate_confidence(candidate.source_tokens), page_number=candidate.page_number,
                source_span_start=candidate.source_span_start, source_span_end=candidate.source_span_end,
                created_at=at,
            ))
    by_field: dict[str, list[Fact]] = defaultdict(list)
    for fact in facts:
        by_field[fact.field_key].append(fact)
    for group in by_field.values():
        if len(group) > 1:
            mark_conflicting_candidates(group)
    return facts


def extract_facts(principal: Principal, version_id: UUID) -> ExtractionResult:
    """Run text extraction on a CLEAN version and store proposed facts.

    Commit before reveal: the caller gets only ids and the run state, and only
    after this transaction has committed. A version that already has a
    successful run returns it unchanged; a failed run is retried as a linked attempt.
    """
    text_engine = engine()
    with unit_of_work(principal) as uow:
        session = uow.session
        version = _version_for_update(session, version_id)
        authorize(session, principal, "document.fact.review", version.application_id, version.document_id)
        if version.scan_status != "clean":
            raise Conflict("facts are only extracted from a version that was scanned clean")
        latest = session.scalars(select(OcrRun).where(OcrRun.document_version_id == version_id)
                                 .order_by(OcrRun.attempt_number.desc()).limit(1)).one_or_none()
        if latest is not None and latest.status == OcrRunStatus.SUCCEEDED.value:
            fact_ids = session.scalars(select(Fact.fact_id).where(Fact.ocr_run_id == latest.ocr_run_id)).all()
            return ExtractionResult(latest, tuple(fact_ids), created=False)
        now = _now()
        if latest is None:
            run = make_ocr_run(document_version_id=version_id, adapter_key=text_engine.adapter_key,
                               model_version=text_engine.model_version, created_at=now)
            session.add(run)
        elif latest.status == OcrRunStatus.FAILED.value:
            run = enqueue_retry(session, latest, created_at=now)
        else:
            raise Conflict("an extraction for this version is already in progress")
        session.flush()
        transition_ocr_run(run, OcrRunStatus.RUNNING, at=now)
        session.flush()

        error: OcrErrorCode | None = None
        facts: list[Fact] = []
        try:
            with storage().open_private(version.storage_ref) as source:
                content = source.read()
            facts = _build_facts(run, version, text_engine.read(content, media_type=version.media_type), now)
        except TextEngineError as exc:
            error = exc.code
        except StorageError:
            error = OcrErrorCode.INPUT_REJECTED
        except ValueError:
            # malformed engine output (spans, tokens); no partial batch is kept
            error = OcrErrorCode.PROCESSING_FAILED
        if error is not None:
            transition_ocr_run(run, OcrRunStatus.FAILED, at=now, error_code=error)
            session.flush()
            return ExtractionResult(run, (), created=True)

        transition_ocr_run(run, OcrRunStatus.SUCCEEDED, at=now)
        session.flush()  # facts need a SUCCEEDED run (database trigger)
        session.add_all(facts)
        session.flush()
        return ExtractionResult(run, tuple(f.fact_id for f in facts), created=True)


# ---- fact visibility ----

def fact_status(fact: Fact) -> str:
    if fact.confirmed_at is not None:
        return "confirmed"
    if fact.state == FactState.REJECTED.value:
        return "rejected"
    if fact.state in (FactState.CONFIRMED.value, FactState.CORRECTED.value):
        return "reviewed"
    if fact.review_typed_at is not None:
        return "in_review"
    return "proposed"


def _suggestion_visible(fact: Fact, principal: Principal) -> bool:
    """Type before reveal: a reviewer sees the OCR value only after entering their own."""
    if principal.role not in REVIEWERS or fact.state != FactState.PROPOSED.value:
        return True
    return fact.suggestion_revealed_at is not None and fact.review_typed_by == principal.user_id


def fact_view(fact: Fact, principal: Principal) -> dict[str, Any]:
    status = fact_status(fact)
    if principal.role == Role.INSTITUTION:
        # institutions see confirmed values only, never raw OCR proposals
        return {"fact_id": str(fact.fact_id), "field_key": fact.field_key, "status": status,
                "value": fact.reviewed_value, "page_number": fact.page_number,
                "confirmed_at": fact.confirmed_at.isoformat()}
    visible = _suggestion_visible(fact, principal)
    return {
        "fact_id": str(fact.fact_id), "field_key": fact.field_key, "status": status,
        "review_decision": DECISION_OF_STATE.get(fact.state), "ocr_run_id": str(fact.ocr_run_id),
        "page_number": fact.page_number, "source_span_start": fact.source_span_start,
        "source_span_end": fact.source_span_end, "script_code": fact.script_code,
        "normalization_status": fact.normalization_status, "conflict_group_id":
            str(fact.conflict_group_id) if fact.conflict_group_id else None,
        "suggestion_visible": visible,
        "candidate_text": fact.candidate_text if visible else None,
        "normalized_value": fact.normalized_value if visible else None,
        "confidence": float(fact.confidence) if visible else None,
        "reviewed_value": fact.reviewed_value,
        "reviewed_by": str(fact.review_typed_by) if fact.reviewed_at else None,
        "reviewed_at": fact.reviewed_at.isoformat() if fact.reviewed_at else None,
        "confirmed_by": str(fact.confirmed_by) if fact.confirmed_by else None,
        "confirmed_at": fact.confirmed_at.isoformat() if fact.confirmed_at else None,
    }


def list_facts(principal: Principal, version_id: UUID) -> dict[str, Any]:
    with new_session() as session:
        version = session.get(DocumentVersion, version_id)
        if version is None:
            raise NotFound("document version not found")
        authorize(session, principal, "document.facts.read", version.application_id, version.document_id)
        facts = session.scalars(select(Fact).where(Fact.document_version_id == version_id)
                                .order_by(Fact.page_number, Fact.source_span_start, Fact.fact_id)).all()
        if version.scan_status != "clean":
            facts = []
        summary = {s: 0 for s in ("proposed", "in_review", "reviewed", "rejected", "confirmed")}
        for fact in facts:
            summary[fact_status(fact)] += 1
        shown = [f for f in facts if principal.role != Role.INSTITUTION or f.confirmed_at is not None]
        return {"document_version_id": str(version_id), "document_id": str(version.document_id),
                "review_status": summary, "facts": [fact_view(f, principal) for f in shown]}


def confirmed_facts(session: Session, application_id: UUID) -> list[Fact]:
    """The only facts other modules (deadlines, compliance) may act on."""
    return list(session.scalars(
        select(Fact).join(DocumentVersion, DocumentVersion.document_version_id == Fact.document_version_id)
        .where(DocumentVersion.application_id == application_id, Fact.confirmed_at.is_not(None))
        .order_by(Fact.confirmed_at)).all())


# ---- review and confirmation ----

def _review_target(uow: UnitOfWork, fact_id: UUID, action: str) -> tuple[Fact, DocumentVersion]:
    fact, version = _fact_for_update(uow.session, fact_id)
    authorize(uow.session, uow.principal, action, version.application_id, version.document_id)
    return fact, version


def enter_review_value(uow: UnitOfWork, fact_id: UUID, value: str) -> Fact:
    """Step 1: record the reviewer's own reading. Repeating the same entry is a no-op."""
    fact, _ = _review_target(uow, fact_id, "document.fact.review")
    if (fact.review_typed_by == uow.principal.user_id and fact.review_typed_value == value.strip()
            and fact.state == FactState.PROPOSED.value):
        return fact
    try:
        enter_value_before_reveal(fact, reviewer_id=uow.principal.user_id, value=value, at=_now())
    except ValueError as exc:
        raise Conflict(str(exc)) from None
    uow.session.flush()
    return fact


def reveal_for_reviewer(uow: UnitOfWork, fact_id: UUID) -> RevealedSuggestion:
    """Step 2, in its own transaction after step 1 has committed: show the OCR suggestion."""
    fact, _ = _review_target(uow, fact_id, "document.fact.review")
    if fact.review_typed_by != uow.principal.user_id:
        raise Forbidden("only the officer who entered a value for this fact may see its suggestion")
    try:
        suggestion = reveal_suggestion(fact, at=_now())
    except ValueError as exc:
        raise Conflict(str(exc)) from None
    uow.session.flush()
    return suggestion


def review_fact(uow: UnitOfWork, fact_id: UUID, decision: str, value: str | None = None,
                note: str | None = None) -> Fact:
    """Step 3: ACCEPTED, CORRECTED or REJECTED, with its doc.fact_reviewed event."""
    if decision not in DECISIONS:
        raise ValidationFailed("decision must be ACCEPTED, CORRECTED or REJECTED")
    fact, version = _review_target(uow, fact_id, "document.fact.review")
    try:
        finalize_review(fact, reviewer_id=uow.principal.user_id, decision=DECISIONS[decision], at=_now(),
                        reviewed_value=value)
    except ValueError as exc:
        raise Conflict(str(exc)) from None
    uow.session.flush()
    payload = {"fact_id": str(fact.fact_id), "document_id": str(version.document_id),
               "version_id": str(version.document_version_id), "field": fact.field_key,
               "decision": decision, "value_hash": value_hash(fact.reviewed_value)}
    note_ref = note_hash = None
    if note is not None and note.strip():
        note_ref, note_hash = port(NotesPort).create(uow, note.strip())
        payload["note_hash"] = note_hash
    _event(uow, version.document_id, "doc.fact_reviewed", payload, note_ref=note_ref, note_hash=note_hash)
    return fact


def confirm_fact(uow: UnitOfWork, fact_id: UUID) -> Fact:
    """Step 4: a second officer confirms an accepted or corrected value (four-eyes)."""
    fact, version = _review_target(uow, fact_id, "document.fact.confirm")
    if fact.confirmed_at is not None:
        raise Conflict("this fact is already confirmed")
    if fact.state == FactState.REJECTED.value:
        raise Conflict("a rejected fact cannot be confirmed")
    if fact.state == FactState.PROPOSED.value:
        raise Conflict("a fact must be reviewed before it can be confirmed")
    if fact.review_typed_by == uow.principal.user_id:
        raise FourEyesViolation("the officer who reviewed this fact cannot also confirm it; "
                                "another officer must confirm")
    now = _now()
    if fact.reviewed_at is not None and now < fact.reviewed_at:
        now = fact.reviewed_at
    fact.confirmed_by = uow.principal.user_id
    fact.confirmed_at = now
    uow.session.flush()
    _event(uow, version.document_id, "doc.fact_confirmed", {
        "fact_id": str(fact.fact_id), "document_id": str(version.document_id),
        "version_id": str(version.document_version_id), "application_id": str(version.application_id),
        "field": fact.field_key, "value_hash": value_hash(fact.reviewed_value),
    })
    return fact


# ---- listing ----

def version_view(version: DocumentVersion) -> dict[str, Any]:
    return {"version_id": str(version.document_version_id), "document_id": str(version.document_id),
            "version_no": version.version_no, "original_filename": version.original_filename,
            "media_type": version.media_type, "size_bytes": version.size_bytes, "sha256": version.sha256,
            "scan_status": version.scan_status, "uploaded_at": version.created_at.isoformat(),
            "scanned_at": version.scanned_at.isoformat() if version.scanned_at else None}


def document_view(document: Document, versions: list[DocumentVersion]) -> dict[str, Any]:
    ordered = sorted(versions, key=lambda v: v.version_no, reverse=True)
    current = next((v for v in ordered if v.scan_status == "clean"), None)
    return {"document_id": str(document.document_id), "application_id": str(document.application_id),
            "doc_type": document.doc_type,
            "current_version_id": str(current.document_version_id) if current else None,
            "versions": [version_view(v) for v in ordered]}


def _documents_with_versions(session: Session, documents: list[Document]) -> list[dict[str, Any]]:
    if not documents:
        return []
    versions: dict[UUID, list[DocumentVersion]] = defaultdict(list)
    for v in session.scalars(select(DocumentVersion).where(
            DocumentVersion.document_id.in_([d.document_id for d in documents]))).all():
        versions[v.document_id].append(v)
    return [document_view(d, versions[d.document_id]) for d in documents]


def list_application_documents(principal: Principal, application_id: UUID) -> list[dict[str, Any]]:
    with new_session() as session:
        authorize(session, principal, "document.facts.read", application_id)
        documents = session.scalars(select(Document).where(Document.application_id == application_id)
                                    .order_by(Document.doc_type, Document.created_at)).all()
        return _documents_with_versions(session, list(documents))


def list_documents(principal: Principal, region: str | None = None,
                   doc_type: str | None = None) -> list[dict[str, Any]]:
    """Documents across applications. Regional officers only ever get their own region."""
    if principal.role == Role.RO_OFFICER and region is None:
        region = principal.region
    port(AuthzPort).check(principal, "document.facts.read", ResourceRef(
        type="document", owner_institution_id=principal.institution_id, region=region))
    with new_session() as session:
        q = select(Document).where(Document.doc_type.is_not(None))
        if principal.role == Role.INSTITUTION:
            q = q.where(Document.institution_id == principal.institution_id)
        if doc_type is not None:
            q = q.where(Document.doc_type == check_doc_type(doc_type))
        documents = list(session.scalars(q.order_by(Document.created_at, Document.document_id)).all())
        if region is not None:
            regions: dict[UUID, str] = {}
            for d in documents:
                if d.application_id not in regions:
                    regions[d.application_id] = resolve_document_owner(session, d.application_id).region
            documents = [d for d in documents if regions[d.application_id] == region]
        return _documents_with_versions(session, documents)
