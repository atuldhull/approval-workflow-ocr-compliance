import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.db import Base

SCHEMA = "dl"


class Deadline(Base):
    __tablename__ = "deadline"
    __table_args__ = (
        # at most one live clock per (subject, rule)
        Index("uq_deadline_live", "subject_type", "subject_id", "rule_id", unique=True,
              postgresql_where=text("status IN ('RUNNING', 'PAUSED')")),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subject_type: Mapped[str] = mapped_column(Text)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    rule_id: Mapped[str] = mapped_column(Text)
    ruleset: Mapped[str] = mapped_column(Text)
    revision: Mapped[str] = mapped_column(Text)
    clause: Mapped[str | None] = mapped_column(Text)
    source_status: Mapped[str] = mapped_column(Text)
    anchor_event_seq: Mapped[int | None] = mapped_column(Integer)
    anchor_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    anchor_date: Mapped[date | None] = mapped_column(Date)
    duration_value: Mapped[int | None] = mapped_column(Integer)
    duration_unit: Mapped[str | None] = mapped_column(Text)
    clock_kind: Mapped[str] = mapped_column(Text)
    calendar_id: Mapped[str | None] = mapped_column(Text)
    clock_owner: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    due_date: Mapped[date] = mapped_column(Date)
    due_version: Mapped[int] = mapped_column(Integer, default=1)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_fire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    explanation: Mapped[str] = mapped_column(Text)
