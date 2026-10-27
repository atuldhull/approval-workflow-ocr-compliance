"""deadlines: timer claims, timer outcomes and escalating alerts

Revision ID: dl_0005_timer_alerts
Revises: dl_0004_calendar_truncate_guards
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "dl_0005_timer_alerts"
down_revision = "dl_0004_calendar_truncate_guards"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("deadline", sa.Column("alert_level", sa.SmallInteger, nullable=False, server_default=sa.text("0")),
                  schema="dl")
    op.add_column("deadline", sa.Column("timer_fence", sa.BigInteger, nullable=False, server_default=sa.text("0")),
                  schema="dl")
    op.add_column("deadline", sa.Column("timer_claimed_by", sa.Text), schema="dl")
    op.add_column("deadline", sa.Column("timer_lease_until", sa.DateTime(timezone=True)), schema="dl")
    op.add_column("deadline", sa.Column("timer_attempts", sa.Integer, nullable=False, server_default=sa.text("0")),
                  schema="dl")
    # Clocks opened before the worker existed have no firing time. Make them due now: the worker then works out
    # the real schedule from the ruleset (and only reschedules if nothing is due yet).
    op.execute("UPDATE dl.deadline SET next_fire_at = now() WHERE status = 'RUNNING' AND next_fire_at IS NULL")
    op.create_index("ix_dl_deadline_timer_due", "deadline", ["next_fire_at"], schema="dl",
                    postgresql_where=sa.text("status = 'RUNNING'"))

    op.create_table(
        "alert",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("deadline_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("dl.deadline.id", ondelete="RESTRICT", name="fk_dl_alert_deadline_id_deadline"),
                  nullable=False),
        sa.Column("level", sa.SmallInteger, nullable=False),
        sa.Column("due_version", sa.Integer, nullable=False),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("recipient_ref", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_type", sa.Text, nullable=False),
        sa.Column("subject_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("institution_id", pg.UUID(as_uuid=True)),
        sa.Column("region", sa.Text),
        sa.Column("template", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("reason", sa.Text),
        sa.Column("from_alert_id", pg.UUID(as_uuid=True)),
        sa.Column("raised_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("escalated_at", sa.DateTime(timezone=True)),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column("acknowledged_by", pg.UUID(as_uuid=True)),
        sa.UniqueConstraint("deadline_id", "level", "due_version", name="uq_dl_alert_level"),
        sa.CheckConstraint("status IN ('OPEN', 'VACANT', 'ESCALATED', 'ACKNOWLEDGED')", name="ck_dl_alert_status"),
        sa.CheckConstraint("reason IS NULL OR reason IN ('VACANCY', 'WINDOW_ELAPSED')", name="ck_dl_alert_reason"),
        sa.CheckConstraint("level > 0 OR (reason IS NULL AND from_alert_id IS NULL)",
                           name="ck_dl_alert_escalation_link"),
        schema="dl",
    )
    op.create_index("ix_dl_alert_region", "alert", ["region"], schema="dl")
    op.create_index("ix_dl_alert_institution_id", "alert", ["institution_id"], schema="dl")

    op.create_table(
        "timer_outcome",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("deadline_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("dl.deadline.id", ondelete="RESTRICT",
                                name="fk_dl_timer_outcome_deadline_id_deadline"), nullable=False),
        sa.Column("fence", sa.BigInteger, nullable=False),
        sa.Column("due_version", sa.Integer, nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True)),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("worker", sa.Text, nullable=False),
        sa.Column("outcome", sa.Text, nullable=False),
        sa.Column("levels_raised", sa.SmallInteger, nullable=False),
        sa.Column("next_fire_at", sa.DateTime(timezone=True)),
        sa.Column("detail", sa.Text),
        sa.UniqueConstraint("deadline_id", "fence", name="uq_dl_timer_outcome_fence"),
        sa.CheckConstraint(
            "outcome IN ('SCHEDULED', 'ALERTED', 'ACKNOWLEDGED', 'LADDER_DONE', 'NOT_RUNNING', 'RETRY', 'FAILED')",
            name="ck_dl_timer_outcome"),
        schema="dl",
    )
    op.create_index("ix_dl_timer_outcome_deadline_id", "timer_outcome", ["deadline_id"], schema="dl")


def downgrade() -> None:
    op.drop_table("timer_outcome", schema="dl")
    op.drop_table("alert", schema="dl")
    op.drop_index("ix_dl_deadline_timer_due", "deadline", schema="dl")
    for column in ("timer_attempts", "timer_lease_until", "timer_claimed_by", "timer_fence", "alert_level"):
        op.drop_column("deadline", column, schema="dl")
