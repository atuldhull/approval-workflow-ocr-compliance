"""deadlines: finalize calendar versions and enforce immutable source data

Revision ID: dl_0003_immutable_calendars
Revises: dl_0002_calendar_versions
"""
from alembic import op
import sqlalchemy as sa

revision = "dl_0003_immutable_calendars"
down_revision = "dl_0002_calendar_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing rows were already usable calendar versions; preserve and seal them.
    op.add_column(
        "calendar_version",
        sa.Column("is_finalized", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="dl",
    )
    op.execute("UPDATE dl.calendar_version SET is_finalized = TRUE")

    op.drop_constraint("ck_dl_calendar_id_versioned", "calendar_version", schema="dl", type_="check")
    op.create_check_constraint(
        "ck_dl_calendar_id_exactly_one_version_separator",
        "calendar_version",
        "length(calendar_id) - length(replace(calendar_id, '@', '')) = 1 "
        "AND btrim(split_part(calendar_id, '@', 1), ' ' || chr(9) || chr(10) || chr(11) || chr(12) || chr(13)) <> '' "
        "AND btrim(split_part(calendar_id, '@', 2), ' ' || chr(9) || chr(10) || chr(11) || chr(12) || chr(13)) <> ''",
        schema="dl",
    )
    op.create_check_constraint(
        "ck_dl_calendar_verified_source_ref",
        "calendar_version",
        "source_status <> 'verified' OR "
        "(source_ref IS NOT NULL AND btrim(source_ref, ' ' || chr(9) || chr(10) || chr(11) || chr(12) || chr(13)) <> '')",
        schema="dl",
    )

    # A calendar's complete source data is inserted in one transaction and then
    # finalized. Deferred validation prevents an unfinalized row being committed.
    op.execute(
        """
        CREATE FUNCTION dl.guard_calendar_version_update() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'calendar versions cannot be deleted; register a new version instead'
                    USING ERRCODE = '55000';
            END IF;
            IF OLD.is_finalized THEN
                RAISE EXCEPTION 'finalized calendar versions are immutable; register a new version instead'
                    USING ERRCODE = '55000';
            END IF;
            IF NEW.is_finalized IS NOT TRUE
               OR NEW.calendar_id IS DISTINCT FROM OLD.calendar_id
               OR NEW.working_weekdays IS DISTINCT FROM OLD.working_weekdays
               OR NEW.source_status IS DISTINCT FROM OLD.source_status
               OR NEW.source_ref IS DISTINCT FROM OLD.source_ref THEN
                RAISE EXCEPTION 'calendar version update may only finalize an unchanged version'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_dl_calendar_version_immutable
            BEFORE UPDATE OR DELETE ON dl.calendar_version
            FOR EACH ROW EXECUTE FUNCTION dl.guard_calendar_version_update()
        """
    )
    op.execute(
        """
        CREATE FUNCTION dl.guard_calendar_holiday_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            old_calendar_id text;
            new_calendar_id text;
            is_finalized boolean;
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                old_calendar_id := OLD.calendar_id;
                SELECT calendar_version.is_finalized INTO is_finalized
                FROM dl.calendar_version AS calendar_version
                WHERE calendar_version.calendar_id = old_calendar_id
                FOR UPDATE;
                IF is_finalized IS TRUE THEN
                    RAISE EXCEPTION 'holidays of a finalized calendar version are immutable'
                        USING ERRCODE = '55000';
                END IF;
            END IF;
            IF TG_OP <> 'DELETE' THEN
                new_calendar_id := NEW.calendar_id;
                SELECT calendar_version.is_finalized INTO is_finalized
                FROM dl.calendar_version AS calendar_version
                WHERE calendar_version.calendar_id = new_calendar_id
                FOR UPDATE;
                IF is_finalized IS TRUE THEN
                    RAISE EXCEPTION 'holidays of a finalized calendar version are immutable'
                        USING ERRCODE = '55000';
                END IF;
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_dl_calendar_holiday_immutable
            BEFORE INSERT OR UPDATE OR DELETE ON dl.holiday
            FOR EACH ROW EXECUTE FUNCTION dl.guard_calendar_holiday_change()
        """
    )
    op.execute(
        """
        CREATE FUNCTION dl.require_finalized_calendar_version() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM dl.calendar_version
                WHERE calendar_id = NEW.calendar_id AND NOT is_finalized
            ) THEN
                RAISE EXCEPTION 'calendar version must be finalized before transaction commit'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NULL;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_dl_calendar_version_finalized_at_commit
            AFTER INSERT OR UPDATE ON dl.calendar_version
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION dl.require_finalized_calendar_version()
        """
    )

    op.drop_constraint("holiday_calendar_id_fkey", "holiday", schema="dl", type_="foreignkey")
    op.create_foreign_key(
        "fk_dl_holiday_calendar_id_calendar_version",
        "holiday",
        "calendar_version",
        ["calendar_id"],
        ["calendar_id"],
        source_schema="dl",
        referent_schema="dl",
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_dl_calendar_version_finalized_at_commit ON dl.calendar_version")
    op.execute("DROP TRIGGER trg_dl_calendar_version_immutable ON dl.calendar_version")
    op.execute("DROP FUNCTION dl.guard_calendar_version_update()")
    op.execute("DROP TRIGGER trg_dl_calendar_holiday_immutable ON dl.holiday")
    op.execute("DROP FUNCTION dl.guard_calendar_holiday_change()")
    op.execute("DROP FUNCTION dl.require_finalized_calendar_version()")

    op.drop_constraint("fk_dl_holiday_calendar_id_calendar_version", "holiday", schema="dl", type_="foreignkey")
    op.create_foreign_key(
        "holiday_calendar_id_fkey",
        "holiday",
        "calendar_version",
        ["calendar_id"],
        ["calendar_id"],
        source_schema="dl",
        referent_schema="dl",
        ondelete="CASCADE",
    )

    op.drop_constraint(
        "ck_dl_calendar_verified_source_ref", "calendar_version", schema="dl", type_="check"
    )
    op.drop_constraint(
        "ck_dl_calendar_id_exactly_one_version_separator", "calendar_version", schema="dl", type_="check"
    )
    op.create_check_constraint(
        "ck_dl_calendar_id_versioned",
        "calendar_version",
        "calendar_id LIKE '%@%'",
        schema="dl",
    )
    op.drop_column("calendar_version", "is_finalized", schema="dl")