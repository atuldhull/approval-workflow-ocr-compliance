"""In-memory stand-ins for every port, so each module can be built and tested before the others exist."""
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from contracts.errors import NotFound
from contracts.types import (
    Anchor,
    CaseRef,
    EventIn,
    LetterIn,
    OutboundMessage,
    Principal,
    ResourceRef,
    Route,
    RouteStage,
    RuleSet,
    SubjectRef,
    VerifyResult,
)
from contracts.enums import Stage


class FakeClock:
    def __init__(self, at: datetime | None = None):
        self.at = at or datetime(2026, 7, 1, 4, 30, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self.at


class FakeLedger:
    def __init__(self):
        self.events: list[EventIn] = []

    def append(self, uow, event: EventIn) -> int:
        self.events.append(event)
        return len(self.events)

    def verify(self, session) -> VerifyResult:
        return VerifyResult(ok=True, checked=len(self.events))


class FakeNotes:
    def __init__(self):
        self.notes: dict[UUID, str] = {}

    def create(self, uow, body: str) -> tuple[UUID, str]:
        ref = uuid4()
        self.notes[ref] = body
        return ref, sha256(body.encode()).hexdigest()


class FakePersonalData:
    def __init__(self):
        self.rows: dict[UUID, dict[str, Any]] = {}

    def store(self, uow, data: dict[str, Any], purpose: str) -> UUID:
        ref = uuid4()
        self.rows[ref] = data
        return ref


class FakeOutbox:
    def __init__(self):
        self.messages: list[OutboundMessage] = []

    def enqueue(self, uow, msg: OutboundMessage) -> None:
        self.messages.append(msg)


class AllowAllAuthz:
    def check(self, principal: Principal, action: str, resource: ResourceRef) -> None:
        return None


class FakeRulesets:
    def __init__(self):
        self.ruleset = RuleSet(
            key="test@r1", ruleset="test", revision="r1", status="test",
            routes={"NEW_PROGRAMME": Route("NEW_PROGRAMME", "New programme",
                                           (RouteStage(Stage.SCRUTINY), RouteStage(Stage.EVC),
                                            RouteStage(Stage.SHC, "as_applicable")))},
            deadline_rules={}, clocks_on_submit=("AICTE_PROCESSING",),
        )

    def default_key(self) -> str:
        return self.ruleset.key

    def get(self, key: str) -> RuleSet:
        return self.ruleset

    def route_for(self, category: str, key: str) -> Route:
        try:
            return self.ruleset.routes[category]
        except KeyError:
            raise NotFound(f"unknown category {category}") from None


class FakeCases:
    def __init__(self):
        self.cases: dict[UUID, CaseRef] = {}

    def lookup(self, session, application_id: UUID) -> CaseRef:
        try:
            return self.cases[application_id]
        except KeyError:
            raise NotFound("application not found") from None


class FakeDeadlineRuleParser:
    def parse(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {r["id"]: r for r in raw.get("rules", [])}


class FakeDeadlines:
    def __init__(self):
        self.calls: list[tuple[str, SubjectRef, str]] = []

    def open(self, uow, subject: SubjectRef, rule_id: str, anchor: Anchor, ruleset_key: str) -> UUID:
        self.calls.append(("open", subject, rule_id))
        return uuid4()

    def close(self, uow, subject: SubjectRef, rule_id: str, outcome: str) -> None:
        self.calls.append(("close", subject, rule_id))

    def pause_internal(self, uow, subject: SubjectRef, rule_id: str) -> None:
        self.calls.append(("pause", subject, rule_id))

    def resume_internal(self, uow, subject: SubjectRef, rule_id: str) -> None:
        self.calls.append(("resume", subject, rule_id))


class FakeCompliance:
    def __init__(self):
        self.letters: list[LetterIn] = []

    def register_letter(self, uow, letter: LetterIn) -> UUID:
        self.letters.append(letter)
        return uuid4()
