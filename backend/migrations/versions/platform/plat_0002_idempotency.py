"""platform: idempotency keys for safely retried commands

Revision ID: plat_0002
Revises: plat_0001
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "plat_0002"
down_revision = "plat_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "idempotency_key",
        sa.Column("principal_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("method", sa.Text, primary_key=True),
        sa.Column("route", sa.Text, primary_key=True),
        sa.Column("key_hash", sa.Text, primary_key=True),
        sa.Column("request_hash", sa.Text, nullable=False),
        sa.Column("response_status", sa.Integer),
        sa.Column("response_body", pg.JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        schema="plat",
    )
    op.create_index("ix_plat_idempotency_key_expires_at", "idempotency_key", ["expires_at"], schema="plat")


def downgrade() -> None:
    op.drop_table("idempotency_key", schema="plat")
