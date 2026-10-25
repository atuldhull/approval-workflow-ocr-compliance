"""deadlines: prevent truncating immutable calendar source data

Revision ID: dl_0004_calendar_truncate_guards
Revises: dl_0003_immutable_calendars
"""
from alembic import op

revision = "dl_0004_calendar_truncate_guards"
down_revision = "dl_0003_immutable_calendars"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Row-level DELETE triggers do not fire for TRUNCATE. Guard both source tables
    # so a bulk operation cannot erase finalized calendar data.
    op.execute(
        """
        CREATE FUNCTION dl.guard_calendar_source_truncate() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'calendar source data cannot be truncated; register a new version instead'
                USING ERRCODE = '55000';
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_dl_calendar_version_no_truncate
            BEFORE TRUNCATE ON dl.calendar_version
            FOR EACH STATEMENT EXECUTE FUNCTION dl.guard_calendar_source_truncate()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_dl_holiday_no_truncate
            BEFORE TRUNCATE ON dl.holiday
            FOR EACH STATEMENT EXECUTE FUNCTION dl.guard_calendar_source_truncate()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_dl_holiday_no_truncate ON dl.holiday")
    op.execute("DROP TRIGGER trg_dl_calendar_version_no_truncate ON dl.calendar_version")
    op.execute("DROP FUNCTION dl.guard_calendar_source_truncate()")
