import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

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


class StageVisit(Base):
    __tablename__ = "stage_visit"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.application.id"), index=True)
    stage: Mapped[str] = mapped_column(Text)
    entered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
