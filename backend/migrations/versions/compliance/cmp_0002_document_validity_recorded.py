"""compliance: document validity records and officer-recorded obligations on cmp.obligation

Revision ID: cmp_0002
Revises: cmp_0001
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "cmp_0002"
down_revision = "cmp_0001"
branch_labels = None
depends_on = None

UUID = pg.UUID(as_uuid=True)
COLUMNS = ("document_id", "document_version_id", "doc_type", "valid_until", "validity_basis", "validity_fact_id",
           "eoa_stop_year", "live_lease_ok", "title", "evidence_required", "recorded_by")


def upgrade() -> None:
    # every column is nullable, so existing obligations stay as they are
    op.add_column("obligation", sa.Column("document_id", UUID, sa.ForeignKey(
        "doc.document.document_id", ondelete="RESTRICT")), schema="cmp")
    op.add_column("obligation", sa.Column("document_version_id", UUID, sa.ForeignKey(
        "doc.document_version.document_version_id", ondelete="RESTRICT")), schema="cmp")
    op.add_column("obligation", sa.Column("doc_type", sa.Text), schema="cmp")
    op.add_column("obligation", sa.Column("valid_until", sa.Date), schema="cmp")
    op.add_column("obligation", sa.Column("validity_basis", sa.Text), schema="cmp")
    op.add_column("obligation", sa.Column("validity_fact_id", UUID, sa.ForeignKey(
        "doc.fact.fact_id", ondelete="RESTRICT")), schema="cmp")
    op.add_column("obligation", sa.Column("eoa_stop_year", sa.Text), schema="cmp")
    op.add_column("obligation", sa.Column("live_lease_ok", sa.Boolean), schema="cmp")
    op.add_column("obligation", sa.Column("title", sa.Text), schema="cmp")
    op.add_column("obligation", sa.Column("evidence_required", sa.Text), schema="cmp")
    op.add_column("obligation", sa.Column("recorded_by", UUID), schema="cmp")
    op.create_check_constraint(
        "ck_cmp_obligation_validity_basis", "obligation",
        "validity_basis IS NULL OR validity_basis IN ('DOCUMENT_FACT', 'OFFICER_RECORDED', 'APH_PERIOD')",
        schema="cmp")
    op.create_check_constraint(
        "ck_cmp_obligation_document_validity", "obligation",
        "kind <> 'DOCUMENT_VALIDITY' OR (document_id IS NOT NULL AND document_version_id IS NOT NULL "
        "AND doc_type IS NOT NULL AND valid_until IS NOT NULL AND validity_basis IS NOT NULL)",
        schema="cmp")
    op.create_check_constraint(
        "ck_cmp_obligation_validity_fact", "obligation",
        "validity_basis IS DISTINCT FROM 'DOCUMENT_FACT' OR validity_fact_id IS NOT NULL", schema="cmp")
    op.create_check_constraint(
        "ck_cmp_obligation_eoa_stop_year", "obligation",
        "eoa_stop_year IS NULL OR eoa_stop_year ~ '^[0-9]{4}-[0-9]{2}$'", schema="cmp")
    op.create_index("uq_cmp_obligation_validity_version", "obligation", ["document_version_id"], unique=True,
                    schema="cmp", postgresql_where=sa.text("kind = 'DOCUMENT_VALIDITY'"))
    op.create_index("uq_cmp_obligation_validity_live", "obligation", ["application_id", "doc_type"], unique=True,
                    schema="cmp", postgresql_where=sa.text("kind = 'DOCUMENT_VALIDITY' AND status <> 'MET'"))


def downgrade() -> None:
    op.drop_index("uq_cmp_obligation_validity_live", "obligation", schema="cmp")
    op.drop_index("uq_cmp_obligation_validity_version", "obligation", schema="cmp")
    for name in ("ck_cmp_obligation_eoa_stop_year", "ck_cmp_obligation_validity_fact",
                 "ck_cmp_obligation_document_validity", "ck_cmp_obligation_validity_basis"):
        op.drop_constraint(name, "obligation", schema="cmp", type_="check")
    for column in reversed(COLUMNS):
        op.drop_column("obligation", column, schema="cmp")
