"""documents: quarantined upload metadata and immutable versions

Revision ID: doc_0001
Revises:
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "doc_0001"
down_revision = None
branch_labels = ("documents",)
depends_on = ("wf_0001",)


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS doc")
    op.create_table(
        "document",
        sa.Column("document_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("application_id", pg.UUID(as_uuid=True), sa.ForeignKey("wf.application.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("institution_id", pg.UUID(as_uuid=True), sa.ForeignKey("wf.institution.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("document_id", "application_id", "institution_id", name="uq_doc_document_owner_scope"),
        schema="doc",
    )
    op.create_index(
        "ix_doc_document_application_id", "document", ["application_id", "document_id"], schema="doc"
    )
    op.create_table(
        "document_version",
        sa.Column("document_version_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("application_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("institution_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("version_no", sa.Integer, nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("media_type", sa.Text, nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_ref", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'QUARANTINED'")),
        sa.Column("uploaded_by", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id", "application_id", "institution_id"],
            ["doc.document.document_id", "doc.document.application_id", "doc.document.institution_id"],
            ondelete="RESTRICT",
            name="fk_doc_version_document_owner_scope",
        ),
        sa.UniqueConstraint("document_id", "version_no", name="uq_doc_version_document_version_no"),
        sa.UniqueConstraint(
            "application_id", "institution_id", "sha256", name="uq_doc_version_owner_application_sha256"
        ),
        sa.UniqueConstraint("storage_ref", name="uq_doc_version_storage_ref"),
        sa.CheckConstraint("version_no > 0", name="ck_doc_version_positive_version"),
        sa.CheckConstraint("size_bytes > 0", name="ck_doc_version_nonempty_size"),
        sa.CheckConstraint(
            "media_type IN ('application/pdf', 'image/png', 'image/jpeg')",
            name="ck_doc_version_supported_media_type",
        ),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_doc_version_sha256_hex"),
        sa.CheckConstraint("status IN ('QUARANTINED', 'REJECTED')", name="ck_doc_version_status"),
        schema="doc",
    )
    op.create_index(
        "ix_doc_version_application_created", "document_version", ["application_id", "created_at"], schema="doc"
    )
    op.create_index(
        "ix_doc_version_status_created", "document_version", ["status", "created_at"], schema="doc"
    )
    op.execute(
        """
        CREATE FUNCTION doc.guard_document_identity_immutable() RETURNS trigger AS $$
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
    )
    op.execute(
        "CREATE TRIGGER trg_doc_document_identity_immutable "
        "BEFORE UPDATE ON doc.document FOR EACH ROW "
        "EXECUTE FUNCTION doc.guard_document_identity_immutable()"
    )
    op.execute(
        """
        CREATE FUNCTION doc.guard_document_application_institution() RETURNS trigger AS $$
        BEGIN
            PERFORM 1 FROM wf.application
            WHERE id = NEW.application_id AND institution_id = NEW.institution_id
            FOR KEY SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'document institution does not own the referenced application'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER trg_doc_document_application_institution "
        "BEFORE INSERT OR UPDATE OF application_id, institution_id ON doc.document "
        "FOR EACH ROW EXECUTE FUNCTION doc.guard_document_application_institution()"
    )
    op.execute(
        """
        CREATE FUNCTION doc.guard_document_version_immutable() RETURNS trigger AS $$
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
    )
    op.execute(
        "CREATE TRIGGER trg_doc_document_version_immutable "
        "BEFORE UPDATE ON doc.document_version FOR EACH ROW "
        "EXECUTE FUNCTION doc.guard_document_version_immutable()"
    )
    op.execute(
        """
        CREATE FUNCTION doc.guard_document_delete() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'document history cannot be deleted';
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table_name in ("document", "document_version"):
        op.execute(
            f"CREATE TRIGGER trg_doc_{table_name}_no_delete "
            f"BEFORE DELETE ON doc.{table_name} FOR EACH ROW "
            "EXECUTE FUNCTION doc.guard_document_delete()"
        )
        op.execute(
            f"CREATE TRIGGER trg_doc_{table_name}_no_truncate "
            f"BEFORE TRUNCATE ON doc.{table_name} FOR EACH STATEMENT "
            "EXECUTE FUNCTION doc.guard_document_delete()"
        )


def downgrade() -> None:
    for table_name in ("document_version", "document"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_doc_{table_name}_no_truncate ON doc.{table_name}")
        op.execute(f"DROP TRIGGER IF EXISTS trg_doc_{table_name}_no_delete ON doc.{table_name}")
    op.execute("DROP FUNCTION IF EXISTS doc.guard_document_delete()")
    op.execute("DROP TRIGGER IF EXISTS trg_doc_document_version_immutable ON doc.document_version")
    op.execute("DROP FUNCTION IF EXISTS doc.guard_document_version_immutable()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_doc_document_application_institution ON doc.document"
    )
    op.execute("DROP FUNCTION IF EXISTS doc.guard_document_application_institution()")
    op.execute("DROP TRIGGER IF EXISTS trg_doc_document_identity_immutable ON doc.document")
    op.execute("DROP FUNCTION IF EXISTS doc.guard_document_identity_immutable()")
    op.drop_table("document_version", schema="doc")
    op.drop_index("ix_doc_document_application_id", table_name="document", schema="doc")
    op.drop_table("document", schema="doc")
    op.execute("DROP SCHEMA IF EXISTS doc")
