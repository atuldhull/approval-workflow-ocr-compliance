"""In-memory stand-ins for every port, so each module can be built and tested before the others exist."""
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any
from uuid import UUID, NAMESPACE_URL, uuid4, uuid5

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
    def __init__(self, *, reference_factory=uuid4):
        self.rows: dict[UUID, dict[str, Any]] = {}
        self.reference_factory = reference_factory

    def store(self, uow, data: dict[str, Any], purpose: str) -> UUID:
        ref = self.reference_factory()
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


class FakeEvc:
    """Nontransactional port fake; DB rollback tests must use real storage."""

    def __init__(self):
        self.calls = []
        self.requests = {}

    def enter(self, uow, case, *, category, ruleset_key, stage_visit_id, rule_id, action, anchor):
        request_id = uuid5(NAMESPACE_URL, f"sih26262:evc:request:{stage_visit_id}")
        self.calls.append(("enter", case.application_id, request_id, rule_id, ruleset_key))
        if self.requests.get(case.application_id, (None,))[0] != request_id:
            self.requests[case.application_id] = (request_id, "QUEUED")
        return request_id

    def complete(self, uow, case, *, ruleset_key, rule_id, action):
        request_id, _ = self.requests[case.application_id]
        self.calls.append(("complete", case.application_id, request_id, rule_id, ruleset_key))
        self.requests[case.application_id] = (request_id, "DONE")
        return request_id

    def cancel(self, uow, case, *, ruleset_key, rule_id, action, reason_code):
        request_id, _ = self.requests[case.application_id]
        self.calls.append(("cancel", case.application_id, request_id, rule_id, ruleset_key))
        self.requests[case.application_id] = (request_id, "CANCELLED")
        return request_id

    def status(self, session, application_id):
        request = self.requests.get(application_id)
        return request[1] if request else None


class FakeCompliance:
    def __init__(self):
        self.letters: list[LetterIn] = []

    def register_letter(self, uow, letter: LetterIn) -> UUID:
        self.letters.append(letter)
        return uuid4()


class FakeDeadlineExpiry:
    def __init__(self):
        self.runs: list[int] = []

    def run_due(self, limit: int) -> int:
        self.runs.append(limit)
        return 0
