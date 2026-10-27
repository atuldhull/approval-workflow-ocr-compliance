import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, synonym

from app.platform.db import Base

SCHEMA = "wf"


class Institution(Base):
    __tablename__ = "institution"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text)
    ro_region: Mapped[str] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)


class Application(Base):
    __tablename__ = "application"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.institution.id"), index=True)
    category: Mapped[str] = mapped_column(Text)
    academic_year: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    current_stage: Mapped[str | None] = mapped_column(Text)
    ruleset_rev: Mapped[str | None] = mapped_column(Text)  # pinned at submission, never changes afterwards
    route: Mapped[list | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dsc_present: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))


class ApplicationItem(Base):
    __tablename__ = "application_item"
    __table_args__ = (
        CheckConstraint("state IN ('PROVIDED', 'MISSING')", name="ck_wf_application_item_state"),
        CheckConstraint("item_key ~ '^[A-Z][A-Z0-9_]*$'", name="ck_wf_application_item_key"),
        CheckConstraint("(state = 'PROVIDED') = (document_ref IS NOT NULL)", name="ck_wf_application_item_document"),
        {"schema": SCHEMA},
    )
    application_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("wf.application.id"), primary_key=True)
    item_key: Mapped[str] = mapped_column(Text, primary_key=True)
    state: Mapped[str] = mapped_column(Text)
    document_ref: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class StageVisit(Base):
    __tablename__ = "stage_visit"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.application.id"), index=True)
    stage: Mapped[str] = mapped_column(Text)
    entered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    exited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    left_at = synonym("exited_at")  # compatibility with the original intake mapping
    outcome: Mapped[str | None] = mapped_column(Text)
    reason_code: Mapped[str | None] = mapped_column(Text)
    note_ref: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    def record_exit(self, *, outcome: str, reason_code: str | None = None, note_ref: uuid.UUID | None = None) -> None:
        """Aggregate helper; caller must authorize and append its command event."""
        from app.platform.registry import port
        from contracts.errors import Conflict
        from contracts.ports import ClockPort

        if self.exited_at is not None:
            raise Conflict("stage visit already exited")
        self.exited_at = port(ClockPort).now()
        self.outcome = outcome
        self.reason_code = reason_code
        self.note_ref = note_ref
