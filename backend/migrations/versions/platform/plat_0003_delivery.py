"""platform: notification delivery - leases, attempts, in-app inbox, recipient directory

Revision ID: plat_0003
Revises: plat_0002
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "plat_0003"
down_revision = "plat_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name, type_ in (("claimed_by", sa.Text), ("lease_until", sa.DateTime(timezone=True)), ("last_error", sa.Text),
                        ("delivered_at", sa.DateTime(timezone=True)), ("dead_at", sa.DateTime(timezone=True))):
        op.add_column("outbox", sa.Column(name, type_), schema="plat")
    op.create_index("ix_plat_outbox_due", "outbox", ["status", "next_attempt_at"], schema="plat")

    op.create_table(
        "delivery_attempt",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("outbox_id", pg.UUID(as_uuid=True), sa.ForeignKey("plat.outbox.id"), nullable=False),
        sa.Column("attempt_no", sa.Integer, nullable=False),
        sa.Column("worker", sa.Text, nullable=False),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.Text, nullable=False),
        sa.Column("error_category", sa.Text),
        sa.Column("provider_ref", sa.Text),
        schema="plat",
    )
    op.create_index("ix_plat_delivery_attempt_outbox_id", "delivery_attempt", ["outbox_id"], schema="plat")
    op.create_index("ix_plat_delivery_attempt_finished_at", "delivery_attempt", ["finished_at"], schema="plat")

    op.create_table(
        "notification",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("outbox_id", pg.UUID(as_uuid=True), sa.ForeignKey("plat.outbox.id"), nullable=False, unique=True),
        sa.Column("alert_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("recipient_ref", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("template", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        schema="plat",
    )
    op.create_index("ix_plat_notification_recipient_ref", "notification", ["recipient_ref"], schema="plat")

    op.create_table(
        "recipient_member",
        sa.Column("recipient_ref", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", pg.UUID(as_uuid=True), primary_key=True),
        schema="plat",
    )
    op.create_index("ix_plat_recipient_member_user_id", "recipient_member", ["user_id"], schema="plat")

    op.create_table(
        "user_contact",
        sa.Column("user_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("channel", sa.Text, primary_key=True),
        sa.Column("personal_ref", pg.UUID(as_uuid=True), sa.ForeignKey("plat.personal_data.id"), nullable=False),
        schema="plat",
    )


def downgrade() -> None:
    for table in ("user_contact", "recipient_member", "notification", "delivery_attempt"):
        op.drop_table(table, schema="plat")
    op.drop_index("ix_plat_outbox_due", "outbox", schema="plat")
    for name in ("dead_at", "delivered_at", "last_error", "lease_until", "claimed_by"):
        op.drop_column("outbox", name, schema="plat")
