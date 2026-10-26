"""Add OCR attempt state, proposed facts, provenance, and review ordering.

Revision ID: doc_0002
Revises: doc_0001
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg


revision = "doc_0002"
down_revision = "doc_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ocr_run",
        sa.Column("ocr_run_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_version_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("adapter_key", sa.String(100), nullable=False),
        sa.Column("model_version", sa.String(100), nullable=True),
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'QUEUED'")),
        sa.Column("attempt_number", sa.Integer, nullable=False, server_default=sa.text("1")),
        sa.Column("retry_of_ocr_run_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("error_code", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["document_version_id"], ["doc.document_version.document_version_id"],
            ondelete="RESTRICT", name="fk_doc_ocr_run_document_version",
        ),
        sa.ForeignKeyConstraint(
            ["retry_of_ocr_run_id"], ["doc.ocr_run.ocr_run_id"],
            ondelete="RESTRICT", name="fk_doc_ocr_run_retry_of",
        ),
        sa.UniqueConstraint("ocr_run_id", "document_version_id", name="uq_doc_ocr_run_identity_version"),
        sa.UniqueConstraint("retry_of_ocr_run_id", name="uq_doc_ocr_run_single_retry"),
        sa.UniqueConstraint("document_version_id", "attempt_number", name="uq_doc_ocr_run_version_attempt"),
        sa.CheckConstraint("length(btrim(adapter_key)) > 0", name="ck_doc_ocr_run_adapter_key"),
        sa.CheckConstraint("attempt_number > 0", name="ck_doc_ocr_run_positive_attempt"),
        sa.CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED')",
            name="ck_doc_ocr_run_status",
        ),
        sa.CheckConstraint(
            "error_code IS NULL OR error_code IN "
            "('ADAPTER_UNAVAILABLE', 'UNSUPPORTED_SCRIPT', 'INPUT_REJECTED', "
            "'PROCESSING_FAILED', 'TIMEOUT', 'RESOURCE_LIMIT', 'UNKNOWN')",
            name="ck_doc_ocr_run_error_code",
        ),
        sa.CheckConstraint(
            "(status = 'QUEUED' AND started_at IS NULL AND finished_at IS NULL AND error_code IS NULL) "
            "OR (status = 'RUNNING' AND started_at IS NOT NULL AND finished_at IS NULL AND error_code IS NULL) "
            "OR (status = 'SUCCEEDED' AND started_at IS NOT NULL AND finished_at IS NOT NULL AND error_code IS NULL) "
            "OR (status = 'FAILED' AND finished_at IS NOT NULL AND error_code IS NOT NULL "
            "AND (started_at IS NULL OR started_at <= finished_at))",
            name="ck_doc_ocr_run_status_timestamps",
        ),
        schema="doc",
    )
    op.create_index(
        "ix_doc_ocr_run_version_created", "ocr_run", ["document_version_id", "created_at"], schema="doc"
    )

    op.create_table(
        "fact",
        sa.Column("fact_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("ocr_run_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("document_version_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("field_key", sa.String(100), nullable=False),
        sa.Column("candidate_text", sa.Text, nullable=False),
        sa.Column("normalized_value", sa.Text, nullable=True),
        sa.Column("normalization_status", sa.String(24), nullable=False),
        sa.Column("script_code", sa.String(16), nullable=False),
        sa.Column("confidence", sa.Numeric(6, 5), nullable=False),
        sa.Column("page_number", sa.Integer, nullable=False),
        sa.Column("source_span_start", sa.Integer, nullable=False),
        sa.Column("source_span_end", sa.Integer, nullable=False),
        sa.Column("conflict_group_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("state", sa.Text, nullable=False, server_default=sa.text("'PROPOSED'")),
        sa.Column("review_typed_value", sa.Text, nullable=True),
        sa.Column("review_typed_by", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("review_typed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("suggestion_revealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_value", sa.Text, nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["ocr_run_id", "document_version_id"],
            ["doc.ocr_run.ocr_run_id", "doc.ocr_run.document_version_id"],
            ondelete="RESTRICT", name="fk_doc_fact_run_version",
        ),
        sa.CheckConstraint("page_number > 0", name="ck_doc_fact_positive_page"),
        sa.CheckConstraint(
            "source_span_start >= 0 AND source_span_end > source_span_start",
            name="ck_doc_fact_source_span",
        ),
        sa.CheckConstraint("length(btrim(candidate_text)) > 0", name="ck_doc_fact_candidate_nonempty"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_doc_fact_confidence_range"),
        sa.CheckConstraint(
            "script_code IN ('LATIN', 'DEVANAGARI', 'BENGALI', 'GUJARATI', 'GURMUKHI', "
            "'KANNADA', 'MALAYALAM', 'ODIA', 'TAMIL', 'TELUGU', 'MIXED', 'UNKNOWN', 'UNSUPPORTED')",
            name="ck_doc_fact_script_code",
        ),
        sa.CheckConstraint(
            "normalization_status IN ('NORMALIZED', 'AMBIGUOUS', 'INVALID', 'UNSUPPORTED', 'NOT_APPLICABLE')",
            name="ck_doc_fact_normalization_status",
        ),
        sa.CheckConstraint(
            "(normalization_status IN ('NORMALIZED', 'NOT_APPLICABLE') AND normalized_value IS NOT NULL) OR "
            "(normalization_status IN ('AMBIGUOUS', 'INVALID', 'UNSUPPORTED') AND normalized_value IS NULL)",
            name="ck_doc_fact_normalization_value",
        ),
        sa.CheckConstraint("length(btrim(field_key)) > 0", name="ck_doc_fact_field_key"),
        sa.CheckConstraint("state IN ('PROPOSED', 'CONFIRMED', 'CORRECTED', 'REJECTED')", name="ck_doc_fact_state"),
        sa.CheckConstraint(
            "(review_typed_value IS NULL AND review_typed_by IS NULL AND review_typed_at IS NULL "
            "AND suggestion_revealed_at IS NULL) OR "
            "(review_typed_value IS NOT NULL AND length(btrim(review_typed_value)) > 0 "
            "AND review_typed_by IS NOT NULL AND review_typed_at IS NOT NULL "
            "AND review_typed_at >= created_at "
            "AND (suggestion_revealed_at IS NULL OR suggestion_revealed_at >= review_typed_at))",
            name="ck_doc_fact_review_entry_order",
        ),
        sa.CheckConstraint(
            "(state = 'PROPOSED' AND reviewed_value IS NULL AND reviewed_at IS NULL) OR "
            "(state = 'CONFIRMED' AND suggestion_revealed_at IS NOT NULL AND reviewed_at IS NOT NULL "
            "AND normalized_value IS NOT NULL AND reviewed_value = normalized_value) OR "
            "(state = 'CORRECTED' AND suggestion_revealed_at IS NOT NULL AND reviewed_at IS NOT NULL "
            "AND reviewed_value IS NOT NULL AND length(btrim(reviewed_value)) > 0) OR "
            "(state = 'REJECTED' AND suggestion_revealed_at IS NOT NULL AND reviewed_at IS NOT NULL "
            "AND reviewed_value IS NULL)",
            name="ck_doc_fact_review_state",
        ),
        schema="doc",
    )
    op.create_index("ix_doc_fact_version_field", "fact", ["document_version_id", "field_key"], schema="doc")
    op.create_index("ix_doc_fact_review_state", "fact", ["state", "created_at"], schema="doc")

    op.execute(
        """
        CREATE FUNCTION doc.guard_ocr_run_insert() RETURNS trigger AS $$
        DECLARE
            parent_status text;
            parent_version uuid;
            parent_attempt integer;
            parent_finished_at timestamptz;
        BEGIN
            IF NEW.status <> 'QUEUED' OR NEW.started_at IS NOT NULL OR NEW.finished_at IS NOT NULL
               OR NEW.error_code IS NOT NULL THEN
                RAISE EXCEPTION 'OCR runs must be inserted in QUEUED state';
            END IF;
            IF NEW.retry_of_ocr_run_id IS NULL THEN
                IF NEW.attempt_number <> 1 THEN
                    RAISE EXCEPTION 'initial OCR attempt number must be one';
                END IF;
            ELSE
                SELECT status, document_version_id, attempt_number, finished_at
                  INTO parent_status, parent_version, parent_attempt, parent_finished_at
                  FROM doc.ocr_run WHERE ocr_run_id = NEW.retry_of_ocr_run_id FOR KEY SHARE;
                IF parent_status IS DISTINCT FROM 'FAILED'
                   OR parent_version IS DISTINCT FROM NEW.document_version_id
                   OR parent_attempt IS DISTINCT FROM NEW.attempt_number - 1
                   OR NEW.created_at < parent_finished_at THEN
                    RAISE EXCEPTION 'OCR retry must follow a failed attempt for the same document version';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER trg_doc_ocr_run_insert BEFORE INSERT ON doc.ocr_run "
        "FOR EACH ROW EXECUTE FUNCTION doc.guard_ocr_run_insert()"
    )
    op.execute(
        """
        CREATE FUNCTION doc.guard_ocr_run_update() RETURNS trigger AS $$
        DECLARE version_status text;
        BEGIN
            IF NEW.ocr_run_id IS DISTINCT FROM OLD.ocr_run_id
               OR NEW.document_version_id IS DISTINCT FROM OLD.document_version_id
               OR NEW.adapter_key IS DISTINCT FROM OLD.adapter_key
               OR NEW.model_version IS DISTINCT FROM OLD.model_version
               OR NEW.attempt_number IS DISTINCT FROM OLD.attempt_number
               OR NEW.retry_of_ocr_run_id IS DISTINCT FROM OLD.retry_of_ocr_run_id
               OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'OCR run identity and provenance are immutable';
            END IF;
            IF OLD.status = 'QUEUED' AND NEW.status = 'RUNNING'
               AND NEW.started_at IS NOT NULL AND NEW.finished_at IS NULL AND NEW.error_code IS NULL
               AND NEW.started_at >= OLD.created_at THEN
                SELECT status INTO version_status FROM doc.document_version
                 WHERE document_version_id = NEW.document_version_id FOR KEY SHARE;
                IF version_status IS DISTINCT FROM 'AVAILABLE' THEN
                    RAISE EXCEPTION 'OCR cannot start until the document version is scanner-approved';
                END IF;
                RETURN NEW;
            END IF;
            IF OLD.status = 'QUEUED' AND NEW.status = 'FAILED'
               AND NEW.started_at IS NULL AND NEW.finished_at IS NOT NULL AND NEW.error_code IS NOT NULL
               AND NEW.finished_at >= OLD.created_at THEN
                RETURN NEW;
            END IF;
            IF OLD.status = 'RUNNING' AND NEW.status IN ('SUCCEEDED', 'FAILED')
               AND NEW.started_at = OLD.started_at AND NEW.finished_at IS NOT NULL
               AND NEW.finished_at >= OLD.started_at
               AND ((NEW.status = 'SUCCEEDED' AND NEW.error_code IS NULL)
                    OR (NEW.status = 'FAILED' AND NEW.error_code IS NOT NULL)) THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'invalid OCR run state transition';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER trg_doc_ocr_run_update BEFORE UPDATE ON doc.ocr_run "
        "FOR EACH ROW EXECUTE FUNCTION doc.guard_ocr_run_update()"
    )

    op.execute(
        """
        CREATE FUNCTION doc.guard_fact_insert() RETURNS trigger AS $$
        DECLARE run_status text;
        BEGIN
            IF NEW.state <> 'PROPOSED' OR NEW.review_typed_value IS NOT NULL
               OR NEW.review_typed_by IS NOT NULL OR NEW.review_typed_at IS NOT NULL
               OR NEW.suggestion_revealed_at IS NOT NULL OR NEW.reviewed_value IS NOT NULL
               OR NEW.reviewed_at IS NOT NULL THEN
                RAISE EXCEPTION 'OCR facts must be inserted as unreviewed PROPOSED values';
            END IF;
            SELECT status INTO run_status FROM doc.ocr_run
             WHERE ocr_run_id = NEW.ocr_run_id
               AND document_version_id = NEW.document_version_id FOR KEY SHARE;
            IF run_status IS DISTINCT FROM 'SUCCEEDED' THEN
                RAISE EXCEPTION 'facts require a successful OCR run for the same document version';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER trg_doc_fact_insert BEFORE INSERT ON doc.fact "
        "FOR EACH ROW EXECUTE FUNCTION doc.guard_fact_insert()"
    )
    op.execute(
        """
        CREATE FUNCTION doc.guard_fact_update() RETURNS trigger AS $$
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
    )
    op.execute(
        "CREATE TRIGGER trg_doc_fact_update BEFORE UPDATE ON doc.fact "
        "FOR EACH ROW EXECUTE FUNCTION doc.guard_fact_update()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_doc_fact_update ON doc.fact")
    op.execute("DROP FUNCTION IF EXISTS doc.guard_fact_update()")
    op.execute("DROP TRIGGER IF EXISTS trg_doc_fact_insert ON doc.fact")
    op.execute("DROP FUNCTION IF EXISTS doc.guard_fact_insert()")
    op.execute("DROP TRIGGER IF EXISTS trg_doc_ocr_run_update ON doc.ocr_run")
    op.execute("DROP FUNCTION IF EXISTS doc.guard_ocr_run_update()")
    op.execute("DROP TRIGGER IF EXISTS trg_doc_ocr_run_insert ON doc.ocr_run")
    op.execute("DROP FUNCTION IF EXISTS doc.guard_ocr_run_insert()")
    op.drop_index("ix_doc_fact_review_state", table_name="fact", schema="doc")
    op.drop_index("ix_doc_fact_version_field", table_name="fact", schema="doc")
    op.drop_table("fact", schema="doc")
    op.drop_index("ix_doc_ocr_run_version_created", table_name="ocr_run", schema="doc")
    op.drop_table("ocr_run", schema="doc")
