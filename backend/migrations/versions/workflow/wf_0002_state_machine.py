"""workflow: definition snapshots and pinned case state; preserve stage visits.

Revision ID: wf_0002
Revises: wf_0001
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "wf_0002"
down_revision = "wf_0001"
# Inherits branch_labels={'workflow'} from wf_0001; do not redefine the label.
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ruleset",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("key", sa.Text, nullable=False),
        sa.Column("version", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("checksum", sa.Text, nullable=False),
        sa.Column("demo_only", sa.Boolean, nullable=False),
        sa.Column("source_status", sa.Text, nullable=False),
        sa.Column("source_files", pg.JSONB, nullable=False),
        sa.Column("source_metadata", pg.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_ref", pg.UUID(as_uuid=True)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("approved_by_ref", pg.UUID(as_uuid=True)),
        sa.UniqueConstraint("key", name="uq_wf_ruleset_key"),
        sa.UniqueConstraint("id", "key", name="uq_wf_ruleset_id_key"),
        sa.CheckConstraint("status IN ('DRAFT', 'VALIDATED', 'APPROVED', 'ACTIVE', 'RETIRED')", name="ck_wf_ruleset_status"),
        sa.CheckConstraint("checksum ~ '^[0-9a-f]{64}$'", name="ck_wf_ruleset_checksum"),
        sa.CheckConstraint("(approved_at IS NULL) = (approved_by_ref IS NULL)", name="ck_wf_ruleset_approval_metadata"),
        schema="wf",
    )
    op.create_table(
        "route_def",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("ruleset_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("ruleset_key", sa.Text, nullable=False),
        sa.Column("route_id", sa.Text, nullable=False),
        sa.Column("category", sa.Text, nullable=False),
        sa.Column("stage_list", pg.JSONB, nullable=False),
        sa.Column("clause_citation", pg.JSONB),
        sa.ForeignKeyConstraint(["ruleset_id", "ruleset_key"], ["wf.ruleset.id", "wf.ruleset.key"], name="fk_wf_route_ruleset"),
        sa.UniqueConstraint("ruleset_key", "route_id", name="uq_wf_route_key_id"),
        schema="wf",
    )
    op.create_index("ix_wf_route_ruleset_id", "route_def", ["ruleset_id"], schema="wf")
    op.create_table(
        "transition",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("route_def_id", pg.UUID(as_uuid=True), sa.ForeignKey("wf.route_def.id"), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("template_id", sa.Text, nullable=False),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("from_stage", sa.Text, nullable=False),
        sa.Column("to_stage", sa.Text, nullable=False),
        sa.Column("roles", pg.JSONB, nullable=False),
        sa.Column("guards", pg.JSONB, nullable=False),
        sa.Column("timers", pg.JSONB, nullable=False),
        sa.Column("letter", pg.JSONB),
        sa.Column("reason_codes_required", sa.Boolean, nullable=False),
        sa.Column("emits_event", sa.Text, nullable=False),
        sa.Column("definition", pg.JSONB, nullable=False),
        sa.UniqueConstraint("route_def_id", "position", name="uq_wf_transition_position"),
        schema="wf",
    )
    op.create_index("ix_wf_transition_route_action", "transition", ["route_def_id", "action"], schema="wf")
    op.create_table(
        "case_state",
        sa.Column("application_id", pg.UUID(as_uuid=True), sa.ForeignKey("wf.application.id"), primary_key=True),
        sa.Column("route_id", sa.Text, nullable=False),
        sa.Column("ruleset_key", sa.Text, nullable=False),
        sa.Column("current_stage", sa.Text),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default=sa.text("1")),
        sa.ForeignKeyConstraint(["ruleset_key", "route_id"], ["wf.route_def.ruleset_key", "wf.route_def.route_id"], name="fk_wf_case_route"),
        sa.CheckConstraint("status IN ('DRAFT', 'IN_PROCESS', 'APPROVED', 'REJECTED', 'WITHDRAWN')", name="ck_wf_case_status"),
        sa.CheckConstraint("version >= 1", name="ck_wf_case_version"),
        schema="wf",
    )
    op.create_index("ix_wf_case_ruleset_route", "case_state", ["ruleset_key", "route_id"], schema="wf")
    op.alter_column("stage_visit", "left_at", new_column_name="exited_at", schema="wf")
    op.add_column("stage_visit", sa.Column("outcome", sa.Text), schema="wf")
    op.add_column("stage_visit", sa.Column("reason_code", sa.Text), schema="wf")
    op.add_column("stage_visit", sa.Column("note_ref", pg.UUID(as_uuid=True)), schema="wf")
    op.execute("""
        CREATE FUNCTION wf.enforce_case_pin() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF (NEW.application_id, NEW.ruleset_key, NEW.route_id)
             IS DISTINCT FROM (OLD.application_id, OLD.ruleset_key, OLD.route_id) THEN
            RAISE EXCEPTION 'case pin is immutable' USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER wf_case_pin_immutable
        BEFORE UPDATE OF application_id, ruleset_key, route_id ON wf.case_state
        FOR EACH ROW EXECUTE FUNCTION wf.enforce_case_pin()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER wf_case_pin_immutable ON wf.case_state")
    op.execute("DROP FUNCTION wf.enforce_case_pin()")
    op.drop_column("stage_visit", "note_ref", schema="wf")
    op.drop_column("stage_visit", "reason_code", schema="wf")
    op.drop_column("stage_visit", "outcome", schema="wf")
    op.alter_column("stage_visit", "exited_at", new_column_name="left_at", schema="wf")
    op.drop_table("case_state", schema="wf")
    op.drop_table("transition", schema="wf")
    op.drop_table("route_def", schema="wf")
    op.drop_table("ruleset", schema="wf")
