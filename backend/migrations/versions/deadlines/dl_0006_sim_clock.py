"""deadlines: demo clock offset shared by the API and the timer worker

Revision ID: dl_0006_sim_clock
Revises: dl_0005_timer_alerts
"""
from alembic import op
import sqlalchemy as sa

revision = "dl_0006_sim_clock"
down_revision = "dl_0005_timer_alerts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # One row at most. Only read in demo mode; outside it the clock is always real time, whatever is stored here.
    op.create_table(
        "sim_clock",
        sa.Column("id", sa.SmallInteger, primary_key=True, autoincrement=False),
        sa.Column("offset_seconds", sa.BigInteger, nullable=False, server_default=sa.text("0")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("id = 1", name="ck_dl_sim_clock_single_row"),
        schema="dl",
    )


def downgrade() -> None:
    op.drop_table("sim_clock", schema="dl")
