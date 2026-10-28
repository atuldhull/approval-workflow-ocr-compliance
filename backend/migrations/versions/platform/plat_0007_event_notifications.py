"""platform: outbox and inbox rows for recorded events, not only alerts; the notifier's event-log cursor

Revision ID: plat_0007
Revises: plat_0006
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "plat_0007"
down_revision = "plat_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("outbox", "alert_id", nullable=True, schema="plat")
    op.add_column("outbox", sa.Column("source_event_id", pg.UUID(as_uuid=True)), schema="plat")
    op.create_unique_constraint("uq_plat_outbox_event_recipient_channel", "outbox",
                                ["source_event_id", "recipient_ref", "channel"], schema="plat")
    op.create_check_constraint("ck_plat_outbox_one_subject", "outbox",
                               "(alert_id IS NULL) <> (source_event_id IS NULL)", schema="plat")

    op.alter_column("notification", "alert_id", nullable=True, schema="plat")
    op.add_column("notification", sa.Column("source_event_id", pg.UUID(as_uuid=True)), schema="plat")
    op.add_column("notification", sa.Column("context", pg.JSONB), schema="plat")

    op.create_table(
        "notify_cursor",
        sa.Column("name", sa.Text, primary_key=True),
        sa.Column("seq", sa.BigInteger, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema="plat",
    )


def downgrade() -> None:
    # rows about events have no alert; they are removed before alert_id becomes required again
    op.drop_table("notify_cursor", schema="plat")
    op.execute("DELETE FROM plat.notification WHERE alert_id IS NULL")
    op.execute("DELETE FROM plat.delivery_recipient WHERE outbox_id IN "
               "(SELECT id FROM plat.outbox WHERE alert_id IS NULL)")
    op.execute("DELETE FROM plat.delivery_attempt WHERE outbox_id IN (SELECT id FROM plat.outbox WHERE alert_id IS NULL)")
    op.execute("DELETE FROM plat.outbox WHERE alert_id IS NULL")
    op.drop_column("notification", "context", schema="plat")
    op.drop_column("notification", "source_event_id", schema="plat")
    op.alter_column("notification", "alert_id", nullable=False, schema="plat")
    op.drop_constraint("ck_plat_outbox_one_subject", "outbox", type_="check", schema="plat")
    op.drop_constraint("uq_plat_outbox_event_recipient_channel", "outbox", type_="unique", schema="plat")
    op.drop_column("outbox", "source_event_id", schema="plat")
    op.alter_column("outbox", "alert_id", nullable=False, schema="plat")
