"""workflow: application checklist items and DSC presence.

Revision ID: wf_0003
Revises: wf_0002
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "wf_0003"
down_revision = "wf_0002"
branch_labels = None  # inherits workflow; one head only
depends_on = None


def upgrade() -> None:
    op.add_column("application", sa.Column("dsc_present", sa.Boolean, nullable=False, server_default=sa.text("false")), schema="wf")
    op.create_table("application_item",
        sa.Column("application_id", pg.UUID(as_uuid=True), sa.ForeignKey("wf.application.id"), primary_key=True),
        sa.Column("item_key", sa.Text, primary_key=True),
        sa.Column("state", sa.Text, nullable=False),
        sa.Column("document_ref", pg.UUID(as_uuid=True)),
        sa.CheckConstraint("state IN ('PROVIDED', 'MISSING')", name="ck_wf_application_item_state"),
        sa.CheckConstraint("item_key ~ '^[A-Z][A-Z0-9_]*$'", name="ck_wf_application_item_key"),
        sa.CheckConstraint("(state = 'PROVIDED') = (document_ref IS NOT NULL)", name="ck_wf_application_item_document"),
        schema="wf")


def downgrade() -> None:
    op.drop_table("application_item", schema="wf")
    op.drop_column("application", "dsc_present", schema="wf")
