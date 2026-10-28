import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Identity, Index, Integer, Text, UniqueConstraint
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
    """Written in the same transaction as the alert, or by the notifier for a recorded event; delivered after commit.

    A row is about one alert (one row per alert and channel) or one domain event (one row per event, recipient and
    channel), never both."""
    __tablename__ = "outbox"
    __table_args__ = (UniqueConstraint("alert_id", "channel"),
                      UniqueConstraint("source_event_id", "recipient_ref", "channel",
                                       name="uq_plat_outbox_event_recipient_channel"),
                      CheckConstraint("(alert_id IS NULL) <> (source_event_id IS NULL)",
                                      name="ck_plat_outbox_one_subject"),
                      Index("ix_plat_outbox_due", "status", "next_attempt_at"), {"schema": SCHEMA})

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    alert_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    source_event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    channel: Mapped[str] = mapped_column(Text)
    template: Mapped[str] = mapped_column(Text)
    recipient_ref: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(Text, default="PENDING")  # PENDING | SENDING | DELIVERED | DEAD
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claimed_by: Mapped[str | None] = mapped_column(Text)          # worker holding the lease
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)          # error category only, never provider text
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dead_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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


class Checkpoint(Base):
    """A signed statement of the ledger head. The trusted copy lives outside the database (the witness)."""
    __tablename__ = "checkpoint"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    head_seq: Mapped[int] = mapped_column(BigInteger)
    head_hash: Mapped[str] = mapped_column(Text)
    entry_count: Mapped[int] = mapped_column(BigInteger)
    key_id: Mapped[str] = mapped_column(Text)
    statement: Mapped[str] = mapped_column(Text)     # the exact canonical JSON that was signed
    signature: Mapped[str] = mapped_column(Text)     # base64 Ed25519
    status: Mapped[str] = mapped_column(Text, server_default="PUBLISHED")   # PENDING | PUBLISHED
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    publish_error: Mapped[str | None] = mapped_column(Text)


class DeliveryAttempt(Base):
    """Every try to deliver an outbox row: when, which worker, and how it ended."""
    __tablename__ = "delivery_attempt"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    outbox_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.outbox.id"), index=True)
    attempt_no: Mapped[int] = mapped_column(Integer)
    worker: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    outcome: Mapped[str] = mapped_column(Text)              # DELIVERED | TRANSIENT | PERMANENT | AMBIGUOUS
    error_category: Mapped[str | None] = mapped_column(Text)
    provider_ref: Mapped[str | None] = mapped_column(Text)


class DeliveryRecipient(Base):
    """Per-recipient result of an email/SMS message, so retries only go to recipients not yet reached.
    Holds a salted hash of the address, never the address itself."""
    __tablename__ = "delivery_recipient"
    __table_args__ = {"schema": SCHEMA}

    outbox_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.outbox.id"), primary_key=True)
    recipient_key: Mapped[str] = mapped_column(Text, primary_key=True)
    outcome: Mapped[str] = mapped_column(Text)        # DELIVERED | REFUSED
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Notification(Base):
    """In-app inbox. One row per outbox row, so in-app delivery happens exactly once."""
    __tablename__ = "notification"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    outbox_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.outbox.id"), unique=True)
    alert_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    source_event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    recipient_ref: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    template: Mapped[str] = mapped_column(Text)
    # what the message was about, worked out once at delivery: case, rule, due date, links. Ids and dates only.
    context: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NotifyCursor(Base):
    """How far the notifier has read the event log for event notifications. One row per consumer."""
    __tablename__ = "notify_cursor"
    __table_args__ = {"schema": SCHEMA}

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    seq: Mapped[int] = mapped_column(BigInteger)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RecipientMember(Base):
    """Who is in a recipient group (an opaque id such as 'regional officers, Southern')."""
    __tablename__ = "recipient_member"
    __table_args__ = {"schema": SCHEMA}

    recipient_ref: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, index=True)


class UserContact(Base):
    """Where to reach a user on a channel. The address itself is erasable personal data."""
    __tablename__ = "user_contact"
    __table_args__ = {"schema": SCHEMA}

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    channel: Mapped[str] = mapped_column(Text, primary_key=True)
    personal_ref: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.personal_data.id"))
