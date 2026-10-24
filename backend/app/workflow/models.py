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
