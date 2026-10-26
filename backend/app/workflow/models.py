"""P1-owned state-machine persistence. All foreign keys remain inside wf."""
from datetime import datetime
from uuid import UUID as UUIDValue

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.db import Base

SCHEMA = "wf"
RULESET_STATUSES = "'DRAFT', 'VALIDATED', 'APPROVED', 'ACTIVE', 'RETIRED'"
CASE_STATUSES = "'DRAFT', 'IN_PROCESS', 'APPROVED', 'REJECTED', 'WITHDRAWN'"


class Ruleset(Base):
    __tablename__ = "ruleset"
    __table_args__ = (
        UniqueConstraint("key", name="uq_wf_ruleset_key"),
        UniqueConstraint("id", "key", name="uq_wf_ruleset_id_key"),
        CheckConstraint(f"status IN ({RULESET_STATUSES})", name="ck_wf_ruleset_status"),
        CheckConstraint("checksum ~ '^[0-9a-f]{64}$'", name="ck_wf_ruleset_checksum"),
        CheckConstraint("(approved_at IS NULL) = (approved_by_ref IS NULL)", name="ck_wf_ruleset_approval_metadata"),
        {"schema": SCHEMA},
    )

    id: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True), primary_key=True)
    key: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    checksum: Mapped[str] = mapped_column(Text)
    demo_only: Mapped[bool] = mapped_column(Boolean)
    source_status: Mapped[str] = mapped_column(Text)
    source_files: Mapped[list] = mapped_column(JSONB)
    source_metadata: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by_ref: Mapped[UUIDValue | None] = mapped_column(UUID(as_uuid=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by_ref: Mapped[UUIDValue | None] = mapped_column(UUID(as_uuid=True))


class RouteDefinition(Base):
    __tablename__ = "route_def"
    __table_args__ = (
        ForeignKeyConstraint(["ruleset_id", "ruleset_key"], ["wf.ruleset.id", "wf.ruleset.key"], name="fk_wf_route_ruleset"),
        UniqueConstraint("ruleset_key", "route_id", name="uq_wf_route_key_id"),
        Index("ix_wf_route_ruleset_id", "ruleset_id"),
        {"schema": SCHEMA},
    )

    id: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True), primary_key=True)
    ruleset_id: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True))
    ruleset_key: Mapped[str] = mapped_column(Text)
    route_id: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(Text)
    stage_list: Mapped[list] = mapped_column(JSONB)
    clause_citation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class TransitionDefinition(Base):
    __tablename__ = "transition"
    __table_args__ = (
        UniqueConstraint("route_def_id", "position", name="uq_wf_transition_position"),
        Index("ix_wf_transition_route_action", "route_def_id", "action"),
        {"schema": SCHEMA},
    )

    id: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True), primary_key=True)
    route_def_id: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True), ForeignKey("wf.route_def.id"))
    position: Mapped[int] = mapped_column(Integer)
    template_id: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    from_stage: Mapped[str] = mapped_column(Text)
    to_stage: Mapped[str] = mapped_column(Text)
    roles: Mapped[list] = mapped_column(JSONB)
    guards: Mapped[list] = mapped_column(JSONB)
    timers: Mapped[list] = mapped_column(JSONB)
    letter: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    reason_codes_required: Mapped[bool] = mapped_column(Boolean)
    emits_event: Mapped[str] = mapped_column(Text)
    definition: Mapped[dict] = mapped_column(JSONB)


class CaseState(Base):
    __tablename__ = "case_state"
    __table_args__ = (
        ForeignKeyConstraint(["ruleset_key", "route_id"], ["wf.route_def.ruleset_key", "wf.route_def.route_id"], name="fk_wf_case_route"),
        CheckConstraint(f"status IN ({CASE_STATUSES})", name="ck_wf_case_status"),
        CheckConstraint("version >= 1", name="ck_wf_case_version"),
        Index("ix_wf_case_ruleset_route", "ruleset_key", "route_id"),
        {"schema": SCHEMA},
    )

    application_id: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True), ForeignKey("wf.application.id"), primary_key=True)
    route_id: Mapped[str] = mapped_column(Text)
    ruleset_key: Mapped[str] = mapped_column(Text)
    current_stage: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))

    __mapper_args__ = {"version_id_col": version}


class Deficiency(Base):
    __tablename__ = "deficiency"
    __table_args__ = (
        UniqueConstraint("application_id", "round_no", name="uq_wf_deficiency_round"),
        CheckConstraint("round_no >= 1", name="ck_wf_deficiency_round"),
        CheckConstraint("status IN ('OPEN', 'RESPONDED', 'CLOSED')", name="ck_wf_deficiency_status"),
        CheckConstraint("(status = 'CLOSED') = (closed_at IS NOT NULL)", name="ck_wf_deficiency_closed"),
        CheckConstraint("(status = 'CLOSED') = (closure_kind IS NOT NULL)", name="ck_wf_deficiency_closure_kind"),
        CheckConstraint("closure_kind IS NULL OR closure_kind IN ('ACCEPTED', 'SUPERSEDED')", name="ck_wf_deficiency_closure_value"),
        Index("ix_wf_deficiency_case", "application_id"),
        Index("uq_wf_deficiency_active", "application_id", unique=True,
              postgresql_where=text("status != 'CLOSED'")),
        {"schema": SCHEMA},
    )
    id: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True), primary_key=True)
    application_id: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True), ForeignKey("wf.case_state.application_id"))
    round_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closure_kind: Mapped[str | None] = mapped_column(Text)


class DeficiencyItem(Base):
    __tablename__ = "deficiency_item"
    __table_args__ = (
        UniqueConstraint("deficiency_id", "item_key", name="uq_wf_deficiency_item_key"),
        CheckConstraint("item_key ~ '^[A-Z][A-Z0-9_]*$'", name="ck_wf_deficiency_item_key"),
        CheckConstraint("state IN ('OPEN', 'RESPONDED', 'ACCEPTED', 'REJECTED')", name="ck_wf_deficiency_item_state"),
        CheckConstraint("(state = 'OPEN') = (response_ref IS NULL)", name="ck_wf_deficiency_item_response"),
        CheckConstraint("(state IN ('ACCEPTED', 'REJECTED')) = (decided_by IS NOT NULL AND decision_reason_code IS NOT NULL)",
                        name="ck_wf_deficiency_item_decision"),
        Index("ix_wf_deficiency_item_round", "deficiency_id"),
        {"schema": SCHEMA},
    )
    id: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True), primary_key=True)
    deficiency_id: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True), ForeignKey("wf.deficiency.id"))
    item_key: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(Text)
    response_ref: Mapped[UUIDValue | None] = mapped_column(UUID(as_uuid=True))
    decided_by: Mapped[UUIDValue | None] = mapped_column(UUID(as_uuid=True))
    decision_reason_code: Mapped[str | None] = mapped_column(Text)
    previous_item_id: Mapped[UUIDValue | None] = mapped_column(UUID(as_uuid=True),
        ForeignKey("wf.deficiency_item.id", name="fk_wf_deficiency_item_previous"))


class Committee(Base):
    __tablename__ = "committee"
    __table_args__ = (
        CheckConstraint("type IN ('SCRUTINY', 'RESCRUTINY', 'EVC', 'SHC', 'EC', 'COUNCIL')", name="ck_wf_committee_type"),
        CheckConstraint("status IN ('ACTIVE', 'CLOSED')", name="ck_wf_committee_status"),
        Index("ix_wf_committee_case", "application_id"),
        {"schema": SCHEMA},
    )
    id: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True), primary_key=True)
    application_id: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True), ForeignKey("wf.application.id"))
    type: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)


class CommitteeMember(Base):
    __tablename__ = "committee_member"
    __table_args__ = (
        CheckConstraint("role IN ('CHAIR', 'MEMBER', 'SECRETARY')", name="ck_wf_committee_member_role"),
        {"schema": SCHEMA},
    )
    committee_id: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True), ForeignKey("wf.committee.id"), primary_key=True)
    user_ref: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True), primary_key=True)
    role: Mapped[str] = mapped_column(Text)


class CommitteeTask(Base):
    __tablename__ = "task"
    __table_args__ = (
        UniqueConstraint("id", "committee_id", name="uq_wf_task_id_committee"),
        ForeignKeyConstraint(["committee_id", "assignee_user_ref"],
            ["wf.committee_member.committee_id", "wf.committee_member.user_ref"], name="fk_wf_task_member"),
        CheckConstraint("title_key IN ('REVIEW_DOCUMENTS', 'REVIEW_RESPONSES', 'PREPARE_REPORT')", name="ck_wf_task_title"),
        CheckConstraint("status IN ('ASSIGNED', 'DONE')", name="ck_wf_task_status"),
        Index("ix_wf_task_committee", "committee_id"),
        {"schema": SCHEMA},
    )
    id: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True), primary_key=True)
    committee_id: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True), ForeignKey("wf.committee.id"))
    title_key: Mapped[str] = mapped_column(Text)
    assignee_user_ref: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(Text)


class Observation(Base):
    __tablename__ = "observation"
    __table_args__ = (
        ForeignKeyConstraint(["task_id", "committee_id"], ["wf.task.id", "wf.task.committee_id"], name="fk_wf_observation_task"),
        ForeignKeyConstraint(["committee_id", "author_user_ref"],
            ["wf.committee_member.committee_id", "wf.committee_member.user_ref"], name="fk_wf_observation_member"),
        CheckConstraint("body_note_hash ~ '^[0-9a-f]{64}$'", name="ck_wf_observation_hash"),
        Index("ix_wf_observation_task", "task_id"),
        {"schema": SCHEMA},
    )
    id: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True), primary_key=True)
    committee_id: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True))
    task_id: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True))
    author_user_ref: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True))
    body_note_ref: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True))
    body_note_hash: Mapped[str] = mapped_column(Text)


class ReportVersion(Base):
    __tablename__ = "report_version"
    __table_args__ = (
        UniqueConstraint("committee_id", "version_no", name="uq_wf_report_committee_version"),
        UniqueConstraint("id", "committee_id", name="uq_wf_report_id_committee"),
        ForeignKeyConstraint(["committee_id", "author_user_ref"],
            ["wf.committee_member.committee_id", "wf.committee_member.user_ref"], name="fk_wf_report_member"),
        ForeignKeyConstraint(["parent_version", "committee_id"],
            ["wf.report_version.id", "wf.report_version.committee_id"], name="fk_wf_report_parent"),
        CheckConstraint("version_no >= 1", name="ck_wf_report_version"),
        CheckConstraint("content_note_hash ~ '^[0-9a-f]{64}$'", name="ck_wf_report_hash"),
        {"schema": SCHEMA},
    )
    id: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True), primary_key=True)
    committee_id: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True), ForeignKey("wf.committee.id"))
    version_no: Mapped[int] = mapped_column(Integer)
    content_note_ref: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True))
    content_note_hash: Mapped[str] = mapped_column(Text)
    author_user_ref: Mapped[UUIDValue] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    parent_version: Mapped[UUIDValue | None] = mapped_column(UUID(as_uuid=True))
