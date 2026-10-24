"""platform: per-recipient delivery results (hashed), for privacy-safe partial retries

Revision ID: plat_0006
Revises: plat_0005
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "plat_0006"
down_revision = "plat_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "delivery_recipient",
        sa.Column("outbox_id", pg.UUID(as_uuid=True), sa.ForeignKey("plat.outbox.id"), primary_key=True),
        sa.Column("recipient_key", sa.Text, primary_key=True),
        sa.Column("outcome", sa.Text, nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        schema="plat",
    )


def downgrade() -> None:
    op.drop_table("delivery_recipient", schema="plat")
