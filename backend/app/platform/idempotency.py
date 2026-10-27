"""Safe retries for commands: the same Idempotency-Key never performs the same mutation twice.

The key record is claimed, and the response stored, inside the SAME transaction as the command itself
(the unit of work). Either the command and its stored response commit together, or neither does - there is no
window in which the mutation is saved but the key is not.

Concurrency: the first request inserts the key row; a second request with the same key blocks on the unique
index until the first commits (then it replays the stored response) or rolls back (then it runs the command
itself). A lock timeout turns a long wait into 409.

Keys are scoped to (user, HTTP method, route template). The request fingerprint covers the path parameters and
body, so reusing a key for a different request is refused with 422. No headers or tokens are stored.
"""
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from hashlib import sha256
from typing import Any, TypeVar
from uuid import UUID

from fastapi import Header
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.platform.db import unit_of_work
from app.platform.models import IdempotencyRecord
from app.platform.registry import port
from app.platform.settings import settings
from contracts.errors import Conflict, ValidationFailed
from contracts.ports import ClockPort, UnitOfWork
from contracts.types import Principal

KEY_FORMAT = re.compile(r"^[A-Za-z0-9_\-:.]{8,128}$")
REPLAYED_HEADER = "Idempotent-Replayed"

T = TypeVar("T")


def idempotency_key(idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> str | None:
    """FastAPI dependency for the optional Idempotency-Key header."""
    if idempotency_key is not None and not KEY_FORMAT.match(idempotency_key):
        raise ValidationFailed("Idempotency-Key must be 8-128 characters: letters, digits, '-', '_', ':' or '.'")
    return idempotency_key


def fingerprint(path_params: dict[str, Any], body: Any) -> str:
    canonical = json.dumps({"path": path_params, "body": body}, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True)
class Replay:
    status_code: int
    body: Any


class IdempotencyStore:
    def __init__(self, lock_timeout_ms: int = 5000):
        self.lock_timeout_ms = lock_timeout_ms

    @staticmethod
    def _id(principal_id: UUID, method: str, route: str, key: str) -> dict:
        return {"principal_id": principal_id, "method": method.upper(), "route": route,
                "key_hash": sha256(key.encode()).hexdigest()}

    def claim(self, uow: UnitOfWork, key: str, method: str, route: str, request_hash: str) -> Replay | None:
        """Returns None if this request now owns the key (run the command), or the stored response to replay."""
        session = uow.session
        ident = self._id(uow.principal.user_id, method, route, key)
        now = port(ClockPort).now()
        session.execute(text(f"SET LOCAL lock_timeout = '{int(self.lock_timeout_ms)}ms'"))
        try:
            # an expired record no longer protects anything; let this request reuse the key
            session.execute(delete(IdempotencyRecord).filter_by(**ident).where(IdempotencyRecord.expires_at <= now))
            inserted = session.execute(
                insert(IdempotencyRecord).values(
                    **ident, request_hash=request_hash, created_at=now,
                    expires_at=now + timedelta(hours=settings.idempotency_ttl_hours),
                ).on_conflict_do_nothing().returning(IdempotencyRecord.key_hash)
            ).first()
        except OperationalError as e:
            if "lock timeout" in str(e).lower() or "LockNotAvailable" in type(e.orig).__name__:
                raise Conflict("a request with this Idempotency-Key is still being processed; retry shortly") from None
            raise
        if inserted:
            return None
        record = session.scalars(select(IdempotencyRecord).filter_by(**ident)).one()
        if record.request_hash != request_hash:
            raise ValidationFailed("this Idempotency-Key was already used for a different request")
        return Replay(record.response_status, record.response_body)

    def complete(self, uow: UnitOfWork, key: str, method: str, route: str, status_code: int, body: Any) -> None:
        ident = self._id(uow.principal.user_id, method, route, key)
        record = uow.session.scalars(select(IdempotencyRecord).filter_by(**ident)).one()
        record.response_status = status_code
        record.response_body = body
        uow.session.flush()


store = IdempotencyStore()


def run_idempotent(principal: Principal, key: str | None, method: str, route: str, request_hash: str,
                   command: Callable[[UnitOfWork], T], serialize: Callable[[T], Any],
                   status_code: int) -> tuple[int, Any, bool]:
    """Runs `command` in one unit of work, guarded by `key`. Returns (status, body, replayed)."""
    with unit_of_work(principal) as uow:
        if key is None:
            return status_code, serialize(command(uow)), False
        replay = store.claim(uow, key, method, route, request_hash)
        if replay is not None:
            return replay.status_code, replay.body, True
        body = serialize(command(uow))
        store.complete(uow, key, method, route, status_code, body)
        return status_code, body, False


def idempotent_response(principal: Principal, key: str | None, method: str, route: str,
                        path_params: dict[str, Any], body: Any, command: Callable[[UnitOfWork], T],
                        serialize: Callable[[T], Any], status_code: int = 200) -> JSONResponse:
    """Endpoint helper: run the command idempotently and build the HTTP response."""
    status, payload, replayed = run_idempotent(principal, key, method, route, fingerprint(path_params, body),
                                               command, serialize, status_code)
    headers = {REPLAYED_HEADER: "true"} if replayed else {}
    return JSONResponse(payload, status_code=status, headers=headers)


def purge_expired(session: Session) -> int:
    """Retention: delete expired records. Run periodically (the notifier worker does)."""
    result = session.execute(delete(IdempotencyRecord).where(IdempotencyRecord.expires_at <= port(ClockPort).now()))
    return result.rowcount or 0
