"""deadlines: explicit working-day calendar versions

Revision ID: dl_0002_calendar_versions
Revises: dl_0001
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "dl_0002_calendar_versions"
down_revision = "dl_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("deadline", sa.Column("count_anchor_day", sa.Boolean), schema="dl")
    op.create_check_constraint(
        "ck_dl_deadline_working_days_calendar",
        "deadline",
        "duration_unit != 'working_days' OR (calendar_id IS NOT NULL AND count_anchor_day IS NOT NULL)",
        schema="dl",
    )
    op.create_table(
        "calendar_version",
        sa.Column("calendar_id", sa.Text, primary_key=True),
        sa.Column("working_weekdays", pg.ARRAY(sa.SmallInteger), nullable=False),
        sa.Column("source_status", sa.Text, nullable=False),
        sa.Column("source_ref", sa.Text),
        sa.CheckConstraint("cardinality(working_weekdays) > 0", name="ck_dl_calendar_weekdays_not_empty"),
        sa.CheckConstraint(
            "working_weekdays <@ ARRAY[0,1,2,3,4,5,6]::smallint[]",
            name="ck_dl_calendar_weekdays_range",
        ),
        sa.CheckConstraint("calendar_id LIKE '%@%'", name="ck_dl_calendar_id_versioned"),
        sa.CheckConstraint("source_status IN ('verified', 'demo_assumption')", name="ck_dl_calendar_source_status"),
        schema="dl",
    )
    op.create_foreign_key(
        "fk_dl_deadline_calendar_id_calendar_version",
        "deadline",
        "calendar_version",
        ["calendar_id"],
        ["calendar_id"],
        source_schema="dl",
        referent_schema="dl",
        ondelete="RESTRICT",
    )
    op.create_table(
        "holiday",
        sa.Column("calendar_id", sa.Text,
                  sa.ForeignKey("dl.calendar_version.calendar_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("holiday_date", sa.Date, primary_key=True),
        sa.Column("label", sa.Text),
        sa.Column("source_ref", sa.Text),
        schema="dl",
    )


def downgrade() -> None:
    op.drop_table("holiday", schema="dl")
    op.drop_constraint("fk_dl_deadline_calendar_id_calendar_version", "deadline", schema="dl")
    op.drop_table("calendar_version", schema="dl")
    op.drop_constraint("ck_dl_deadline_working_days_calendar", "deadline", schema="dl")
    op.drop_column("deadline", "count_anchor_day", schema="dl")
