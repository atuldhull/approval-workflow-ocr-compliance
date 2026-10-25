import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, SmallInteger, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.db import Base

SCHEMA = "dl"
_CALENDAR_TRIM_CHARS = "' ' || chr(9) || chr(10) || chr(11) || chr(12) || chr(13)"
_CALENDAR_ID_CHECK = (
    "length(calendar_id) - length(replace(calendar_id, '@', '')) = 1 "
    f"AND btrim(split_part(calendar_id, '@', 1), {_CALENDAR_TRIM_CHARS}) <> '' "
    f"AND btrim(split_part(calendar_id, '@', 2), {_CALENDAR_TRIM_CHARS}) <> ''"
)
_VERIFIED_SOURCE_REF_CHECK = (
    "source_status <> 'verified' OR "
    f"(source_ref IS NOT NULL AND btrim(source_ref, {_CALENDAR_TRIM_CHARS}) <> '')"
)


class Deadline(Base):
    __tablename__ = "deadline"
    __table_args__ = (
        # at most one live clock per (subject, rule)
        Index("uq_deadline_live", "subject_type", "subject_id", "rule_id", unique=True,
              postgresql_where=text("status IN ('RUNNING', 'PAUSED')")),
        CheckConstraint(
            "duration_unit != 'working_days' OR (calendar_id IS NOT NULL AND count_anchor_day IS NOT NULL)",
            name="ck_dl_deadline_working_days_calendar",
        ),
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
    calendar_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("dl.calendar_version.calendar_id", ondelete="RESTRICT")
    )
    count_anchor_day: Mapped[bool | None] = mapped_column(nullable=True)
    clock_owner: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    due_date: Mapped[date] = mapped_column(Date)
    due_version: Mapped[int] = mapped_column(Integer, default=1)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_fire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    explanation: Mapped[str] = mapped_column(Text)


class CalendarVersion(Base):
    """One explicitly sourced, finalized set of working weekdays."""

    __tablename__ = "calendar_version"
    __table_args__ = (
        CheckConstraint("cardinality(working_weekdays) > 0", name="ck_dl_calendar_weekdays_not_empty"),
        CheckConstraint(
            "working_weekdays <@ ARRAY[0,1,2,3,4,5,6]::smallint[]",
            name="ck_dl_calendar_weekdays_range",
        ),
        CheckConstraint(_CALENDAR_ID_CHECK, name="ck_dl_calendar_id_exactly_one_version_separator"),
        CheckConstraint("source_status IN ('verified', 'demo_assumption')", name="ck_dl_calendar_source_status"),
        CheckConstraint(_VERIFIED_SOURCE_REF_CHECK, name="ck_dl_calendar_verified_source_ref"),
        {"schema": SCHEMA},
    )

    # The key includes its version, e.g. ``RO-SOUTH@2026-27-r1``.
    calendar_id: Mapped[str] = mapped_column(Text, primary_key=True)
    working_weekdays: Mapped[list[int]] = mapped_column(ARRAY(SmallInteger), nullable=False)
    source_status: Mapped[str] = mapped_column(Text, nullable=False)
    source_ref: Mapped[str | None] = mapped_column(Text)
    is_finalized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))


class CalendarHoliday(Base):
    __tablename__ = "holiday"
    __table_args__ = ({"schema": SCHEMA},)

    calendar_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("dl.calendar_version.calendar_id", ondelete="RESTRICT", name="fk_dl_holiday_calendar_id_calendar_version"),
        primary_key=True,
    )
    holiday_date: Mapped[date] = mapped_column(Date, primary_key=True)
    label: Mapped[str | None] = mapped_column(Text)
    source_ref: Mapped[str | None] = mapped_column(Text)
