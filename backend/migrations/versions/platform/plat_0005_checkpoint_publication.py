"""platform: two-step checkpoint publication (pending -> published)

Revision ID: plat_0005
Revises: plat_0004
"""
from alembic import op
import sqlalchemy as sa

revision = "plat_0005"
down_revision = "plat_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Rows written before this revision were handed to the witness before their commit, so they count as published.
    op.add_column("checkpoint", sa.Column("status", sa.Text, nullable=False, server_default="PUBLISHED"), schema="plat")
    op.add_column("checkpoint", sa.Column("published_at", sa.DateTime(timezone=True)), schema="plat")
    op.add_column("checkpoint", sa.Column("publish_error", sa.Text), schema="plat")


def downgrade() -> None:
    for name in ("publish_error", "published_at", "status"):
        op.drop_column("checkpoint", name, schema="plat")
