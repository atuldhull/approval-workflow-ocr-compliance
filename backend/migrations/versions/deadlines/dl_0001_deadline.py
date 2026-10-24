"""deadlines: deadline table

Revision ID: dl_0001
Revises:
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "dl_0001"
down_revision = None
branch_labels = ("deadlines",)
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS dl")
    op.create_table(
        "deadline",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("subject_type", sa.Text, nullable=False),
        sa.Column("subject_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("rule_id", sa.Text, nullable=False),
        sa.Column("ruleset", sa.Text, nullable=False),
        sa.Column("revision", sa.Text, nullable=False),
        sa.Column("clause", sa.Text),
        sa.Column("source_status", sa.Text, nullable=False),
        sa.Column("anchor_event_seq", sa.Integer),
        sa.Column("anchor_at", sa.DateTime(timezone=True)),
        sa.Column("anchor_date", sa.Date),
        sa.Column("duration_value", sa.Integer),
        sa.Column("duration_unit", sa.Text),
        sa.Column("clock_kind", sa.Text, nullable=False),
        sa.Column("calendar_id", sa.Text),
        sa.Column("clock_owner", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_date", sa.Date, nullable=False),
        sa.Column("due_version", sa.Integer, nullable=False),
        sa.Column("paused_at", sa.DateTime(timezone=True)),
        sa.Column("next_fire_at", sa.DateTime(timezone=True)),
        sa.Column("explanation", sa.Text, nullable=False),
        schema="dl",
    )
    op.create_index("ix_dl_deadline_subject_id", "deadline", ["subject_id"], schema="dl")
    op.create_index("uq_deadline_live", "deadline", ["subject_type", "subject_id", "rule_id"], unique=True,
                    schema="dl", postgresql_where=sa.text("status IN ('RUNNING', 'PAUSED')"))


def downgrade() -> None:
    op.execute("DROP SCHEMA dl CASCADE")
