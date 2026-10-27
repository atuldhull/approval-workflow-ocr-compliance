"""Checklist document types, malware-scan state, and the separate fact confirmation step.

Revision ID: doc_0004_document_api_lifecycle
Revises: doc_0003_document_history_guards
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg


revision = "doc_0004_document_api_lifecycle"
down_revision = "doc_0003_document_history_guards"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # One logical document per (application, checklist item). Rows written
    # before this revision have no type and stay outside the versioning rule.
    op.add_column("document", sa.Column("doc_type", sa.String(64), nullable=True), schema="doc")
    op.create_check_constraint(
        "ck_doc_document_doc_type", "document",
        "doc_type IS NULL OR doc_type ~ '^[A-Z][A-Z0-9_]*$'", schema="doc",
    )
    op.create_unique_constraint(
        "uq_doc_document_application_doc_type", "document", ["application_id", "doc_type"], schema="doc"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION doc.guard_document_identity_immutable() RETURNS trigger AS $$
        BEGIN
            IF NEW.document_id IS DISTINCT FROM OLD.document_id
               OR NEW.application_id IS DISTINCT FROM OLD.application_id
               OR NEW.institution_id IS DISTINCT FROM OLD.institution_id
               OR NEW.doc_type IS DISTINCT FROM OLD.doc_type
               OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'document identity and ownership are immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )

    # Scan state. A version is AVAILABLE only together with a CLEAN verdict;
    # an infected version is REJECTED and stays in quarantine.
    op.add_column(
        "document_version",
        sa.Column("scan_status", sa.Text, nullable=False, server_default=sa.text("'scan_pending'")),
        schema="doc",
    )
    op.add_column("document_version", sa.Column("scan_signature", sa.String(200), nullable=True), schema="doc")
    op.add_column(
        "document_version", sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=True), schema="doc"
    )
    op.drop_constraint("ck_doc_version_status", "document_version", schema="doc")
    op.create_check_constraint(
        "ck_doc_version_status", "document_version",
        "status IN ('QUARANTINED', 'AVAILABLE', 'REJECTED')", schema="doc",
    )
    op.create_check_constraint(
        "ck_doc_version_scan_status", "document_version",
        "scan_status IN ('scan_pending', 'clean', 'infected')", schema="doc",
    )
    op.create_check_constraint(
        "ck_doc_version_scan_consistency", "document_version",
        "(scan_status = 'scan_pending' AND status IN ('QUARANTINED', 'REJECTED') "
        "AND scanned_at IS NULL AND scan_signature IS NULL) OR "
        "(scan_status = 'clean' AND status = 'AVAILABLE' AND scanned_at IS NOT NULL "
        "AND scan_signature IS NULL) OR "
        "(scan_status = 'infected' AND status = 'REJECTED' AND scanned_at IS NOT NULL)",
        schema="doc",
    )
    op.execute(
        """
        CREATE FUNCTION doc.guard_document_version_insert() RETURNS trigger AS $$
        BEGIN
            IF NEW.status <> 'QUARANTINED' OR NEW.scan_status <> 'scan_pending' THEN
                RAISE EXCEPTION 'document versions must be inserted quarantined and awaiting a scan';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER trg_doc_document_version_insert "
        "BEFORE INSERT ON doc.document_version FOR EACH ROW "
        "EXECUTE FUNCTION doc.guard_document_version_insert()"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION doc.guard_document_version_immutable() RETURNS trigger AS $$
        BEGIN
            IF NEW.document_version_id IS DISTINCT FROM OLD.document_version_id
               OR NEW.document_id IS DISTINCT FROM OLD.document_id
               OR NEW.application_id IS DISTINCT FROM OLD.application_id
               OR NEW.institution_id IS DISTINCT FROM OLD.institution_id
               OR NEW.version_no IS DISTINCT FROM OLD.version_no
               OR NEW.original_filename IS DISTINCT FROM OLD.original_filename
               OR NEW.media_type IS DISTINCT FROM OLD.media_type
               OR NEW.size_bytes IS DISTINCT FROM OLD.size_bytes
               OR NEW.sha256 IS DISTINCT FROM OLD.sha256
               OR NEW.storage_ref IS DISTINCT FROM OLD.storage_ref
               OR NEW.uploaded_by IS DISTINCT FROM OLD.uploaded_by
               OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'document version source metadata is immutable';
            END IF;
            -- A scan verdict is recorded once and never changes afterwards.
            IF OLD.scan_status <> 'scan_pending'
               AND (NEW.scan_status IS DISTINCT FROM OLD.scan_status
                    OR NEW.scan_signature IS DISTINCT FROM OLD.scan_signature
                    OR NEW.scanned_at IS DISTINCT FROM OLD.scanned_at) THEN
                RAISE EXCEPTION 'document scan verdicts are immutable';
            END IF;
            IF NEW.status IS DISTINCT FROM OLD.status
               AND NOT (OLD.status = 'QUARANTINED' AND NEW.status = 'REJECTED')
               AND NOT (OLD.status = 'QUARANTINED' AND NEW.status = 'AVAILABLE'
                        AND OLD.scan_status = 'scan_pending' AND NEW.scan_status = 'clean') THEN
                RAISE EXCEPTION 'invalid document version status transition';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )

    # Confirmation is a second step after review, by a different person.
    op.add_column("fact", sa.Column("confirmed_by", pg.UUID(as_uuid=True), nullable=True), schema="doc")
    op.add_column("fact", sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True), schema="doc")
    op.create_check_constraint(
        "ck_doc_fact_confirmation", "fact",
        "(confirmed_by IS NULL AND confirmed_at IS NULL) OR "
        "(confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL "
        "AND state IN ('CONFIRMED', 'CORRECTED') AND reviewed_at IS NOT NULL "
        "AND confirmed_at >= reviewed_at AND confirmed_by <> review_typed_by)",
        schema="doc",
    )
    op.execute(_FACT_UPDATE_WITH_CONFIRMATION)


def downgrade() -> None:
    op.execute(_FACT_UPDATE_DOC_0002)
    op.drop_constraint("ck_doc_fact_confirmation", "fact", schema="doc")
    op.drop_column("fact", "confirmed_at", schema="doc")
    op.drop_column("fact", "confirmed_by", schema="doc")

    op.execute(_VERSION_UPDATE_DOC_0001)
    op.execute("DROP TRIGGER trg_doc_document_version_insert ON doc.document_version")
    op.execute("DROP FUNCTION doc.guard_document_version_insert()")
    op.drop_constraint("ck_doc_version_scan_consistency", "document_version", schema="doc")
    op.drop_constraint("ck_doc_version_scan_status", "document_version", schema="doc")
    # Fails if any version was scanned clean; history is never rewritten to fit an older schema.
    op.drop_constraint("ck_doc_version_status", "document_version", schema="doc")
    op.create_check_constraint(
        "ck_doc_version_status", "document_version", "status IN ('QUARANTINED', 'REJECTED')", schema="doc"
    )
    op.drop_column("document_version", "scanned_at", schema="doc")
    op.drop_column("document_version", "scan_signature", schema="doc")
    op.drop_column("document_version", "scan_status", schema="doc")

    op.execute(_DOCUMENT_IDENTITY_DOC_0001)
    op.drop_constraint("uq_doc_document_application_doc_type", "document", schema="doc")
    op.drop_constraint("ck_doc_document_doc_type", "document", schema="doc")
    op.drop_column("document", "doc_type", schema="doc")


_FACT_UPDATE_WITH_CONFIRMATION = """
CREATE OR REPLACE FUNCTION doc.guard_fact_update() RETURNS trigger AS $$
BEGIN
    IF NEW.fact_id IS DISTINCT FROM OLD.fact_id
       OR NEW.ocr_run_id IS DISTINCT FROM OLD.ocr_run_id
       OR NEW.document_version_id IS DISTINCT FROM OLD.document_version_id
       OR NEW.field_key IS DISTINCT FROM OLD.field_key
       OR NEW.candidate_text IS DISTINCT FROM OLD.candidate_text
       OR NEW.normalized_value IS DISTINCT FROM OLD.normalized_value
       OR NEW.normalization_status IS DISTINCT FROM OLD.normalization_status
       OR NEW.script_code IS DISTINCT FROM OLD.script_code
       OR NEW.confidence IS DISTINCT FROM OLD.confidence
       OR NEW.page_number IS DISTINCT FROM OLD.page_number
       OR NEW.source_span_start IS DISTINCT FROM OLD.source_span_start
       OR NEW.source_span_end IS DISTINCT FROM OLD.source_span_end
       OR NEW.conflict_group_id IS DISTINCT FROM OLD.conflict_group_id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'OCR fact source and provenance are immutable';
    END IF;
    IF OLD.state <> 'PROPOSED' THEN
        -- The only change after a review decision: one confirmation of an
        -- accepted or corrected value, by someone other than its reviewer.
        IF OLD.state IN ('CONFIRMED', 'CORRECTED') AND OLD.confirmed_at IS NULL
           AND NEW.confirmed_at IS NOT NULL AND NEW.confirmed_by IS NOT NULL
           AND NEW.state = OLD.state
           AND NEW.review_typed_value IS NOT DISTINCT FROM OLD.review_typed_value
           AND NEW.review_typed_by IS NOT DISTINCT FROM OLD.review_typed_by
           AND NEW.review_typed_at IS NOT DISTINCT FROM OLD.review_typed_at
           AND NEW.suggestion_revealed_at IS NOT DISTINCT FROM OLD.suggestion_revealed_at
           AND NEW.reviewed_value IS NOT DISTINCT FROM OLD.reviewed_value
           AND NEW.reviewed_at IS NOT DISTINCT FROM OLD.reviewed_at THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'final OCR fact decisions are immutable';
    END IF;
    IF NEW.confirmed_by IS NOT NULL OR NEW.confirmed_at IS NOT NULL THEN
        RAISE EXCEPTION 'a fact can only be confirmed after its review decision';
    END IF;
    IF OLD.review_typed_at IS NULL AND NEW.review_typed_at IS NOT NULL
       AND NEW.state = 'PROPOSED' AND NEW.review_typed_value IS NOT NULL
       AND NEW.review_typed_by IS NOT NULL AND NEW.suggestion_revealed_at IS NULL
       AND NEW.reviewed_value IS NULL AND NEW.reviewed_at IS NULL THEN
        RETURN NEW;
    END IF;
    IF OLD.review_typed_at IS NOT NULL AND OLD.suggestion_revealed_at IS NULL
       AND NEW.state = 'PROPOSED'
       AND NEW.review_typed_value IS NOT DISTINCT FROM OLD.review_typed_value
       AND NEW.review_typed_by IS NOT DISTINCT FROM OLD.review_typed_by
       AND NEW.review_typed_at IS NOT DISTINCT FROM OLD.review_typed_at
       AND NEW.suggestion_revealed_at IS NOT NULL
       AND NEW.reviewed_value IS NULL AND NEW.reviewed_at IS NULL THEN
        RETURN NEW;
    END IF;
    IF OLD.suggestion_revealed_at IS NOT NULL
       AND NEW.state IN ('CONFIRMED', 'CORRECTED', 'REJECTED')
       AND NEW.review_typed_value IS NOT DISTINCT FROM OLD.review_typed_value
       AND NEW.review_typed_by IS NOT DISTINCT FROM OLD.review_typed_by
       AND NEW.review_typed_at IS NOT DISTINCT FROM OLD.review_typed_at
       AND NEW.suggestion_revealed_at IS NOT DISTINCT FROM OLD.suggestion_revealed_at
       AND NEW.reviewed_at IS NOT NULL
       AND NEW.reviewed_at >= OLD.suggestion_revealed_at THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'invalid OCR fact review transition; type before reveal';
END;
$$ LANGUAGE plpgsql
"""

# Exact function bodies from doc_0001/doc_0002, restored on downgrade.
_FACT_UPDATE_DOC_0002 = """
CREATE OR REPLACE FUNCTION doc.guard_fact_update() RETURNS trigger AS $$
BEGIN
    IF NEW.fact_id IS DISTINCT FROM OLD.fact_id
       OR NEW.ocr_run_id IS DISTINCT FROM OLD.ocr_run_id
       OR NEW.document_version_id IS DISTINCT FROM OLD.document_version_id
       OR NEW.field_key IS DISTINCT FROM OLD.field_key
       OR NEW.candidate_text IS DISTINCT FROM OLD.candidate_text
       OR NEW.normalized_value IS DISTINCT FROM OLD.normalized_value
       OR NEW.normalization_status IS DISTINCT FROM OLD.normalization_status
       OR NEW.script_code IS DISTINCT FROM OLD.script_code
       OR NEW.confidence IS DISTINCT FROM OLD.confidence
       OR NEW.page_number IS DISTINCT FROM OLD.page_number
       OR NEW.source_span_start IS DISTINCT FROM OLD.source_span_start
       OR NEW.source_span_end IS DISTINCT FROM OLD.source_span_end
       OR NEW.conflict_group_id IS DISTINCT FROM OLD.conflict_group_id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'OCR fact source and provenance are immutable';
    END IF;
    IF OLD.state <> 'PROPOSED' THEN
        RAISE EXCEPTION 'final OCR fact decisions are immutable';
    END IF;
    IF OLD.review_typed_at IS NULL AND NEW.review_typed_at IS NOT NULL
       AND NEW.state = 'PROPOSED' AND NEW.review_typed_value IS NOT NULL
       AND NEW.review_typed_by IS NOT NULL AND NEW.suggestion_revealed_at IS NULL
       AND NEW.reviewed_value IS NULL AND NEW.reviewed_at IS NULL THEN
        RETURN NEW;
    END IF;
    IF OLD.review_typed_at IS NOT NULL AND OLD.suggestion_revealed_at IS NULL
       AND NEW.state = 'PROPOSED'
       AND NEW.review_typed_value IS NOT DISTINCT FROM OLD.review_typed_value
       AND NEW.review_typed_by IS NOT DISTINCT FROM OLD.review_typed_by
       AND NEW.review_typed_at IS NOT DISTINCT FROM OLD.review_typed_at
       AND NEW.suggestion_revealed_at IS NOT NULL
       AND NEW.reviewed_value IS NULL AND NEW.reviewed_at IS NULL THEN
        RETURN NEW;
    END IF;
    IF OLD.suggestion_revealed_at IS NOT NULL
       AND NEW.state IN ('CONFIRMED', 'CORRECTED', 'REJECTED')
       AND NEW.review_typed_value IS NOT DISTINCT FROM OLD.review_typed_value
       AND NEW.review_typed_by IS NOT DISTINCT FROM OLD.review_typed_by
       AND NEW.review_typed_at IS NOT DISTINCT FROM OLD.review_typed_at
       AND NEW.suggestion_revealed_at IS NOT DISTINCT FROM OLD.suggestion_revealed_at
       AND NEW.reviewed_at IS NOT NULL
       AND NEW.reviewed_at >= OLD.suggestion_revealed_at THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'invalid OCR fact review transition; type before reveal';
END;
$$ LANGUAGE plpgsql
"""

_VERSION_UPDATE_DOC_0001 = """
CREATE OR REPLACE FUNCTION doc.guard_document_version_immutable() RETURNS trigger AS $$
BEGIN
    IF NEW.document_version_id IS DISTINCT FROM OLD.document_version_id
       OR NEW.document_id IS DISTINCT FROM OLD.document_id
       OR NEW.application_id IS DISTINCT FROM OLD.application_id
       OR NEW.institution_id IS DISTINCT FROM OLD.institution_id
       OR NEW.version_no IS DISTINCT FROM OLD.version_no
       OR NEW.original_filename IS DISTINCT FROM OLD.original_filename
       OR NEW.media_type IS DISTINCT FROM OLD.media_type
       OR NEW.size_bytes IS DISTINCT FROM OLD.size_bytes
       OR NEW.sha256 IS DISTINCT FROM OLD.sha256
       OR NEW.storage_ref IS DISTINCT FROM OLD.storage_ref
       OR NEW.uploaded_by IS DISTINCT FROM OLD.uploaded_by
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'document version source metadata is immutable';
    END IF;
    IF NEW.status IS DISTINCT FROM OLD.status
       AND NOT (OLD.status = 'QUARANTINED' AND NEW.status = 'REJECTED') THEN
        RAISE EXCEPTION 'invalid document version status transition';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""

_DOCUMENT_IDENTITY_DOC_0001 = """
CREATE OR REPLACE FUNCTION doc.guard_document_identity_immutable() RETURNS trigger AS $$
BEGIN
    IF NEW.document_id IS DISTINCT FROM OLD.document_id
       OR NEW.application_id IS DISTINCT FROM OLD.application_id
       OR NEW.institution_id IS DISTINCT FROM OLD.institution_id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'document identity and ownership are immutable';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""
