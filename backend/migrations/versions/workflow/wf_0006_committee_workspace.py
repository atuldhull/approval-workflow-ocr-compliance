"""workflow: member-attributed committee work and append-only reports."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "wf_0006"
down_revision = "wf_0005"
branch_labels = None  # inherits workflow; no second head
depends_on = None


def upgrade() -> None:
    op.create_table("committee",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("application_id", pg.UUID(as_uuid=True), sa.ForeignKey("wf.application.id"), nullable=False),
        sa.Column("type", sa.Text, nullable=False), sa.Column("status", sa.Text, nullable=False),
        sa.CheckConstraint("type IN ('SCRUTINY', 'RESCRUTINY', 'EVC', 'SHC', 'EC', 'COUNCIL')", name="ck_wf_committee_type"),
        sa.CheckConstraint("status IN ('ACTIVE', 'CLOSED')", name="ck_wf_committee_status"), schema="wf")
    op.create_index("ix_wf_committee_case", "committee", ["application_id"], schema="wf")
    op.create_table("committee_member",
        sa.Column("committee_id", pg.UUID(as_uuid=True), sa.ForeignKey("wf.committee.id"), primary_key=True),
        sa.Column("user_ref", pg.UUID(as_uuid=True), primary_key=True), sa.Column("role", sa.Text, nullable=False),
        sa.CheckConstraint("role IN ('CHAIR', 'MEMBER', 'SECRETARY')", name="ck_wf_committee_member_role"), schema="wf")
    op.create_table("task",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("committee_id", pg.UUID(as_uuid=True), sa.ForeignKey("wf.committee.id"), nullable=False),
        sa.Column("title_key", sa.Text, nullable=False), sa.Column("assignee_user_ref", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.UniqueConstraint("id", "committee_id", name="uq_wf_task_id_committee"),
        sa.ForeignKeyConstraint(["committee_id", "assignee_user_ref"],
            ["wf.committee_member.committee_id", "wf.committee_member.user_ref"], name="fk_wf_task_member"),
        sa.CheckConstraint("title_key IN ('REVIEW_DOCUMENTS', 'REVIEW_RESPONSES', 'PREPARE_REPORT')", name="ck_wf_task_title"),
        sa.CheckConstraint("status IN ('ASSIGNED', 'DONE')", name="ck_wf_task_status"), schema="wf")
    op.create_index("ix_wf_task_committee", "task", ["committee_id"], schema="wf")
    op.create_table("observation",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("committee_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("author_user_ref", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("body_note_ref", pg.UUID(as_uuid=True), nullable=False), sa.Column("body_note_hash", sa.Text, nullable=False),
        sa.ForeignKeyConstraint(["task_id", "committee_id"], ["wf.task.id", "wf.task.committee_id"], name="fk_wf_observation_task"),
        sa.ForeignKeyConstraint(["committee_id", "author_user_ref"],
            ["wf.committee_member.committee_id", "wf.committee_member.user_ref"], name="fk_wf_observation_member"),
        sa.CheckConstraint("body_note_hash ~ '^[0-9a-f]{64}$'", name="ck_wf_observation_hash"), schema="wf")
    op.create_index("ix_wf_observation_task", "observation", ["task_id"], schema="wf")
    op.create_table("report_version",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("committee_id", pg.UUID(as_uuid=True), sa.ForeignKey("wf.committee.id"), nullable=False),
        sa.Column("version_no", sa.Integer, nullable=False), sa.Column("content_note_ref", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("content_note_hash", sa.Text, nullable=False), sa.Column("author_user_ref", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("parent_version", pg.UUID(as_uuid=True)),
        sa.UniqueConstraint("committee_id", "version_no", name="uq_wf_report_committee_version"),
        sa.UniqueConstraint("id", "committee_id", name="uq_wf_report_id_committee"),
        sa.ForeignKeyConstraint(["committee_id", "author_user_ref"],
            ["wf.committee_member.committee_id", "wf.committee_member.user_ref"], name="fk_wf_report_member"),
        sa.ForeignKeyConstraint(["parent_version", "committee_id"],
            ["wf.report_version.id", "wf.report_version.committee_id"], name="fk_wf_report_parent"),
        sa.CheckConstraint("version_no >= 1", name="ck_wf_report_version"),
        sa.CheckConstraint("content_note_hash ~ '^[0-9a-f]{64}$'", name="ck_wf_report_hash"), schema="wf")
    op.execute("""
        CREATE FUNCTION wf.reject_report_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'REPORT_APPEND_ONLY' USING ERRCODE = '55000';
        END $$
    """)
    op.execute("""CREATE TRIGGER report_append_only BEFORE UPDATE OR DELETE ON wf.report_version
                  FOR EACH ROW EXECUTE FUNCTION wf.reject_report_mutation()""")
    op.execute("""
        CREATE FUNCTION wf.check_report_chain() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE latest_id uuid; latest_no integer;
        BEGIN
            PERFORM id FROM wf.committee WHERE id = NEW.committee_id FOR UPDATE;
            SELECT id, version_no INTO latest_id, latest_no FROM wf.report_version
                WHERE committee_id = NEW.committee_id ORDER BY version_no DESC LIMIT 1;
            IF NEW.version_no != COALESCE(latest_no, 0) + 1 OR NEW.parent_version IS DISTINCT FROM latest_id THEN
                RAISE EXCEPTION 'REPORT_PARENT_OR_VERSION_CONFLICT' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""CREATE TRIGGER report_chain BEFORE INSERT ON wf.report_version
                  FOR EACH ROW EXECUTE FUNCTION wf.check_report_chain()""")


def downgrade() -> None:
    op.drop_table("report_version", schema="wf")
    op.execute("DROP FUNCTION wf.check_report_chain()")
    op.execute("DROP FUNCTION wf.reject_report_mutation()")
    op.drop_table("observation", schema="wf")
    op.drop_table("task", schema="wf")
    op.drop_table("committee_member", schema="wf")
    op.drop_table("committee", schema="wf")
