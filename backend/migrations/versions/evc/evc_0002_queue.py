"""evc: pinned queue requests, one per source visit and one active per case."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "evc_0002"
down_revision = "evc_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Legacy rows stay identifiable; never invent a visit/pin/deadline or cancel duplicates.
    op.add_column("evc_request", sa.Column("stage_visit_ref", pg.UUID(as_uuid=True)), schema="evc")
    op.add_column("evc_request", sa.Column("ruleset_key", sa.Text), schema="evc")
    op.add_column("evc_request", sa.Column("rule_id", sa.Text), schema="evc")
    op.add_column("evc_request", sa.Column("deadline_ref", pg.UUID(as_uuid=True)), schema="evc")
    op.add_column("evc_request", sa.Column("closed_at", sa.DateTime(timezone=True)), schema="evc")
    op.add_column("evc_request", sa.Column("entry_no", sa.Integer), schema="evc")
    op.create_unique_constraint("uq_evc_request_entry", "evc_request", ["application_id", "entry_no"], schema="evc")
    op.create_check_constraint("ck_evc_request_entry", "evc_request", "entry_no IS NULL OR entry_no > 0", schema="evc")
    op.create_foreign_key("evc_request_stage_visit_ref_fkey", "evc_request", "stage_visit", ["stage_visit_ref"], ["id"],
                          source_schema="evc", referent_schema="wf")
    op.create_unique_constraint("uq_evc_request_visit", "evc_request", ["stage_visit_ref"], schema="evc")
    op.create_index("uq_evc_request_active", "evc_request", ["application_id"], unique=True, schema="evc",
                    postgresql_where=sa.text("status IN ('QUEUED', 'PROPOSED', 'PUBLISHED')"))


def downgrade() -> None:
    op.drop_index("uq_evc_request_active", table_name="evc_request", schema="evc")
    op.drop_constraint("uq_evc_request_visit", "evc_request", type_="unique", schema="evc")
    op.drop_constraint("evc_request_stage_visit_ref_fkey", "evc_request", type_="foreignkey", schema="evc")
    op.drop_constraint("ck_evc_request_entry", "evc_request", type_="check", schema="evc")
    op.drop_constraint("uq_evc_request_entry", "evc_request", type_="unique", schema="evc")
    for name in ("entry_no", "closed_at", "deadline_ref", "rule_id", "ruleset_key", "stage_visit_ref"):
        op.drop_column("evc_request", name, schema="evc")
