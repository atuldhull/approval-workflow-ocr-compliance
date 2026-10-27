"""workflow: persisted deficiency rounds and item responses."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "wf_0004"
down_revision = "wf_0003"
branch_labels = None  # inherits workflow from the root
depends_on = None


def upgrade() -> None:
    op.create_table("deficiency",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("application_id", pg.UUID(as_uuid=True), sa.ForeignKey("wf.case_state.application_id"), nullable=False),
        sa.Column("round_no", sa.Integer, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("application_id", "round_no", name="uq_wf_deficiency_round"),
        sa.CheckConstraint("round_no >= 1", name="ck_wf_deficiency_round"),
        sa.CheckConstraint("status IN ('OPEN', 'RESPONDED', 'CLOSED')", name="ck_wf_deficiency_status"),
        sa.CheckConstraint("(status = 'CLOSED') = (closed_at IS NOT NULL)", name="ck_wf_deficiency_closed"),
        schema="wf")
    op.create_index("ix_wf_deficiency_case", "deficiency", ["application_id"], schema="wf")
    op.create_index("uq_wf_deficiency_active", "deficiency", ["application_id"], unique=True,
                    postgresql_where=sa.text("status != 'CLOSED'"), schema="wf")
    op.create_table("deficiency_item",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("deficiency_id", pg.UUID(as_uuid=True), sa.ForeignKey("wf.deficiency.id"), nullable=False),
        sa.Column("item_key", sa.Text, nullable=False),
        sa.Column("state", sa.Text, nullable=False),
        sa.Column("response_ref", pg.UUID(as_uuid=True)),
        sa.Column("decided_by", pg.UUID(as_uuid=True)),
        sa.Column("decision_reason_code", sa.Text),
        sa.UniqueConstraint("deficiency_id", "item_key", name="uq_wf_deficiency_item_key"),
        sa.CheckConstraint("item_key ~ '^[A-Z][A-Z0-9_]*$'", name="ck_wf_deficiency_item_key"),
        sa.CheckConstraint("state IN ('OPEN', 'RESPONDED', 'ACCEPTED', 'REJECTED')", name="ck_wf_deficiency_item_state"),
        sa.CheckConstraint("(state = 'OPEN') = (response_ref IS NULL)", name="ck_wf_deficiency_item_response"),
        sa.CheckConstraint("(state IN ('ACCEPTED', 'REJECTED')) = (decided_by IS NOT NULL AND decision_reason_code IS NOT NULL)",
                           name="ck_wf_deficiency_item_decision"), schema="wf")
    op.create_index("ix_wf_deficiency_item_round", "deficiency_item", ["deficiency_id"], schema="wf")


def downgrade() -> None:
    op.drop_table("deficiency_item", schema="wf")
    op.drop_table("deficiency", schema="wf")
