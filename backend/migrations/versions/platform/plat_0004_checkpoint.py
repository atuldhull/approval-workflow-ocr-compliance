"""platform: signed ledger checkpoints

Revision ID: plat_0004
Revises: plat_0003
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "plat_0004"
down_revision = "plat_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "checkpoint",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("head_seq", sa.BigInteger, nullable=False),
        sa.Column("head_hash", sa.Text, nullable=False),
        sa.Column("entry_count", sa.BigInteger, nullable=False),
        sa.Column("key_id", sa.Text, nullable=False),
        sa.Column("statement", sa.Text, nullable=False),
        sa.Column("signature", sa.Text, nullable=False),
        schema="plat",
    )


def downgrade() -> None:
    op.drop_table("checkpoint", schema="plat")
