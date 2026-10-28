"""workflow: the appeal against an LoD (APH cl. 1.11 / 2.24) and the SAC committee type."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "wf_0007"
down_revision = "wf_0006"
branch_labels = None  # inherits the workflow chain label
depends_on = None

STATUSES = "'WINDOW_OPEN', 'FILED', 'RECOMMENDED', 'NOT_RECOMMENDED', 'REFERRED_BACK', 'LAPSED', 'DECIDED'"


def upgrade() -> None:
    op.drop_constraint("ck_wf_committee_type", "committee", type_="check", schema="wf")
    op.create_check_constraint("ck_wf_committee_type", "committee",
                               "type IN ('SCRUTINY', 'RESCRUTINY', 'EVC', 'SHC', 'EC', 'COUNCIL', 'SAC')", schema="wf")
    op.create_table("appeal",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("application_id", pg.UUID(as_uuid=True), sa.ForeignKey("wf.case_state.application_id"), nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("lod_letter_ref", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("window_rule_id", sa.Text, nullable=False),
        sa.Column("window_deadline_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("filed_at", sa.DateTime(timezone=True)), sa.Column("filed_by", pg.UUID(as_uuid=True)),
        sa.Column("grounds_note_ref", pg.UUID(as_uuid=True)), sa.Column("grounds_note_hash", sa.Text),
        sa.Column("hearing_no", sa.Integer, nullable=False),
        sa.Column("recommendation", sa.Text), sa.Column("recommended_at", sa.DateTime(timezone=True)),
        sa.Column("recommended_by", pg.UUID(as_uuid=True)), sa.Column("recommendation_report_ref", pg.UUID(as_uuid=True)),
        sa.Column("outcome", sa.Text), sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("decided_by", pg.UUID(as_uuid=True)), sa.Column("decision_letter_ref", pg.UUID(as_uuid=True)),
        sa.Column("speaking_order_note_ref", pg.UUID(as_uuid=True)), sa.Column("speaking_order_note_hash", sa.Text),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("application_id", name="uq_wf_appeal_case"),
        sa.CheckConstraint(f"status IN ({STATUSES})", name="ck_wf_appeal_status"),
        sa.CheckConstraint("recommendation IS NULL OR recommendation IN ('RECOMMEND', 'NOT_RECOMMEND', 'REFER_SCRUTINY', "
                           "'REFER_EVC')", name="ck_wf_appeal_recommendation"),
        sa.CheckConstraint("outcome IS NULL OR outcome IN ('LOA', 'EOA', 'LOR')", name="ck_wf_appeal_outcome"),
        sa.CheckConstraint("(status = 'DECIDED') = (outcome IS NOT NULL)", name="ck_wf_appeal_decided"),
        sa.CheckConstraint("outcome IS DISTINCT FROM 'LOR' OR speaking_order_note_hash IS NOT NULL",
                           name="ck_wf_appeal_speaking_order"),
        sa.CheckConstraint("hearing_no >= 0", name="ck_wf_appeal_hearing"), schema="wf")


def downgrade() -> None:
    op.drop_table("appeal", schema="wf")
    op.drop_constraint("ck_wf_committee_type", "committee", type_="check", schema="wf")
    op.create_check_constraint("ck_wf_committee_type", "committee",
                               "type IN ('SCRUTINY', 'RESCRUTINY', 'EVC', 'SHC', 'EC', 'COUNCIL')", schema="wf")
