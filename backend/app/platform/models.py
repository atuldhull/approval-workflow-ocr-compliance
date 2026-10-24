import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Identity, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.db import Base

SCHEMA = "plat"


class DomainEvent(Base):
    """Full event payloads - the replay source. Payloads hold ids, enums, dates and hashes only."""
    __tablename__ = "domain_event"
    __table_args__ = {"schema": SCHEMA}

    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True, default=uuid.uuid4)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    aggregate_type: Mapped[str] = mapped_column(Text)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    event_type: Mapped[str] = mapped_column(Text)
    event_version: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    role: Mapped[str] = mapped_column(Text)
    reason_code: Mapped[str | None] = mapped_column(Text)
    ruleset_rev: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB)
    note_ref: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    note_hash: Mapped[str | None] = mapped_column(Text)
    personal_ref: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class LedgerEntry(Base):
    """Hash chain over domain_event for tamper evidence."""
    __tablename__ = "ledger_entry"
    __table_args__ = {"schema": SCHEMA}

    seq: Mapped[int] = mapped_column(BigInteger, ForeignKey(f"{SCHEMA}.domain_event.seq"), primary_key=True)
    event_hash: Mapped[str] = mapped_column(Text)
    prev_hash: Mapped[str] = mapped_column(Text)
    entry_hash: Mapped[str] = mapped_column(Text)
    signature: Mapped[str | None] = mapped_column(Text)


class CaseNote(Base):
    """Free text (reasons, observations), kept outside the chain so it can be redacted."""
    __tablename__ = "case_note"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    body: Mapped[str | None] = mapped_column(Text)
    body_hash: Mapped[str] = mapped_column(Text)
    retain_until: Mapped[date | None] = mapped_column(Date)
    redacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PersonalData(Base):
    """Erasable personal fields; events hold only a reference."""
    __tablename__ = "personal_data"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    data: Mapped[dict | None] = mapped_column(JSONB)
    purpose: Mapped[str] = mapped_column(Text)
    retain_until: Mapped[date | None] = mapped_column(Date)
    erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Outbox(Base):
    """Written in the same transaction as the alert; the notifier delivers it after commit."""
    __tablename__ = "outbox"
    __table_args__ = (UniqueConstraint("alert_id", "channel"), {"schema": SCHEMA})

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    alert_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    channel: Mapped[str] = mapped_column(Text)
    template: Mapped[str] = mapped_column(Text)
    recipient_ref: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(Text, default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IdempotencyRecord(Base):
    """One retried command, keyed per user + method + route. Written in the command's own transaction."""
    __tablename__ = "idempotency_key"
    __table_args__ = {"schema": SCHEMA}

    principal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    method: Mapped[str] = mapped_column(Text, primary_key=True)
    route: Mapped[str] = mapped_column(Text, primary_key=True)
    key_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    request_hash: Mapped[str] = mapped_column(Text)
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict | list | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
