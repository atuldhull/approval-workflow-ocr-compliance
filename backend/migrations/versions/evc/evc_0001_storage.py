"""evc: expert pool, scheduling storage and database-enforced no double booking."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "evc_0001"
down_revision = None
branch_labels = ("evc",)
depends_on = "wf_0001"  # stable application/institution IDs; independent EVC head


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS evc")
    op.execute("""
        CREATE FUNCTION evc.coded_tags(value text[]) RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
            SELECT value IS NOT NULL AND COALESCE(array_ndims(value), 1) = 1
                AND NOT EXISTS (SELECT 1 FROM unnest(value) t WHERE t IS NULL OR t !~ '^[A-Z][A-Z0-9_]*$')
                AND cardinality(value) = (SELECT count(DISTINCT t) FROM unnest(value) t)
        $$
    """)
    op.execute("""
        CREATE FUNCTION evc.numeric_json(value jsonb) RETURNS boolean LANGUAGE plpgsql IMMUTABLE AS $$
        DECLARE entry record;
        BEGIN
            CASE jsonb_typeof(value)
                WHEN 'object' THEN
                    FOR entry IN SELECT key, val FROM jsonb_each(value) AS e(key, val) LOOP
                        IF entry.key !~ '^[A-Za-z][A-Za-z0-9_]*$' OR NOT evc.numeric_json(entry.val) THEN RETURN false; END IF;
                    END LOOP;
                    RETURN true;
                WHEN 'array' THEN
                    FOR entry IN SELECT val FROM jsonb_array_elements(value) AS e(val) LOOP
                        IF NOT evc.numeric_json(entry.val) THEN RETURN false; END IF;
                    END LOOP;
                    RETURN true;
                WHEN 'number' THEN RETURN true;
                WHEN 'boolean' THEN RETURN true;
                WHEN 'null' THEN RETURN true;
                ELSE RETURN false;
            END CASE;
        END $$
    """)
    op.create_table("evc_request",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("application_id", pg.UUID(as_uuid=True), sa.ForeignKey("wf.application.id"), nullable=False),
        sa.Column("institution_ref", pg.UUID(as_uuid=True), sa.ForeignKey("wf.institution.id"), nullable=False),
        sa.Column("region", sa.Text, nullable=False), sa.Column("category", sa.Text, nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("earliest_date", sa.Date, nullable=False), sa.Column("due_by", sa.Date, nullable=False),
        sa.Column("status", sa.Text, nullable=False), sa.Column("priority_key", sa.Text, nullable=False),
        sa.CheckConstraint("status IN ('QUEUED','PROPOSED','PUBLISHED','DONE','CANCELLED')", name="ck_evc_request_status"),
        sa.CheckConstraint("earliest_date <= due_by", name="ck_evc_request_window"),
        sa.CheckConstraint("category ~ '^[A-Z][A-Z0-9_]*$'", name="ck_evc_request_category"),
        sa.CheckConstraint("priority_key ~ '^[A-Za-z0-9_:-]+$'", name="ck_evc_request_priority"), schema="evc")
    op.create_index("ix_evc_request_queue", "evc_request", ["status", "due_by", "priority_key", "id"], schema="evc")
    op.create_index("ix_evc_request_case", "evc_request", ["application_id"], schema="evc")
    op.create_table("expert",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_ref", pg.UUID(as_uuid=True), nullable=False), sa.Column("region", sa.Text, nullable=False),
        sa.Column("expertise_tags", pg.ARRAY(sa.Text), nullable=False),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.UniqueConstraint("user_ref", name="uq_evc_expert_user"),
        sa.CheckConstraint("evc.coded_tags(expertise_tags)", name="ck_evc_expert_tags"), schema="evc")
    op.create_table("availability",
        sa.Column("expert_id", pg.UUID(as_uuid=True), sa.ForeignKey("evc.expert.id"), primary_key=True),
        sa.Column("date", sa.Date, primary_key=True), sa.Column("slot_part", sa.Text, primary_key=True),
        sa.Column("available", sa.Boolean, nullable=False),
        sa.CheckConstraint("slot_part ~ '^[A-Z][A-Z0-9_]*$'", name="ck_evc_availability_part"), schema="evc")
    op.create_table("coi",
        sa.Column("expert_id", pg.UUID(as_uuid=True), sa.ForeignKey("evc.expert.id"), primary_key=True),
        sa.Column("institution_ref", pg.UUID(as_uuid=True), sa.ForeignKey("wf.institution.id"), primary_key=True),
        sa.Column("reason_code", sa.Text, primary_key=True), sa.Column("source", sa.Text, primary_key=True),
        sa.CheckConstraint("reason_code ~ '^[A-Z][A-Z0-9_]*$'", name="ck_evc_coi_reason"),
        sa.CheckConstraint("source ~ '^[A-Z][A-Z0-9_]*$'", name="ck_evc_coi_source"), schema="evc")
    op.create_table("slot",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True), sa.Column("date", sa.Date, nullable=False),
        sa.Column("slot_part", sa.Text, nullable=False), sa.Column("capacity", sa.Integer, nullable=False),
        sa.CheckConstraint("slot_part ~ '^[A-Z][A-Z0-9_]*$'", name="ck_evc_slot_part"),
        sa.CheckConstraint("capacity > 0", name="ck_evc_slot_capacity"), schema="evc")
    op.create_table("schedule_run",
        sa.Column("run_id", pg.UUID(as_uuid=True), primary_key=True), sa.Column("algorithm", sa.Text, nullable=False),
        sa.Column("parameters", pg.JSONB, nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text, nullable=False), sa.Column("metrics", pg.JSONB, nullable=False),
        sa.CheckConstraint("algorithm IN ('EDF','CPSAT')", name="ck_evc_run_algorithm"),
        sa.CheckConstraint("status ~ '^[A-Z][A-Z0-9_]*$'", name="ck_evc_run_status"),
        sa.CheckConstraint("jsonb_typeof(parameters) = 'object' AND evc.numeric_json(parameters)", name="ck_evc_run_parameters"),
        sa.CheckConstraint("jsonb_typeof(metrics) = 'object' AND evc.numeric_json(metrics)", name="ck_evc_run_metrics"), schema="evc")
    op.create_table("assignment",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("evc_request_id", pg.UUID(as_uuid=True), sa.ForeignKey("evc.evc_request.id"), nullable=False),
        sa.Column("slot_id", pg.UUID(as_uuid=True), sa.ForeignKey("evc.slot.id"), nullable=False),
        sa.Column("expert_ids", pg.ARRAY(pg.UUID(as_uuid=True)), nullable=False), sa.Column("panel_role", sa.Text, nullable=False),
        sa.Column("published", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("schedule_run_id", pg.UUID(as_uuid=True), sa.ForeignKey("evc.schedule_run.run_id"), nullable=False),
        sa.CheckConstraint("panel_role ~ '^[A-Z][A-Z0-9_]*$'", name="ck_evc_assignment_role"), schema="evc")
    op.create_index("ix_evc_assignment_request", "assignment", ["evc_request_id"], schema="evc")
    op.create_index("ix_evc_assignment_slot", "assignment", ["slot_id"], schema="evc")
    op.create_table("assignment_expert",
        sa.Column("assignment_id", pg.UUID(as_uuid=True), sa.ForeignKey("evc.assignment.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("expert_id", pg.UUID(as_uuid=True), sa.ForeignKey("evc.expert.id"), primary_key=True),
        sa.Column("slot_id", pg.UUID(as_uuid=True), sa.ForeignKey("evc.slot.id"), nullable=False), sa.Column("date", sa.Date, nullable=False),
        sa.Column("slot_part", sa.Text, nullable=False), sa.Column("published", sa.Boolean, nullable=False), schema="evc")
    op.create_index("uq_evc_published_expert_time", "assignment_expert", ["expert_id", "date", "slot_part"],
                    unique=True, postgresql_where=sa.text("published"), schema="evc")
    op.execute("""
        CREATE FUNCTION evc.validate_panel() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.expert_ids IS NULL OR cardinality(NEW.expert_ids) = 0 OR array_ndims(NEW.expert_ids) != 1 THEN
                RAISE EXCEPTION 'EVC_PANEL_IDS_INVALID' USING ERRCODE = '23514';
            END IF;
            IF array_position(NEW.expert_ids, NULL) IS NOT NULL
               OR cardinality(NEW.expert_ids) != (SELECT count(DISTINCT id) FROM unnest(NEW.expert_ids) id) THEN
                RAISE EXCEPTION 'EVC_PANEL_IDS_INVALID' USING ERRCODE = '23514';
            END IF;
            -- SHARE also conflicts with non-key calendar edits; KEY SHARE would not.
            -- Take this lock before replacing memberships to avoid stale snapshots.
            PERFORM id FROM evc.slot WHERE id = NEW.slot_id FOR SHARE;
            RETURN NEW;
        END $$
    """)
    op.execute("""CREATE TRIGGER assignment_validate_panel BEFORE INSERT OR UPDATE ON evc.assignment
                  FOR EACH ROW EXECUTE FUNCTION evc.validate_panel()""")
    op.execute("""
        CREATE FUNCTION evc.sync_membership() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP != 'INSERT' THEN
                DELETE FROM evc.assignment_expert WHERE assignment_id = OLD.id;
            END IF;
            IF TG_OP != 'DELETE' THEN
                INSERT INTO evc.assignment_expert (assignment_id, expert_id, slot_id, date, slot_part, published)
                    SELECT NEW.id, e.id, s.id, s.date, s.slot_part, NEW.published
                    FROM evc.slot s CROSS JOIN unnest(NEW.expert_ids) AS e(id) WHERE s.id = NEW.slot_id;
                RETURN NEW;
            END IF;
            RETURN OLD;
        END $$
    """)
    op.execute("""CREATE TRIGGER assignment_sync_membership AFTER INSERT OR UPDATE OR DELETE ON evc.assignment
                  FOR EACH ROW EXECUTE FUNCTION evc.sync_membership()""")
    op.execute("""
        CREATE FUNCTION evc.protect_membership() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF pg_trigger_depth() < 2 THEN
                RAISE EXCEPTION 'EVC_MEMBERSHIP_TRIGGER_OWNED' USING ERRCODE = '23514';
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""CREATE TRIGGER membership_trigger_owned BEFORE INSERT OR UPDATE OR DELETE ON evc.assignment_expert
                  FOR EACH ROW EXECUTE FUNCTION evc.protect_membership()""")
    op.execute("""
        CREATE FUNCTION evc.sync_slot_calendar() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            UPDATE evc.assignment_expert SET date = NEW.date, slot_part = NEW.slot_part WHERE slot_id = NEW.id;
            RETURN NEW;
        END $$
    """)
    op.execute("""CREATE TRIGGER slot_sync_calendar AFTER UPDATE OF date, slot_part ON evc.slot
                  FOR EACH ROW EXECUTE FUNCTION evc.sync_slot_calendar()""")


def downgrade() -> None:
    for table in ("assignment_expert", "assignment", "schedule_run", "slot", "coi", "availability", "expert", "evc_request"):
        op.drop_table(table, schema="evc")
    for name in ("sync_slot_calendar()", "protect_membership()", "sync_membership()", "validate_panel()", "numeric_json(jsonb)", "coded_tags(text[])"):
        op.execute(f"DROP FUNCTION evc.{name}")
    op.execute("DROP SCHEMA evc")
