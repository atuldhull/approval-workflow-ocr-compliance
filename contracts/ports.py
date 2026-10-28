"""How modules call each other.

A port is an in-process Python call that runs inside the caller's database transaction
(the unit of work). Mandatory work - a workflow transition, the deadlines it opens, its ledger
events and any outbox rows - therefore commits or rolls back together. Only notification
delivery is asynchronous: the notifier reads the outbox after commit.

Implementations are registered in each module's wiring.py; fakes for tests live in fakes.py.
"""
from datetime import datetime
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from sqlalchemy.orm import Session

from contracts.types import (
    Anchor,
    CaseRef,
    EventIn,
    LetterIn,
    OutboundMessage,
    Principal,
    ResourceRef,
    Route,
    RuleSet,
    SubjectRef,
    VerifyResult,
)


@runtime_checkable
class UnitOfWork(Protocol):
    session: Session
    principal: Principal


# ---- provided by the platform module ----

@runtime_checkable
class LedgerPort(Protocol):
    def append(self, uow: UnitOfWork, event: EventIn) -> int: ...
    def verify(self, session: Session) -> VerifyResult: ...


@runtime_checkable
class NotesPort(Protocol):
    def create(self, uow: UnitOfWork, body: str) -> tuple[UUID, str]: ...  # (note_ref, note_hash)


@runtime_checkable
class PersonalDataPort(Protocol):
    def store(self, uow: UnitOfWork, data: dict[str, Any], purpose: str) -> UUID: ...


@runtime_checkable
class OutboxPort(Protocol):
    def enqueue(self, uow: UnitOfWork, msg: OutboundMessage) -> None: ...


@runtime_checkable
class AuthzPort(Protocol):
    def check(self, principal: Principal, action: str, resource: ResourceRef) -> None: ...


# ---- provided by the workflow / intake modules ----

@runtime_checkable
class RulesetPort(Protocol):
    def default_key(self) -> str: ...
    def get(self, key: str) -> RuleSet: ...
    def route_for(self, category: str, key: str) -> Route: ...


@runtime_checkable
class CasePort(Protocol):
    def lookup(self, session: Session, application_id: UUID) -> CaseRef: ...


@runtime_checkable
class EvcPort(Protocol):
    def enter(self, uow: UnitOfWork, case: CaseRef, *, category: str,
              ruleset_key: str, stage_visit_id: UUID, rule_id: str,
              action: str, anchor: Anchor) -> UUID: ...
    def complete(self, uow: UnitOfWork, case: CaseRef, *, ruleset_key: str,
                 rule_id: str, action: str) -> UUID: ...
    def cancel(self, uow: UnitOfWork, case: CaseRef, *, ruleset_key: str,
               rule_id: str, action: str, reason_code: str) -> UUID: ...
    def status(self, session: Session, application_id: UUID) -> str | None: ...


@runtime_checkable
class DeadlineExpiryPort(Protocol):
    """Expiry actions of clocks a module opened (deadlines.yaml on_expiry), e.g. close_appeal_window. The deadline
    worker calls it after marking clocks BREACHED; each action runs in its own unit of work."""
    def run_due(self, limit: int) -> int: ...  # number of expiry actions applied


# ---- provided by the deadlines / compliance modules ----

@runtime_checkable
class DeadlineRuleParserPort(Protocol):
    def parse(self, raw: dict[str, Any]) -> dict[str, Any]: ...


@runtime_checkable
class DeadlinePort(Protocol):
    def open(self, uow: UnitOfWork, subject: SubjectRef, rule_id: str, anchor: Anchor, ruleset_key: str) -> UUID: ...
    def close(self, uow: UnitOfWork, subject: SubjectRef, rule_id: str, outcome: str) -> None: ...
    def pause_internal(self, uow: UnitOfWork, subject: SubjectRef, rule_id: str) -> None: ...
    def resume_internal(self, uow: UnitOfWork, subject: SubjectRef, rule_id: str) -> None: ...


@runtime_checkable
class CompliancePort(Protocol):
    def register_letter(self, uow: UnitOfWork, letter: LetterIn) -> UUID: ...


@runtime_checkable
class ClockPort(Protocol):
    def now(self) -> datetime: ...  # the only source of time in the system
