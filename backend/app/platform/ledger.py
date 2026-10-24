import json
from datetime import timezone
from functools import lru_cache
from hashlib import sha256
from typing import Any

from jsonschema import Draft202012Validator
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.platform.models import DomainEvent, LedgerEntry
from app.platform.registry import port
from app.platform.settings import settings
from contracts.enums import MODULE_PREFIXES
from contracts.errors import ValidationFailed
from contracts.ports import ClockPort, UnitOfWork
from contracts.types import EventIn, VerifyResult

GENESIS = "0" * 64
_LOCK_KEY = 26262  # serialises appends so seq order == chain order


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _s(value: Any) -> str | None:
    return None if value is None else str(value)


def event_hash(ev: DomainEvent) -> str:
    """SHA-256 over the canonical form of every field that defines the event."""
    return sha256(canonical({
        "seq": ev.seq,
        "at": ev.at.astimezone(timezone.utc).isoformat(),
        "aggregate_type": ev.aggregate_type,
        "aggregate_id": _s(ev.aggregate_id),
        "event_type": ev.event_type,
        "event_version": ev.event_version,
        "actor_id": _s(ev.actor_id),
        "role": ev.role,
        "reason_code": ev.reason_code,
        "ruleset_rev": ev.ruleset_rev,
        "payload": ev.payload,
        "note_ref": _s(ev.note_ref),
        "note_hash": ev.note_hash,
        "personal_ref": _s(ev.personal_ref),
    }).encode()).hexdigest()


def entry_hash(prev: str, ev_hash: str) -> str:
    return sha256(f"{prev}{ev_hash}".encode()).hexdigest()


@lru_cache(maxsize=None)
def _validator(event_type: str, version: int) -> Draft202012Validator:
    prefix, _, name = event_type.partition(".")
    if prefix not in MODULE_PREFIXES or not name:
        raise ValidationFailed(f"event_type must be '<prefix>.<name>' with a known prefix: {event_type}")
    path = settings.contracts_dir / "events" / prefix / f"{name}.v{version}.json"
    if not path.exists():
        raise ValidationFailed(f"no contract schema for {event_type} v{version}")
    schema = json.loads(path.read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)


class Ledger:
    def append(self, uow: UnitOfWork, event: EventIn) -> int:
        payload = json.loads(canonical(event.payload))
        errors = sorted(_validator(event.event_type, event.event_version).iter_errors(payload), key=str)
        if errors:
            raise ValidationFailed(f"{event.event_type}: {errors[0].message}")

        session = uow.session
        session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _LOCK_KEY})
        ev = DomainEvent(
            at=port(ClockPort).now(),
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            event_type=event.event_type,
            event_version=event.event_version,
            actor_id=uow.principal.user_id,
            role=str(uow.principal.role),
            reason_code=event.reason_code,
            ruleset_rev=event.ruleset_rev,
            payload=payload,
            note_ref=event.note_ref,
            note_hash=event.note_hash,
            personal_ref=event.personal_ref,
        )
        session.add(ev)
        session.flush()

        prev = session.scalar(select(LedgerEntry.entry_hash).order_by(LedgerEntry.seq.desc()).limit(1)) or GENESIS
        ev_hash = event_hash(ev)
        session.add(LedgerEntry(seq=ev.seq, event_hash=ev_hash, prev_hash=prev, entry_hash=entry_hash(prev, ev_hash)))
        session.flush()
        return ev.seq

    def verify(self, session: Session) -> VerifyResult:
        """Recompute every event hash and the chain. Detects edits made after the last trusted head."""
        prev = GENESIS
        checked = 0
        rows = session.execute(
            select(DomainEvent, LedgerEntry).outerjoin(LedgerEntry, LedgerEntry.seq == DomainEvent.seq)
            .order_by(DomainEvent.seq)
        )
        for ev, entry in rows:
            checked += 1
            if entry is None:
                return VerifyResult(False, checked, ev.seq, "event has no ledger entry")
            if entry.event_hash != event_hash(ev):
                return VerifyResult(False, checked, ev.seq, "event content does not match its hash")
            if entry.prev_hash != prev or entry.entry_hash != entry_hash(prev, entry.event_hash):
                return VerifyResult(False, checked, ev.seq, "chain link broken")
            prev = entry.entry_hash
        return VerifyResult(True, checked)
