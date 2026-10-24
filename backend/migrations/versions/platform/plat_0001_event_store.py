"""platform: event store, ledger, notes, personal data, outbox

Revision ID: plat_0001
Revises:
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "plat_0001"
down_revision = None
branch_labels = ("platform",)
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS plat")
    op.create_table(
        "domain_event",
        sa.Column("seq", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("id", pg.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("aggregate_type", sa.Text, nullable=False),
        sa.Column("aggregate_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column("event_version", sa.Integer, nullable=False),
        sa.Column("actor_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("reason_code", sa.Text),
        sa.Column("ruleset_rev", sa.Text),
        sa.Column("payload", pg.JSONB, nullable=False),
        sa.Column("note_ref", pg.UUID(as_uuid=True)),
        sa.Column("note_hash", sa.Text),
        sa.Column("personal_ref", pg.UUID(as_uuid=True)),
        schema="plat",
    )
    op.create_index("ix_plat_domain_event_aggregate_id", "domain_event", ["aggregate_id"], schema="plat")
    op.create_table(
        "ledger_entry",
        sa.Column("seq", sa.BigInteger, sa.ForeignKey("plat.domain_event.seq"), primary_key=True),
        sa.Column("event_hash", sa.Text, nullable=False),
        sa.Column("prev_hash", sa.Text, nullable=False),
        sa.Column("entry_hash", sa.Text, nullable=False),
        sa.Column("signature", sa.Text),
        schema="plat",
    )
    op.create_table(
        "case_note",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("body", sa.Text),
        sa.Column("body_hash", sa.Text, nullable=False),
        sa.Column("retain_until", sa.Date),
        sa.Column("redacted_at", sa.DateTime(timezone=True)),
        schema="plat",
    )
    op.create_table(
        "personal_data",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("data", pg.JSONB),
        sa.Column("purpose", sa.Text, nullable=False),
        sa.Column("retain_until", sa.Date),
        sa.Column("erased_at", sa.DateTime(timezone=True)),
        schema="plat",
    )
    op.create_table(
        "outbox",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("alert_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.Text, nullable=False),
        sa.Column("template", sa.Text, nullable=False),
        sa.Column("recipient_ref", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("alert_id", "channel"),
        schema="plat",
    )


def downgrade() -> None:
    op.execute("DROP SCHEMA plat CASCADE")
