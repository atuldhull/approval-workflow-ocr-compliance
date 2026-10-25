"""Person 2-owned document metadata. Uploaded versions retain immutable provenance."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.db import Base

SCHEMA = "doc"


class Document(Base):
    __tablename__ = "document"
    __table_args__ = (
        UniqueConstraint(
            "document_id", "application_id", "institution_id", name="uq_doc_document_owner_scope"
        ),
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
        CheckConstraint("status IN ('QUARANTINED', 'REJECTED')", name="ck_doc_version_status"),
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
