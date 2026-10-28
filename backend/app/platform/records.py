"""Case notes, personal data and the outbox - the stores other modules write through ports."""
from hashlib import sha256
from typing import Any
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert

from app.platform.models import CaseNote, Outbox, PersonalData
from app.platform.registry import port
from contracts.ports import ClockPort, UnitOfWork
from contracts.types import OutboundMessage


class Notes:
    def create(self, uow: UnitOfWork, body: str) -> tuple[UUID, str]:
        body_hash = sha256(body.encode("utf-8")).hexdigest()
        note = CaseNote(body=body, body_hash=body_hash)
        uow.session.add(note)
        uow.session.flush()
        return note.id, body_hash


def redact_note(session, note_id: UUID) -> None:
    """Removes a note's text. Its hash stays, so events that anchor the note still verify."""
    note = session.get(CaseNote, note_id)
    if note is not None and note.redacted_at is None:
        note.body, note.redacted_at = None, port(ClockPort).now()


def erase_personal(session, ref: UUID) -> None:
    """Erases personal fields. Events hold only the reference, so the ledger is unaffected."""
    row = session.get(PersonalData, ref)
    if row is not None and row.erased_at is None:
        row.data, row.erased_at = None, port(ClockPort).now()


class PersonalStore:
    def store(self, uow: UnitOfWork, data: dict[str, Any], purpose: str) -> UUID:
        row = PersonalData(data=data, purpose=purpose)
        uow.session.add(row)
        uow.session.flush()
        return row.id


class OutboxWriter:
    def enqueue(self, uow: UnitOfWork, msg: OutboundMessage) -> None:
        # (alert_id, channel) is unique, so a retried command can never queue the same alert twice; a message about
        # an event is unique per (event, recipient, channel) in the same way
        target = ["source_event_id", "recipient_ref", "channel"] if msg.source_event_id else ["alert_id", "channel"]
        uow.session.execute(
            insert(Outbox).values(
                created_at=port(ClockPort).now(), alert_id=msg.alert_id, source_event_id=msg.source_event_id,
                channel=msg.channel, template=msg.template, recipient_ref=msg.recipient_ref, status="PENDING",
                attempts=0,
            ).on_conflict_do_nothing(index_elements=target)
        )
