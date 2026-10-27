"""EVC-owned storage. Panel selection/publishing commands are separate work."""
from datetime import date as DateValue, datetime
from uuid import UUID as UUIDValue

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.db import Base

SCHEMA = "evc"


class EvcRequest(Base):
    __tablename__ = "evc_request"
    __table_args__ = (
        CheckConstraint("status IN ('QUEUED','PROPOSED','PUBLISHED','DONE','CANCELLED')", name="ck_evc_request_status"),
        CheckConstraint("earliest_date <= due_by", name="ck_evc_request_window"),
        CheckConstraint("category ~ '^[A-Z][A-Z0-9_]*$'", name="ck_evc_request_category"),
        CheckConstraint("priority_key ~ '^[A-Za-z0-9_:-]+$'", name="ck_evc_request_priority"),
        Index("ix_evc_request_queue", "status", "due_by", "priority_key", "id"),
        Index("ix_evc_request_case", "application_id"),
        UniqueConstraint("stage_visit_ref", name="uq_evc_request_visit"),
        UniqueConstraint("application_id", "entry_no", name="uq_evc_request_entry"),
        CheckConstraint("entry_no IS NULL OR entry_no > 0", name="ck_evc_request_entry"),
        Index("uq_evc_request_active", "application_id", unique=True,
              postgresql_where=text("status IN ('QUEUED', 'PROPOSED', 'PUBLISHED')")),
        {"schema": SCHEMA},
    )
    id: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True), primary_key=True)
    application_id: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True), ForeignKey("wf.application.id"))
    institution_ref: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True), ForeignKey("wf.institution.id"))
    region: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(Text)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    earliest_date: Mapped[DateValue] = mapped_column(Date)
    due_by: Mapped[DateValue] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text)
    priority_key: Mapped[str] = mapped_column(Text)
    stage_visit_ref: Mapped[UUIDValue | None] = mapped_column(UUID(as_uuid=True), ForeignKey("wf.stage_visit.id"))
    ruleset_key: Mapped[str | None] = mapped_column(Text)
    rule_id: Mapped[str | None] = mapped_column(Text)
    deadline_ref: Mapped[UUIDValue | None] = mapped_column(UUID(as_uuid=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    entry_no: Mapped[int | None] = mapped_column(Integer)


class Expert(Base):
    __tablename__ = "expert"
    __table_args__ = (
        UniqueConstraint("user_ref", name="uq_evc_expert_user"),
        CheckConstraint("evc.coded_tags(expertise_tags)", name="ck_evc_expert_tags"),
        {"schema": SCHEMA},
    )
    id: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_ref: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True))
    personal_ref: Mapped[UUIDValue | None] = mapped_column(UUID(as_uuid=True))
    region: Mapped[str] = mapped_column(Text)
    expertise_tags: Mapped[list[str]] = mapped_column(ARRAY(Text))
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class Availability(Base):
    __tablename__ = "availability"
    __table_args__ = (
        CheckConstraint("slot_part ~ '^[A-Z][A-Z0-9_]*$'", name="ck_evc_availability_part"),
        {"schema": SCHEMA},
    )
    expert_id: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True), ForeignKey("evc.expert.id"), primary_key=True)
    date: Mapped[DateValue] = mapped_column(Date, primary_key=True)
    slot_part: Mapped[str] = mapped_column(Text, primary_key=True)
    available: Mapped[bool] = mapped_column(Boolean)


class Coi(Base):
    __tablename__ = "coi"
    __table_args__ = (
        CheckConstraint("reason_code ~ '^[A-Z][A-Z0-9_]*$'", name="ck_evc_coi_reason"),
        CheckConstraint("source ~ '^[A-Z][A-Z0-9_]*$'", name="ck_evc_coi_source"),
        {"schema": SCHEMA},
    )
    expert_id: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True), ForeignKey("evc.expert.id"), primary_key=True)
    institution_ref: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True), ForeignKey("wf.institution.id"), primary_key=True)
    reason_code: Mapped[str] = mapped_column(Text, primary_key=True)
    source: Mapped[str] = mapped_column(Text, primary_key=True)


class Slot(Base):
    __tablename__ = "slot"
    __table_args__ = (
        CheckConstraint("slot_part ~ '^[A-Z][A-Z0-9_]*$'", name="ck_evc_slot_part"),
        CheckConstraint("capacity > 0", name="ck_evc_slot_capacity"),
        {"schema": SCHEMA},
    )
    id: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True), primary_key=True)
    date: Mapped[DateValue] = mapped_column(Date)
    slot_part: Mapped[str] = mapped_column(Text)
    capacity: Mapped[int] = mapped_column(Integer)


class ScheduleRun(Base):
    __tablename__ = "schedule_run"
    __table_args__ = (
        CheckConstraint("algorithm IN ('EDF','CPSAT')", name="ck_evc_run_algorithm"),
        CheckConstraint("status ~ '^[A-Z][A-Z0-9_]*$'", name="ck_evc_run_status"),
        CheckConstraint("jsonb_typeof(parameters) = 'object' AND evc.numeric_json(parameters)", name="ck_evc_run_parameters"),
        CheckConstraint("jsonb_typeof(metrics) = 'object' AND evc.numeric_json(metrics)", name="ck_evc_run_metrics"),
        CheckConstraint("region_scope IS NULL OR (region_scope <> '' AND region_scope = upper(region_scope))", name="ck_evc_run_region_scope"),
        {"schema": SCHEMA},
    )
    run_id: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True), primary_key=True)
    algorithm: Mapped[str] = mapped_column(Text)
    parameters: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text)
    metrics: Mapped[dict] = mapped_column(JSONB)
    # Upper-case region the run was planned for; NULL means every region (and every run made before evc_0004).
    region_scope: Mapped[str | None] = mapped_column(Text)


class ScheduleRunRequest(Base):
    """Every queued request a run considered, in plan order: PROPOSED, or UNSCHEDULED with its explanation code."""

    __tablename__ = "schedule_run_request"
    __table_args__ = (
        CheckConstraint("ordinal >= 0", name="ck_evc_run_request_ordinal"),
        CheckConstraint("(outcome = 'PROPOSED' AND explanation_code IS NULL) OR (outcome = 'UNSCHEDULED' AND explanation_code "
                        "IN ('NO_AVAILABILITY', 'PANEL_INCOMPLETE', 'COI_ONLY', 'CAPACITY_EXHAUSTED', 'EXPERT_DAILY_CAP', "
                        "'NO_FEASIBLE_SLOT'))", name="ck_evc_run_request_outcome"),
        UniqueConstraint("run_id", "ordinal", name="uq_evc_run_request_ordinal"),
        Index("ix_evc_run_request_request", "request_id"),
        {"schema": SCHEMA},
    )
    run_id: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True), ForeignKey("evc.schedule_run.run_id"), primary_key=True)
    request_id: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True), ForeignKey("evc.evc_request.id"), primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(Text)
    explanation_code: Mapped[str | None] = mapped_column(Text)


class Assignment(Base):
    __tablename__ = "assignment"
    __table_args__ = (
        CheckConstraint("panel_role ~ '^[A-Z][A-Z0-9_]*$'", name="ck_evc_assignment_role"),
        Index("ix_evc_assignment_request", "evc_request_id"),
        Index("ix_evc_assignment_slot", "slot_id"),
        {"schema": SCHEMA},
    )
    id: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True), primary_key=True)
    evc_request_id: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True), ForeignKey("evc.evc_request.id"))
    slot_id: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True), ForeignKey("evc.slot.id"))
    expert_ids: Mapped[list[UUIDValue]] = mapped_column(ARRAY(UUID(as_uuid=True)))
    panel_role: Mapped[str] = mapped_column(Text)
    published: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    schedule_run_id: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True), ForeignKey("evc.schedule_run.run_id"))


class AssignmentExpert(Base):
    """DB-maintained projection of expert_ids; no application writes allowed."""

    __tablename__ = "assignment_expert"
    __table_args__ = (
        Index("uq_evc_published_expert_time", "expert_id", "date", "slot_part", unique=True, postgresql_where=text("published")),
        {"schema": SCHEMA},
    )
    assignment_id: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True), ForeignKey("evc.assignment.id", ondelete="CASCADE"), primary_key=True)
    expert_id: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True), ForeignKey("evc.expert.id"), primary_key=True)
    slot_id: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True), ForeignKey("evc.slot.id"))
    date: Mapped[DateValue] = mapped_column(Date)
    slot_part: Mapped[str] = mapped_column(Text)
    published: Mapped[bool] = mapped_column(Boolean)
