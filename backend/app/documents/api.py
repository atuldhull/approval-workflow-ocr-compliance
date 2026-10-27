"""Document endpoints: upload, scan, extraction, fact listing, review and confirmation.

Authorization and visibility live in service.py. Uploads need an
Idempotency-Key; review and confirm honour one when given. Nothing here ever
returns file bytes: there is no download endpoint yet.
"""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.documents import service
from app.documents.storage import StorageError
from app.documents.validation import UploadValidationError, safe_display_filename
from app.platform.auth import current_principal
from app.platform.db import new_session, unit_of_work
from app.platform.errors import ServiceUnavailable
from app.platform.idempotency import REPLAYED_HEADER, fingerprint, idempotency_key, idempotent_response, store
from contracts.errors import ValidationFailed
from contracts.types import Principal

router = APIRouter(tags=["documents"])

UPLOAD_ROUTE = "/applications/{application_id}/documents"
REVIEW_ROUTE = "/document-facts/{fact_id}/review"
CONFIRM_ROUTE = "/document-facts/{fact_id}/confirm"


class VersionOut(BaseModel):
    version_id: UUID
    document_id: UUID
    version_no: int
    original_filename: str
    media_type: str
    size_bytes: int
    sha256: str
    scan_status: Literal["scan_pending", "clean", "infected"]
    uploaded_at: str
    scanned_at: str | None


class DocumentOut(BaseModel):
    document_id: UUID
    application_id: UUID
    doc_type: str | None
    current_version_id: UUID | None  # newest version scanned clean
    versions: list[VersionOut]


class UploadOut(BaseModel):
    document_id: UUID
    doc_type: str | None
    created: bool  # False: the same file was already uploaded for this checklist item
    version: VersionOut


class ExtractionOut(BaseModel):
    ocr_run_id: UUID
    version_id: UUID
    status: str
    attempt_number: int
    error_code: str | None
    fact_ids: list[UUID]


class SuggestionOut(BaseModel):
    fact_id: UUID
    candidate_text: str
    normalized_value: str | None
    confidence: float
    normalization_status: str


class EntryIn(BaseModel):
    value: str = Field(min_length=1, max_length=1000, pattern=r"\S")


class ReviewIn(BaseModel):
    decision: Literal["ACCEPTED", "CORRECTED", "REJECTED"]
    value: str | None = Field(default=None, min_length=1, max_length=1000)
    note: str | None = Field(default=None, max_length=4000)


def _upload_body(result: service.UploadResult) -> dict:
    return {"document_id": str(result.document.document_id), "doc_type": result.document.doc_type,
            "created": result.created, "version": service.version_view(result.version)}


@router.post(UPLOAD_ROUTE, status_code=201, response_model=UploadOut,
             responses={200: {"model": UploadOut, "description": "same file already uploaded for this item"}})
def upload_document(application_id: UUID, background: BackgroundTasks, doc_type: str = Form(...),
                    file: UploadFile = File(...), principal: Principal = Depends(current_principal),
                    key: str | None = Depends(idempotency_key)):
    """Add a version of a checklist document. It stays in quarantine until the malware scan is clean."""
    if key is None:
        raise ValidationFailed("an Idempotency-Key header is required for document uploads")
    service.check_doc_type(doc_type)
    with new_session() as session:
        # refuse before any bytes are stored for a caller who may not upload here
        case = service.authorize(session, principal, "document.upload", application_id)
    storage = service.storage()
    try:
        staged = storage.stage(file.file, institution_id=case.institution_id, application_id=application_id)
    except UploadValidationError as exc:
        raise ValidationFailed(str(exc)) from None
    except StorageError as exc:
        raise ServiceUnavailable("document storage is unavailable") from exc

    filename = safe_display_filename(file.filename)
    # multipart bodies are fingerprinted by content hash and form fields, never by raw bytes
    request_hash = fingerprint({"application_id": str(application_id)},
                               {"sha256": staged.sha256, "filename": filename, "doc_type": doc_type})
    keep = replayed = created = False
    try:
        with unit_of_work(principal) as uow:
            replay = store.claim(uow, key, "POST", UPLOAD_ROUTE, request_hash)
            if replay is not None:
                status, body, replayed = replay.status_code, replay.body, True
            else:
                result = service.record_upload(uow, application_id=application_id, doc_type=doc_type,
                                               filename=filename, staged=staged)
                status, body = (201 if result.created else 200), _upload_body(result)
                store.complete(uow, key, "POST", UPLOAD_ROUTE, status, body)
                created = result.created
        keep = not replayed and created
    finally:
        if not keep:
            try:
                storage.abort(staged)  # duplicate, replay or rollback: this request's copy is not needed
            except StorageError:
                pass
    if keep:
        background.add_task(service.scan_after_upload, UUID(body["version"]["version_id"]))
    return JSONResponse(body, status_code=status, headers={REPLAYED_HEADER: "true"} if replayed else {})


@router.get("/applications/{application_id}/documents", response_model=list[DocumentOut])
def list_application_documents(application_id: UUID, principal: Principal = Depends(current_principal)):
    return service.list_application_documents(principal, application_id)


@router.get("/documents", response_model=list[DocumentOut])
def list_documents(region: str | None = None, doc_type: str | None = None,
                   principal: Principal = Depends(current_principal)):
    """Across applications. Institutions get their own; regional officers always their own region."""
    return service.list_documents(principal, region, doc_type)


@router.post("/document-versions/{version_id}/scan", response_model=VersionOut)
def scan_version(version_id: UUID, principal: Principal = Depends(current_principal)):
    """Scan (or rescan) a scan_pending version. 503 if the scanner cannot answer; nothing changes then."""
    return service.version_view(service.scan_version(principal, version_id))


@router.post("/document-versions/{version_id}/extract", response_model=ExtractionOut, status_code=201,
             responses={200: {"model": ExtractionOut, "description": "facts were already extracted"}})
def extract_facts(version_id: UUID, principal: Principal = Depends(current_principal)):
    """Extract proposed facts from a clean version. Returns ids and state only, after commit."""
    result = service.extract_facts(principal, version_id)
    run = result.run
    body = ExtractionOut(ocr_run_id=run.ocr_run_id, version_id=version_id, status=run.status,
                         attempt_number=run.attempt_number, error_code=run.error_code,
                         fact_ids=list(result.fact_ids))
    return JSONResponse(body.model_dump(mode="json"), status_code=201 if result.created else 200)


@router.get("/document-versions/{version_id}/facts")
def list_facts(version_id: UUID, principal: Principal = Depends(current_principal)):
    """Reviewers and oversight see proposals; institutions see confirmed values and review counts only."""
    return service.list_facts(principal, version_id)


def _suggestion(s) -> dict:
    return SuggestionOut(fact_id=s.fact_id, candidate_text=s.candidate_text, normalized_value=s.normalized_value,
                         confidence=s.confidence, normalization_status=s.normalization_status).model_dump(mode="json")


@router.post("/document-facts/{fact_id}/entry", response_model=SuggestionOut)
def enter_value(fact_id: UUID, body: EntryIn, principal: Principal = Depends(current_principal)):
    """Type before reveal: the reviewer's own reading commits first, then the OCR suggestion is returned."""
    with unit_of_work(principal) as uow:
        service.enter_review_value(uow, fact_id, body.value)
    with unit_of_work(principal) as uow:
        return _suggestion(service.reveal_for_reviewer(uow, fact_id))


@router.post("/document-facts/{fact_id}/reveal", response_model=SuggestionOut)
def reveal(fact_id: UUID, principal: Principal = Depends(current_principal)):
    """Show the suggestion again to the reviewer who already entered a value (e.g. after a lost response)."""
    with unit_of_work(principal) as uow:
        return _suggestion(service.reveal_for_reviewer(uow, fact_id))


@router.post(REVIEW_ROUTE)
def review_fact(fact_id: UUID, body: ReviewIn, principal: Principal = Depends(current_principal),
                key: str | None = Depends(idempotency_key)):
    return idempotent_response(
        principal, key, "POST", REVIEW_ROUTE, {"fact_id": str(fact_id)}, body.model_dump(mode="json"),
        lambda uow: service.review_fact(uow, fact_id, body.decision, body.value, body.note),
        lambda fact: service.fact_view(fact, principal))


@router.post(CONFIRM_ROUTE)
def confirm_fact(fact_id: UUID, principal: Principal = Depends(current_principal),
                 key: str | None = Depends(idempotency_key)):
    """A second officer confirms a reviewed value. The reviewer cannot confirm their own review (409)."""
    return idempotent_response(
        principal, key, "POST", CONFIRM_ROUTE, {"fact_id": str(fact_id)}, None,
        lambda uow: service.confirm_fact(uow, fact_id),
        lambda fact: service.fact_view(fact, principal))
