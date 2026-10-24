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


class PersonalStore:
    def store(self, uow: UnitOfWork, data: dict[str, Any], purpose: str) -> UUID:
        row = PersonalData(data=data, purpose=purpose)
        uow.session.add(row)
        uow.session.flush()
        return row.id


class OutboxWriter:
    def enqueue(self, uow: UnitOfWork, msg: OutboundMessage) -> None:
        # (alert_id, channel) is unique, so a retried command can never queue the same alert twice
        uow.session.execute(
            insert(Outbox).values(
                created_at=port(ClockPort).now(), alert_id=msg.alert_id, channel=msg.channel,
                template=msg.template, recipient_ref=msg.recipient_ref, status="PENDING", attempts=0,
            ).on_conflict_do_nothing(index_elements=["alert_id", "channel"])
        )
