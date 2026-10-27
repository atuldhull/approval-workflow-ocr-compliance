"""Person 2-owned document metadata. Uploaded versions retain immutable provenance."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.db import Base
from app.documents.states import OcrRunStatus
from contracts.enums import FactState

SCHEMA = "doc"


class Document(Base):
    __tablename__ = "document"
    __table_args__ = (
        UniqueConstraint(
            "document_id", "application_id", "institution_id", name="uq_doc_document_owner_scope"
        ),
        UniqueConstraint("application_id", "doc_type", name="uq_doc_document_application_doc_type"),
        CheckConstraint("doc_type IS NULL OR doc_type ~ '^[A-Z][A-Z0-9_]*$'", name="ck_doc_document_doc_type"),
        Index("ix_doc_document_application_id", "application_id", "document_id"),
        {"schema": SCHEMA},
    )

    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wf.application.id", ondelete="RESTRICT"), nullable=False
    )
    institution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wf.institution.id", ondelete="RESTRICT"), nullable=False
    )
    # Checklist item code; one document per (application, doc_type), each upload a new version.
    doc_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DocumentVersion(Base):
    __tablename__ = "document_version"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_id", "application_id", "institution_id"],
            ["doc.document.document_id", "doc.document.application_id", "doc.document.institution_id"],
            ondelete="RESTRICT",
            name="fk_doc_version_document_owner_scope",
        ),
        UniqueConstraint("document_id", "version_no", name="uq_doc_version_document_version_no"),
        UniqueConstraint(
            "application_id", "institution_id", "sha256", name="uq_doc_version_owner_application_sha256"
        ),
        UniqueConstraint("storage_ref", name="uq_doc_version_storage_ref"),
        CheckConstraint("version_no > 0", name="ck_doc_version_positive_version"),
        CheckConstraint("size_bytes > 0", name="ck_doc_version_nonempty_size"),
        CheckConstraint(
            "media_type IN ('application/pdf', 'image/png', 'image/jpeg')",
            name="ck_doc_version_supported_media_type",
        ),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_doc_version_sha256_hex"),
        CheckConstraint("status IN ('QUARANTINED', 'AVAILABLE', 'REJECTED')", name="ck_doc_version_status"),
        CheckConstraint("scan_status IN ('scan_pending', 'clean', 'infected')", name="ck_doc_version_scan_status"),
        CheckConstraint(
            "(scan_status = 'scan_pending' AND status IN ('QUARANTINED', 'REJECTED') "
            "AND scanned_at IS NULL AND scan_signature IS NULL) OR "
            "(scan_status = 'clean' AND status = 'AVAILABLE' AND scanned_at IS NOT NULL "
            "AND scan_signature IS NULL) OR "
            "(scan_status = 'infected' AND status = 'REJECTED' AND scanned_at IS NOT NULL)",
            name="ck_doc_version_scan_consistency",
        ),
        Index("ix_doc_version_application_created", "application_id", "created_at"),
        Index("ix_doc_version_status_created", "status", "created_at"),
        {"schema": SCHEMA},
    )

    document_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    application_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_ref: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="QUARANTINED", server_default=text("'QUARANTINED'")
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    scan_status: Mapped[str] = mapped_column(
        Text, nullable=False, default="scan_pending", server_default=text("'scan_pending'")
    )
    scan_signature: Mapped[str | None] = mapped_column(String(200), nullable=True)
    scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OcrRun(Base):
    """One immutable OCR attempt, with a linked row for every retry."""

    __tablename__ = "ocr_run"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_version_id"],
            ["doc.document_version.document_version_id"],
            ondelete="RESTRICT",
            name="fk_doc_ocr_run_document_version",
        ),
        ForeignKeyConstraint(
            ["retry_of_ocr_run_id"], ["doc.ocr_run.ocr_run_id"],
            ondelete="RESTRICT", name="fk_doc_ocr_run_retry_of",
        ),
        UniqueConstraint("ocr_run_id", "document_version_id", name="uq_doc_ocr_run_identity_version"),
        UniqueConstraint("retry_of_ocr_run_id", name="uq_doc_ocr_run_single_retry"),
        UniqueConstraint("document_version_id", "attempt_number", name="uq_doc_ocr_run_version_attempt"),
        CheckConstraint("length(btrim(adapter_key)) > 0", name="ck_doc_ocr_run_adapter_key"),
        CheckConstraint("attempt_number > 0", name="ck_doc_ocr_run_positive_attempt"),
        CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED')",
            name="ck_doc_ocr_run_status",
        ),
        CheckConstraint(
            "error_code IS NULL OR error_code IN "
            "('ADAPTER_UNAVAILABLE', 'UNSUPPORTED_SCRIPT', 'INPUT_REJECTED', "
            "'PROCESSING_FAILED', 'TIMEOUT', 'RESOURCE_LIMIT', 'UNKNOWN')",
            name="ck_doc_ocr_run_error_code",
        ),
        CheckConstraint(
            "(status = 'QUEUED' AND started_at IS NULL AND finished_at IS NULL AND error_code IS NULL) "
            "OR (status = 'RUNNING' AND started_at IS NOT NULL AND finished_at IS NULL AND error_code IS NULL) "
            "OR (status = 'SUCCEEDED' AND started_at IS NOT NULL AND finished_at IS NOT NULL AND error_code IS NULL) "
            "OR (status = 'FAILED' AND finished_at IS NOT NULL AND error_code IS NOT NULL "
            "AND (started_at IS NULL OR started_at <= finished_at))",
            name="ck_doc_ocr_run_status_timestamps",
        ),
        Index("ix_doc_ocr_run_version_created", "document_version_id", "created_at"),
        {"schema": SCHEMA},
    )

    ocr_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    adapter_key: Mapped[str] = mapped_column(String(100), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default=OcrRunStatus.QUEUED.value, server_default=text("'QUEUED'")
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    retry_of_ocr_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Fact(Base):
    """A proposed field candidate tied to one OCR run and immutable source span."""

    __tablename__ = "fact"
    __table_args__ = (
        ForeignKeyConstraint(
            ["ocr_run_id", "document_version_id"],
            ["doc.ocr_run.ocr_run_id", "doc.ocr_run.document_version_id"],
            ondelete="RESTRICT",
            name="fk_doc_fact_run_version",
        ),
        CheckConstraint("page_number > 0", name="ck_doc_fact_positive_page"),
        CheckConstraint(
            "source_span_start >= 0 AND source_span_end > source_span_start",
            name="ck_doc_fact_source_span",
        ),
        CheckConstraint("length(btrim(candidate_text)) > 0", name="ck_doc_fact_candidate_nonempty"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_doc_fact_confidence_range"),
        CheckConstraint(
            "script_code IN ('LATIN', 'DEVANAGARI', 'BENGALI', 'GUJARATI', 'GURMUKHI', "
            "'KANNADA', 'MALAYALAM', 'ODIA', 'TAMIL', 'TELUGU', 'MIXED', 'UNKNOWN', 'UNSUPPORTED')",
            name="ck_doc_fact_script_code",
        ),
        CheckConstraint(
            "normalization_status IN ('NORMALIZED', 'AMBIGUOUS', 'INVALID', 'UNSUPPORTED', 'NOT_APPLICABLE')",
            name="ck_doc_fact_normalization_status",
        ),
        CheckConstraint(
            "(normalization_status IN ('NORMALIZED', 'NOT_APPLICABLE') AND normalized_value IS NOT NULL) OR "
            "(normalization_status IN ('AMBIGUOUS', 'INVALID', 'UNSUPPORTED') AND normalized_value IS NULL)",
            name="ck_doc_fact_normalization_value",
        ),
        CheckConstraint("length(btrim(field_key)) > 0", name="ck_doc_fact_field_key"),
        CheckConstraint(
            "state IN ('PROPOSED', 'CONFIRMED', 'CORRECTED', 'REJECTED')",
            name="ck_doc_fact_state",
        ),
        CheckConstraint(
            "(review_typed_value IS NULL AND review_typed_by IS NULL AND review_typed_at IS NULL "
            "AND suggestion_revealed_at IS NULL) OR "
            "(review_typed_value IS NOT NULL AND length(btrim(review_typed_value)) > 0 "
            "AND review_typed_by IS NOT NULL AND review_typed_at IS NOT NULL "
            "AND review_typed_at >= created_at "
            "AND (suggestion_revealed_at IS NULL OR suggestion_revealed_at >= review_typed_at))",
            name="ck_doc_fact_review_entry_order",
        ),
        CheckConstraint(
            "(state = 'PROPOSED' AND reviewed_value IS NULL AND reviewed_at IS NULL) OR "
            "(state = 'CONFIRMED' AND suggestion_revealed_at IS NOT NULL AND reviewed_at IS NOT NULL "
            "AND normalized_value IS NOT NULL AND reviewed_value = normalized_value) OR "
            "(state = 'CORRECTED' AND suggestion_revealed_at IS NOT NULL AND reviewed_at IS NOT NULL "
            "AND reviewed_value IS NOT NULL AND length(btrim(reviewed_value)) > 0) OR "
            "(state = 'REJECTED' AND suggestion_revealed_at IS NOT NULL AND reviewed_at IS NOT NULL "
            "AND reviewed_value IS NULL)",
            name="ck_doc_fact_review_state",
        ),
        CheckConstraint(
            "(confirmed_by IS NULL AND confirmed_at IS NULL) OR "
            "(confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL "
            "AND state IN ('CONFIRMED', 'CORRECTED') AND reviewed_at IS NOT NULL "
            "AND confirmed_at >= reviewed_at AND confirmed_by <> review_typed_by)",
            name="ck_doc_fact_confirmation",
        ),
        CheckConstraint(
            "(review_typed_role IS NULL OR (review_typed_by IS NOT NULL AND review_typed_role IN "
            "('INSTITUTION', 'SCRUTINY_COMMITTEE', 'RO_OFFICER', 'BUREAU_OFFICER', 'BUREAU_HEAD', 'AUDITOR')))",
            name="ck_doc_fact_review_typed_role",
        ),
        CheckConstraint(
            "(confirmed_role IS NULL OR (confirmed_by IS NOT NULL AND confirmed_role IN "
            "('INSTITUTION', 'SCRUTINY_COMMITTEE', 'RO_OFFICER', 'BUREAU_OFFICER', 'BUREAU_HEAD', 'AUDITOR')))",
            name="ck_doc_fact_confirmed_role",
        ),
        Index("ix_doc_fact_version_field", "document_version_id", "field_key"),
        Index("ix_doc_fact_review_state", "state", "created_at"),
        {"schema": SCHEMA},
    )

    fact_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ocr_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    document_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    field_key: Mapped[str] = mapped_column(String(100), nullable=False)
    candidate_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalization_status: Mapped[str] = mapped_column(String(24), nullable=False)
    script_code: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_span_start: Mapped[int] = mapped_column(Integer, nullable=False)
    source_span_end: Mapped[int] = mapped_column(Integer, nullable=False)
    conflict_group_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    state: Mapped[str] = mapped_column(
        Text, nullable=False, default=FactState.PROPOSED.value, server_default=text("'PROPOSED'")
    )
    review_typed_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_typed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    review_typed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Role of that officer, so listings can say who acted without exposing user ids (doc_0005).
    review_typed_role: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggestion_revealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Second step after review, by another officer. Only confirmed facts may drive deadlines.
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_role: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
