"""compliance: approval letters, obligations and evidence

Revision ID: cmp_0001
Revises:
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "cmp_0001"
down_revision = None
branch_labels = ("compliance",)
depends_on = ("wf_0001", "doc_0002")

UUID = pg.UUID(as_uuid=True)
REJECTION_REASONS = ("'DOCUMENT_ILLEGIBLE', 'DOCUMENT_INCOMPLETE', 'WRONG_DOCUMENT', 'AMOUNT_MISMATCH', "
                     "'DATE_MISMATCH', 'DOCUMENT_EXPIRED', 'SIGNATURE_OR_ATTESTATION_MISSING', 'OTHER_SEE_NOTE'")


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS cmp")
    op.create_table(
        "approval_letter",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("application_id", UUID, sa.ForeignKey("wf.application.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("institution_id", UUID, sa.ForeignKey("wf.institution.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("region", sa.Text, nullable=False),
        sa.Column("letter_type", sa.Text, nullable=False),
        sa.Column("academic_year", sa.Text, nullable=False),
        sa.Column("issue_date", sa.Date, nullable=False),
        sa.Column("issue_date_source", sa.Text, nullable=False),
        sa.Column("issue_date_fact_id", UUID, sa.ForeignKey("doc.fact.fact_id", ondelete="RESTRICT")),
        sa.Column("document_version_id", UUID,
                  sa.ForeignKey("doc.document_version.document_version_id", ondelete="RESTRICT")),
        sa.Column("f_no", sa.Text),
        sa.Column("lists_deficiencies", sa.Boolean, nullable=False),
        sa.Column("deficiencies_confirmed_by", UUID),
        sa.Column("validity_deadline_id", UUID),
        sa.Column("valid_until", sa.Date),
        sa.Column("ruleset_rev", sa.Text, nullable=False),
        sa.Column("registered_by", UUID, nullable=False),
        sa.Column("registered_role", sa.Text, nullable=False),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("letter_type IN ('LOA', 'EOA', 'LOD', 'LOR', 'CORRIGENDUM')", name="ck_cmp_letter_type"),
        sa.CheckConstraint("issue_date_source IN ('PORTAL_EVENT', 'CONFIRMED_FACT')",
                           name="ck_cmp_letter_issue_date_source"),
        sa.CheckConstraint("academic_year ~ '^[0-9]{4}-[0-9]{2}$'", name="ck_cmp_letter_academic_year"),
        sa.CheckConstraint(
            "(issue_date_source = 'CONFIRMED_FACT' AND issue_date_fact_id IS NOT NULL) OR "
            "(issue_date_source = 'PORTAL_EVENT' AND issue_date_fact_id IS NULL "
            "AND f_no IS NOT NULL AND length(btrim(f_no)) > 0)",
            name="ck_cmp_letter_provenance",
        ),
        sa.CheckConstraint("NOT lists_deficiencies OR deficiencies_confirmed_by IS NOT NULL",
                           name="ck_cmp_letter_deficiencies_confirmed"),
        sa.CheckConstraint("(validity_deadline_id IS NULL) = (valid_until IS NULL)", name="ck_cmp_letter_validity"),
        schema="cmp",
    )
    op.create_index("uq_cmp_letter_one_approval_per_year", "approval_letter",
                    ["application_id", "letter_type", "academic_year"], unique=True, schema="cmp",
                    postgresql_where=sa.text("letter_type IN ('LOA', 'EOA')"))
    op.create_index("ix_cmp_letter_application", "approval_letter", ["application_id", "issue_date"], schema="cmp")
    op.create_index("ix_cmp_letter_region", "approval_letter", ["region"], schema="cmp")

    op.create_table(
        "obligation",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("application_id", UUID, sa.ForeignKey("wf.application.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("institution_id", UUID, sa.ForeignKey("wf.institution.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("region", sa.Text, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("source_letter_id", UUID, sa.ForeignKey("cmp.approval_letter.id", ondelete="RESTRICT")),
        sa.Column("source_clause", sa.Text),
        sa.Column("source_status", sa.Text, nullable=False),
        sa.Column("state_origin", sa.Text, nullable=False),
        sa.Column("rule_id", sa.Text),
        sa.Column("deadline_id", UUID),
        sa.Column("due_date", sa.Date),
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'OPEN'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("met_evidence_id", UUID),
        sa.Column("met_by", UUID),
        sa.Column("met_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("kind IN ('UNDERTAKING', 'AFFIDAVIT', 'LETTER_CONDITION', 'DEPOSIT', "
                           "'DOCUMENT_VALIDITY', 'RECURRING_FILING')", name="ck_cmp_obligation_kind"),
        sa.CheckConstraint("source_status IN ('verified', 'verified_letter_text', 'demo_assumption')",
                           name="ck_cmp_obligation_source_status"),
        sa.CheckConstraint("state_origin IN ('OFFICER_CONFIRMED', 'RULE_DEFAULT')",
                           name="ck_cmp_obligation_state_origin"),
        sa.CheckConstraint("status IN ('OPEN', 'EVIDENCE_SUBMITTED', 'MET')", name="ck_cmp_obligation_status"),
        sa.CheckConstraint("source_letter_id IS NOT NULL OR source_clause IS NOT NULL",
                           name="ck_cmp_obligation_source"),
        sa.CheckConstraint("(deadline_id IS NULL) = (due_date IS NULL)", name="ck_cmp_obligation_due_from_deadline"),
        sa.CheckConstraint(
            "(status = 'MET') = (met_evidence_id IS NOT NULL AND met_at IS NOT NULL AND met_by IS NOT NULL)",
            name="ck_cmp_obligation_met",
        ),
        schema="cmp",
    )
    op.create_index("uq_cmp_obligation_letter_kind", "obligation", ["source_letter_id", "kind"], unique=True,
                    schema="cmp", postgresql_where=sa.text("source_letter_id IS NOT NULL"))
    op.create_index("ix_cmp_obligation_application", "obligation", ["application_id", "created_at"], schema="cmp")
    op.create_index("ix_cmp_obligation_region_status", "obligation", ["region", "status"], schema="cmp")

    op.create_table(
        "evidence",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("obligation_id", UUID, sa.ForeignKey("cmp.obligation.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("application_id", UUID, nullable=False),
        sa.Column("institution_id", UUID, nullable=False),
        sa.Column("document_version_id", UUID,
                  sa.ForeignKey("doc.document_version.document_version_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'SUBMITTED'")),
        sa.Column("submitted_by", UUID, nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_by", UUID),
        sa.Column("verified_role", sa.Text),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("reason_code", sa.Text),
        sa.Column("note_ref", UUID),
        sa.Column("note_hash", sa.Text),
        sa.CheckConstraint("status IN ('SUBMITTED', 'ACCEPTED', 'REJECTED')", name="ck_cmp_evidence_status"),
        sa.CheckConstraint(
            "(status = 'SUBMITTED' AND verified_by IS NULL AND verified_role IS NULL AND verified_at IS NULL "
            "AND reason_code IS NULL AND note_ref IS NULL AND note_hash IS NULL) OR "
            "(status = 'ACCEPTED' AND verified_by IS NOT NULL AND verified_role IS NOT NULL "
            "AND verified_at IS NOT NULL AND reason_code IS NULL) OR "
            "(status = 'REJECTED' AND verified_by IS NOT NULL AND verified_role IS NOT NULL "
            "AND verified_at IS NOT NULL AND reason_code IS NOT NULL)",
            name="ck_cmp_evidence_decision",
        ),
        sa.CheckConstraint(f"reason_code IS NULL OR reason_code IN ({REJECTION_REASONS})",
                           name="ck_cmp_evidence_reason_code"),
        sa.CheckConstraint("reason_code IS DISTINCT FROM 'OTHER_SEE_NOTE' OR note_ref IS NOT NULL",
                           name="ck_cmp_evidence_other_needs_note"),
        sa.CheckConstraint("verified_role IS NULL OR verified_role <> 'SYSTEM'",
                           name="ck_cmp_evidence_human_verifier"),
        sa.CheckConstraint("(note_ref IS NULL) = (note_hash IS NULL)", name="ck_cmp_evidence_note_pair"),
        schema="cmp",
    )
    op.create_index("uq_cmp_evidence_one_pending", "evidence", ["obligation_id"], unique=True, schema="cmp",
                    postgresql_where=sa.text("status = 'SUBMITTED'"))
    op.create_index("uq_cmp_evidence_obligation_version", "evidence", ["obligation_id", "document_version_id"],
                    unique=True, schema="cmp")


def downgrade() -> None:
    op.execute("DROP SCHEMA cmp CASCADE")
