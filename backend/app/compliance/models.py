"""Approval letters, the obligations they create, and the evidence submitted against them (schema cmp)."""
import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.compliance.vocab import RejectionReason
from app.platform.db import Base

SCHEMA = "cmp"


def _in(column: str, values) -> str:
    return f"{column} IN ({', '.join(repr(str(v)) for v in values)})"


LETTER_TYPES = ("LOA", "EOA", "LOD", "LOR", "CORRIGENDUM")
ISSUE_DATE_SOURCES = ("PORTAL_EVENT", "CONFIRMED_FACT")
OBLIGATION_KINDS = ("UNDERTAKING", "AFFIDAVIT", "LETTER_CONDITION", "DEPOSIT", "DOCUMENT_VALIDITY", "RECURRING_FILING")
SOURCE_STATUSES = ("verified", "verified_letter_text", "demo_assumption")
STATE_ORIGINS = ("OFFICER_CONFIRMED", "RULE_DEFAULT")
OBLIGATION_STATUSES = ("OPEN", "EVIDENCE_SUBMITTED", "MET")
EVIDENCE_STATUSES = ("SUBMITTED", "ACCEPTED", "REJECTED")


class ApprovalLetter(Base):
    """An issued LoA/EoA (or related letter) with the provenance of its issue date."""

    __tablename__ = "approval_letter"
    __table_args__ = (
        CheckConstraint(_in("letter_type", LETTER_TYPES), name="ck_cmp_letter_type"),
        CheckConstraint(_in("issue_date_source", ISSUE_DATE_SOURCES), name="ck_cmp_letter_issue_date_source"),
        CheckConstraint("academic_year ~ '^[0-9]{4}-[0-9]{2}$'", name="ck_cmp_letter_academic_year"),
        # a confirmed-fact date must name its fact; a portal date must carry the letter number instead
        CheckConstraint(
            "(issue_date_source = 'CONFIRMED_FACT' AND issue_date_fact_id IS NOT NULL) OR "
            "(issue_date_source = 'PORTAL_EVENT' AND issue_date_fact_id IS NULL "
            "AND f_no IS NOT NULL AND length(btrim(f_no)) > 0)",
            name="ck_cmp_letter_provenance",
        ),
        CheckConstraint("NOT lists_deficiencies OR deficiencies_confirmed_by IS NOT NULL",
                        name="ck_cmp_letter_deficiencies_confirmed"),
        CheckConstraint("(validity_deadline_id IS NULL) = (valid_until IS NULL)", name="ck_cmp_letter_validity"),
        # one LoA and one EoA per application and academic year; corrigenda and others may repeat
        Index("uq_cmp_letter_one_approval_per_year", "application_id", "letter_type", "academic_year", unique=True,
              postgresql_where=text("letter_type IN ('LOA', 'EOA')")),
        Index("ix_cmp_letter_application", "application_id", "issue_date"),
        Index("ix_cmp_letter_region", "region"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wf.application.id", ondelete="RESTRICT"), nullable=False)
    institution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wf.institution.id", ondelete="RESTRICT"), nullable=False)
    region: Mapped[str] = mapped_column(Text, nullable=False)
    letter_type: Mapped[str] = mapped_column(Text, nullable=False)
    academic_year: Mapped[str] = mapped_column(Text, nullable=False)
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    issue_date_source: Mapped[str] = mapped_column(Text, nullable=False)
    issue_date_fact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doc.fact.fact_id", ondelete="RESTRICT"))
    document_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doc.document_version.document_version_id", ondelete="RESTRICT"))
    # LetterIn.f_no; the handbook letters print it as "F.No." (the plan's fr_no is the same value)
    f_no: Mapped[str | None] = mapped_column(Text)
    lists_deficiencies: Mapped[bool] = mapped_column(Boolean, nullable=False)
    deficiencies_confirmed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # LoA validity clock (deadlines module) and the date it ends
    validity_deadline_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    valid_until: Mapped[date | None] = mapped_column(Date)
    ruleset_rev: Mapped[str] = mapped_column(Text, nullable=False)
    registered_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    registered_role: Mapped[str] = mapped_column(Text, nullable=False)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Obligation(Base):
    """Something the institution must do, where it comes from, and when it is due."""

    __tablename__ = "obligation"
    __table_args__ = (
        CheckConstraint(_in("kind", OBLIGATION_KINDS), name="ck_cmp_obligation_kind"),
        CheckConstraint(_in("source_status", SOURCE_STATUSES), name="ck_cmp_obligation_source_status"),
        CheckConstraint(_in("state_origin", STATE_ORIGINS), name="ck_cmp_obligation_state_origin"),
        CheckConstraint(_in("status", OBLIGATION_STATUSES), name="ck_cmp_obligation_status"),
        CheckConstraint("source_letter_id IS NOT NULL OR source_clause IS NOT NULL", name="ck_cmp_obligation_source"),
        CheckConstraint("(deadline_id IS NULL) = (due_date IS NULL)", name="ck_cmp_obligation_due_from_deadline"),
        CheckConstraint(
            "(status = 'MET') = (met_evidence_id IS NOT NULL AND met_at IS NOT NULL AND met_by IS NOT NULL)",
            name="ck_cmp_obligation_met",
        ),
        Index("uq_cmp_obligation_letter_kind", "source_letter_id", "kind", unique=True,
              postgresql_where=text("source_letter_id IS NOT NULL")),
        Index("ix_cmp_obligation_application", "application_id", "created_at"),
        Index("ix_cmp_obligation_region_status", "region", "status"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wf.application.id", ondelete="RESTRICT"), nullable=False)
    institution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wf.institution.id", ondelete="RESTRICT"), nullable=False)
    region: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    source_letter_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cmp.approval_letter.id", ondelete="RESTRICT"))
    source_clause: Mapped[str | None] = mapped_column(Text)
    source_status: Mapped[str] = mapped_column(Text, nullable=False)
    state_origin: Mapped[str] = mapped_column(Text, nullable=False)
    rule_id: Mapped[str | None] = mapped_column(Text)
    # the clock lives in the deadlines module; only its id and the due date at opening are kept here
    deadline_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="OPEN", server_default=text("'OPEN'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    met_evidence_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    met_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    met_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Evidence(Base):
    """One immutable document version offered against one obligation, and the human decision on it."""

    __tablename__ = "evidence"
    __table_args__ = (
        CheckConstraint(_in("status", EVIDENCE_STATUSES), name="ck_cmp_evidence_status"),
        CheckConstraint(
            "(status = 'SUBMITTED' AND verified_by IS NULL AND verified_role IS NULL AND verified_at IS NULL "
            "AND reason_code IS NULL AND note_ref IS NULL AND note_hash IS NULL) OR "
            "(status = 'ACCEPTED' AND verified_by IS NOT NULL AND verified_role IS NOT NULL "
            "AND verified_at IS NOT NULL AND reason_code IS NULL) OR "
            "(status = 'REJECTED' AND verified_by IS NOT NULL AND verified_role IS NOT NULL "
            "AND verified_at IS NOT NULL AND reason_code IS NOT NULL)",
            name="ck_cmp_evidence_decision",
        ),
        CheckConstraint("reason_code IS NULL OR " + _in("reason_code", RejectionReason),
                        name="ck_cmp_evidence_reason_code"),
        CheckConstraint("reason_code IS DISTINCT FROM 'OTHER_SEE_NOTE' OR note_ref IS NOT NULL",
                        name="ck_cmp_evidence_other_needs_note"),
        CheckConstraint("verified_role IS NULL OR verified_role <> 'SYSTEM'", name="ck_cmp_evidence_human_verifier"),
        CheckConstraint("(note_ref IS NULL) = (note_hash IS NULL)", name="ck_cmp_evidence_note_pair"),
        # at most one undecided submission per obligation; a version is offered once per obligation
        Index("uq_cmp_evidence_one_pending", "obligation_id", unique=True,
              postgresql_where=text("status = 'SUBMITTED'")),
        Index("uq_cmp_evidence_obligation_version", "obligation_id", "document_version_id", unique=True),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    obligation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cmp.obligation.id", ondelete="RESTRICT"), nullable=False)
    application_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doc.document_version.document_version_id", ondelete="RESTRICT"),
        nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="SUBMITTED", server_default=text("'SUBMITTED'"))
    submitted_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    verified_role: Mapped[str | None] = mapped_column(Text)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason_code: Mapped[str | None] = mapped_column(Text)
    note_ref: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    note_hash: Mapped[str | None] = mapped_column(Text)
