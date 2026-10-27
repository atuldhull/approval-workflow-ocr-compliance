import uuid
from datetime import date, datetime

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, SmallInteger,
                        Text, UniqueConstraint, text)
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
        # the timer worker's queue: running clocks with a firing time
        Index("ix_dl_deadline_timer_due", "next_fire_at", postgresql_where=text("status = 'RUNNING'")),
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
    # timer state: the next ladder level to raise for this due_version, and the worker's claim on the row
    alert_level: Mapped[int] = mapped_column(SmallInteger, default=0, server_default=text("0"))
    timer_fence: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    timer_claimed_by: Mapped[str | None] = mapped_column(Text)
    timer_lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timer_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))


ALERT_STATUSES = ("OPEN", "VACANT", "ESCALATED", "ACKNOWLEDGED")
ESCALATION_REASONS = ("VACANCY", "WINDOW_ELAPSED")
TIMER_OUTCOMES = ("SCHEDULED", "ALERTED", "ACKNOWLEDGED", "LADDER_DONE", "NOT_RUNNING", "RETRY", "FAILED")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Alert(Base):
    """One ladder level raised for one deadline due_version. Holds roles and opaque group ids, never contacts."""

    __tablename__ = "alert"
    __table_args__ = (
        UniqueConstraint("deadline_id", "level", "due_version", name="uq_dl_alert_level"),
        CheckConstraint(_in("status", ALERT_STATUSES), name="ck_dl_alert_status"),
        CheckConstraint(f"reason IS NULL OR {_in('reason', ESCALATION_REASONS)}", name="ck_dl_alert_reason"),
        CheckConstraint("level > 0 OR (reason IS NULL AND from_alert_id IS NULL)", name="ck_dl_alert_escalation_link"),
        Index("ix_dl_alert_region", "region"),
        Index("ix_dl_alert_institution_id", "institution_id"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    deadline_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dl.deadline.id", ondelete="RESTRICT", name="fk_dl_alert_deadline_id_deadline"))
    level: Mapped[int] = mapped_column(SmallInteger)
    due_version: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(Text)
    recipient_ref: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))  # opaque role-group id
    subject_type: Mapped[str] = mapped_column(Text)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    institution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    region: Mapped[str | None] = mapped_column(Text)
    template: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    from_alert_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    raised_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class TimerOutcome(Base):
    """What one claim of a due deadline did. One row per claim (fence), so overlapping runs cannot both record."""

    __tablename__ = "timer_outcome"
    __table_args__ = (
        UniqueConstraint("deadline_id", "fence", name="uq_dl_timer_outcome_fence"),
        CheckConstraint(_in("outcome", TIMER_OUTCOMES), name="ck_dl_timer_outcome"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    deadline_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dl.deadline.id", ondelete="RESTRICT",
                                       name="fk_dl_timer_outcome_deadline_id_deadline"), index=True)
    fence: Mapped[int] = mapped_column(BigInteger)
    due_version: Mapped[int] = mapped_column(Integer)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    worker: Mapped[str] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(Text)
    levels_raised: Mapped[int] = mapped_column(SmallInteger, default=0)
    next_fire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    detail: Mapped[str | None] = mapped_column(Text)  # an error category, never free text from an exception


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


class SimClock(Base):
    """Demo time travel, shared by every process (API, timer worker). Ignored outside demo mode."""

    __tablename__ = "sim_clock"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_dl_sim_clock_single_row"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    offset_seconds: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
