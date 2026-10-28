"""deadlines: a BREACHED clock stays live (one per subject and rule) and stays in the timer queue

Revision ID: dl_0007_breached_is_live
Revises: dl_0006_sim_clock
"""
from alembic import op
import sqlalchemy as sa

revision = "dl_0007_breached_is_live"
down_revision = "dl_0006_sim_clock"
branch_labels = None
depends_on = None


def _indexes(live: str, timer: str) -> None:
    op.drop_index("uq_deadline_live", "deadline", schema="dl")
    op.create_index("uq_deadline_live", "deadline", ["subject_type", "subject_id", "rule_id"], unique=True,
                    schema="dl", postgresql_where=sa.text(live))
    op.drop_index("ix_dl_deadline_timer_due", "deadline", schema="dl")
    op.create_index("ix_dl_deadline_timer_due", "deadline", ["next_fire_at"], schema="dl",
                    postgresql_where=sa.text(timer))


def upgrade() -> None:
    # Nothing was ever written as BREACHED before this revision, so the wider unique index cannot conflict.
    _indexes("status IN ('RUNNING', 'PAUSED', 'BREACHED')", "status IN ('RUNNING', 'BREACHED')")


def downgrade() -> None:
    _indexes("status IN ('RUNNING', 'PAUSED')", "status = 'RUNNING'")
