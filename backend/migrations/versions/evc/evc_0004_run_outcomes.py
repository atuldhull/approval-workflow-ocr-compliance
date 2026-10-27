"""evc: keep each run's region scope and per-request outcome so runs can be listed and read back."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "evc_0004"
down_revision = "evc_0003"
branch_labels = None
depends_on = None

EXPLANATIONS = ("NO_AVAILABILITY", "PANEL_INCOMPLETE", "COI_ONLY", "CAPACITY_EXHAUSTED", "EXPERT_DAILY_CAP", "NO_FEASIBLE_SLOT")


def upgrade() -> None:
    # Older runs keep a NULL scope and no outcome rows; nothing is back-filled or guessed.
    op.add_column("schedule_run", sa.Column("region_scope", sa.Text), schema="evc")
    op.create_check_constraint("ck_evc_run_region_scope", "schedule_run",
                               "region_scope IS NULL OR (region_scope <> '' AND region_scope = upper(region_scope))", schema="evc")
    codes = ", ".join(f"'{code}'" for code in EXPLANATIONS)
    op.create_table(
        "schedule_run_request",
        sa.Column("run_id", pg.UUID(as_uuid=True), sa.ForeignKey("evc.schedule_run.run_id"), primary_key=True),
        sa.Column("request_id", pg.UUID(as_uuid=True), sa.ForeignKey("evc.evc_request.id"), primary_key=True),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("outcome", sa.Text, nullable=False),
        sa.Column("explanation_code", sa.Text),
        sa.CheckConstraint("ordinal >= 0", name="ck_evc_run_request_ordinal"),
        sa.CheckConstraint(f"(outcome = 'PROPOSED' AND explanation_code IS NULL) OR "
                           f"(outcome = 'UNSCHEDULED' AND explanation_code IN ({codes}))", name="ck_evc_run_request_outcome"),
        sa.UniqueConstraint("run_id", "ordinal", name="uq_evc_run_request_ordinal"),
        schema="evc",
    )
    op.create_index("ix_evc_run_request_request", "schedule_run_request", ["request_id"], schema="evc")


def downgrade() -> None:
    op.drop_index("ix_evc_run_request_request", table_name="schedule_run_request", schema="evc")
    op.drop_table("schedule_run_request", schema="evc")
    op.drop_constraint("ck_evc_run_region_scope", "schedule_run", type_="check", schema="evc")
    op.drop_column("schedule_run", "region_scope", schema="evc")
