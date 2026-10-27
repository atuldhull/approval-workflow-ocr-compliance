"""Protect document-processing history from ordinary deletion and truncation.

Revision ID: doc_0003_document_history_guards
Revises: doc_0002
"""

from alembic import op


revision = "doc_0003_document_history_guards"
down_revision = "doc_0002"
branch_labels = None
depends_on = None


_TABLES = ("document", "document_version", "ocr_run", "fact")
_OCR_TABLES = ("ocr_run", "fact")


def upgrade() -> None:
    # Replace doc_0001's unconditional truncate triggers with a narrow test-reset
    # gate. Its row-level delete guards remain installed and unchanged.
    for table_name in ("document", "document_version"):
        op.execute(f"DROP TRIGGER trg_doc_{table_name}_no_truncate ON doc.{table_name}")

    op.execute(
        """
        CREATE FUNCTION doc.guard_document_truncate() RETURNS trigger AS $$
        BEGIN
            IF current_setting('awoc.test_reset', true) IS DISTINCT FROM 'on' THEN
                RAISE EXCEPTION 'document history cannot be truncated outside the approved test reset'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql
        """
    )

    # Statement-level DELETE guards deny even no-op DELETE statements; the row
    # guards below preserve the established per-row protection.
    for table_name in _TABLES:
        op.execute(
            f"CREATE TRIGGER trg_doc_{table_name}_delete_statement "
            f"BEFORE DELETE ON doc.{table_name} FOR EACH STATEMENT "
            "EXECUTE FUNCTION doc.guard_document_delete()"
        )
        op.execute(
            f"CREATE TRIGGER trg_doc_{table_name}_no_truncate "
            f"BEFORE TRUNCATE ON doc.{table_name} FOR EACH STATEMENT "
            "EXECUTE FUNCTION doc.guard_document_truncate()"
        )

    # doc_0001 already provides these row-level guards for document and
    # document_version. Add the same protection to OCR attempts and facts.
    for table_name in _OCR_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_doc_{table_name}_no_delete "
            f"BEFORE DELETE ON doc.{table_name} FOR EACH ROW "
            "EXECUTE FUNCTION doc.guard_document_delete()"
        )


def downgrade() -> None:
    for table_name in _TABLES:
        op.execute(f"DROP TRIGGER trg_doc_{table_name}_no_truncate ON doc.{table_name}")
        op.execute(f"DROP TRIGGER trg_doc_{table_name}_delete_statement ON doc.{table_name}")

    for table_name in _OCR_TABLES:
        op.execute(f"DROP TRIGGER trg_doc_{table_name}_no_delete ON doc.{table_name}")

    op.execute("DROP FUNCTION doc.guard_document_truncate()")

    # Restore doc_0001's original protections exactly; its DELETE triggers and
    # shared guard function were never removed.
    for table_name in ("document", "document_version"):
        op.execute(
            f"CREATE TRIGGER trg_doc_{table_name}_no_truncate "
            f"BEFORE TRUNCATE ON doc.{table_name} FOR EACH STATEMENT "
            "EXECUTE FUNCTION doc.guard_document_delete()"
        )
