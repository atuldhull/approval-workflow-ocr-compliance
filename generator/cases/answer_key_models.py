"""Proposed DEMO answer key. No database writes, ID generation or clock reads.

The checked-in schema is this model's JSON validation schema plus $schema/$id.
Model validation additionally checks relationships JSON Schema cannot express.
"""
from datetime import date, datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from contracts.enums import ApplicationStatus, ClockKind, ClockOwner, LetterType, Stage


def _uuid(value: str) -> str:
    UUID(value)
    return value


def _instant(value: str) -> str:
    datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    return value


def _date(value: str) -> str:
    date.fromisoformat(value)
    return value


Id = Annotated[str, Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", json_schema_extra={"format": "uuid"}), AfterValidator(_uuid)]
Instant = Annotated[str, Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$", json_schema_extra={"format": "date-time"}), AfterValidator(_instant)]
IsoDate = Annotated[str, Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$", json_schema_extra={"format": "date"}), AfterValidator(_date)]
Code = Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]*$")]
RulesetKey = Annotated[str, Field(pattern=r"^[a-z0-9-]+@[A-Za-z0-9-]+$")]
Version = Annotated[str, Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]
Count = Annotated[int, Field(ge=0, strict=True)]
Positive = Annotated[int, Field(gt=0, strict=True)]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ReservedExtensions(Record):
    """Owner-reserved; only {} is valid until a reviewed version defines fields."""


class Counts(Record):
    institutions: Count
    applications: Count
    deficiency_loops: Count
    deficiency_items: Count
    late_responses: Count
    evc_delays: Count
    letters: Count
    clock_expectations: Count


class Header(Record):
    schema_version: Literal["0.1.0"]
    review_status: Literal["PROPOSED_TEAM_REVIEW"]
    label: Literal["DEMO"]
    seed: Count
    generator_version: Version
    ruleset_key: RulesetKey
    generated_at_clock: Instant
    counts: Counts


class Institution(Record):
    id: Id
    region: Code
    ro_id: Code
    category: Code
    label: Literal["DEMO"]


class Application(Record):
    id: Id
    institution_id: Id
    category: Code
    route_id: Code
    pinned_ruleset_key: RulesetKey
    label: Literal["DEMO"]


class DeficiencyItem(Record):
    id: Id
    status: Literal["OPEN", "RESOLVED"]
    resolved_at_clock: Instant | None
    resolution_response_id: Id | None

    @model_validator(mode="after")
    def resolution(self) -> Self:
        resolved = self.status == "RESOLVED"
        if (self.resolved_at_clock is not None) != resolved or (self.resolution_response_id is not None) != resolved:
            raise ValueError("RESOLVED requires resolution time/response; OPEN requires nulls")
        return self


class DeficiencyLoop(Record):
    id: Id
    recorded_at_clock: Instant
    as_of_clock: Instant
    response_id: Id | None
    responded_at_clock: Instant | None
    items: Annotated[list[DeficiencyItem], Field(min_length=1)]

    @model_validator(mode="after")
    def timeline(self) -> Self:
        if self.as_of_clock < self.recorded_at_clock:
            raise ValueError("loop snapshot precedes recording")
        if (self.response_id is None) != (self.responded_at_clock is None):
            raise ValueError("response ID and time must occur together")
        if self.responded_at_clock is not None and not self.recorded_at_clock <= self.responded_at_clock <= self.as_of_clock:
            raise ValueError("response outside loop interval")
        for item in self.items:
            if item.status == "RESOLVED" and (
                item.resolution_response_id != self.response_id
                or item.resolved_at_clock != self.responded_at_clock
            ):
                raise ValueError("resolved item must reference this loop's response/time")
        return self


class LateResponse(Record):
    response_id: Id
    loop_id: Id
    expected_by_clock: Instant
    responded_at_clock: Instant
    late_by_seconds: Positive

    @model_validator(mode="after")
    def duration(self) -> Self:
        if _seconds(self.expected_by_clock, self.responded_at_clock) != self.late_by_seconds:
            raise ValueError("late response duration mismatch")
        return self


class EvcDelay(Record):
    request_id: Id
    planned_at_clock: Instant
    actual_at_clock: Instant
    delay_seconds: Positive

    @model_validator(mode="after")
    def duration(self) -> Self:
        if _seconds(self.planned_at_clock, self.actual_at_clock) != self.delay_seconds:
            raise ValueError("EVC delay duration mismatch")
        return self


class RouteStageExpectation(Record):
    stage: Stage
    when: Literal["always", "as_applicable"]


class RouteOutcome(Record):
    at_clock: Instant
    expected_stage_list: Annotated[list[RouteStageExpectation], Field(min_length=1)]
    expected_visited_stages: list[Stage]
    expected_status: ApplicationStatus


class LetterExpectation(Record):
    id: Id
    type: LetterType
    issue_at_clock: Instant
    lists_deficiencies: Annotated[bool, Field(strict=True)]


class WorkflowExpectation(Record):
    application_id: Id
    deficiency_loop_count: Count
    deficiency_loops: list[DeficiencyLoop]
    late_responses: list[LateResponse]
    evc_delays: list[EvcDelay]
    route_outcome: RouteOutcome
    letters_to_issue: list[LetterExpectation]

    @model_validator(mode="after")
    def loops(self) -> Self:
        if self.deficiency_loop_count != len(self.deficiency_loops):
            raise ValueError("deficiency_loop_count mismatch")
        loops = {loop.id: loop for loop in self.deficiency_loops}
        for response in self.late_responses:
            loop = loops.get(response.loop_id)
            if loop is None or (loop.response_id, loop.responded_at_clock) != (response.response_id, response.responded_at_clock):
                raise ValueError("late response must match a planted loop response")
            if response.expected_by_clock < loop.recorded_at_clock:
                raise ValueError("response deadline precedes deficiency")
        return self


class ClockExpectation(Record):
    id: Id
    application_id: Id
    subject_type: Literal["application", "obligation", "evc_request"]
    subject_id: Id
    rule_id: Code
    clock_kind: ClockKind
    clock_owner: ClockOwner
    at_clock: Instant
    basis: Literal["RULESET", "DEMO_ASSUMPTION"]


class ClockOpen(ClockExpectation):
    operation: Literal["OPEN"]
    anchor_at_clock: Instant
    expected_due_date: IsoDate
    expected_due_at_clock: Instant

    @model_validator(mode="after")
    def timeline(self) -> Self:
        if self.anchor_at_clock > self.at_clock or self.expected_due_at_clock < self.anchor_at_clock:
            raise ValueError("invalid opening anchor/due chronology")
        return self


class ClockPauseResume(ClockExpectation):
    operation: Literal["PAUSE", "RESUME"]
    clock_kind: Literal[ClockKind.INTERNAL]


class ClockClose(ClockExpectation):
    operation: Literal["CLOSE"]
    outcome: Literal["MET", "WAIVED"]


ClockOperation = Annotated[ClockOpen | ClockPauseResume | ClockClose, Field(discriminator="operation")]


def _seconds(start: str, end: str) -> int:
    return int((datetime.strptime(end, "%Y-%m-%dT%H:%M:%SZ") - datetime.strptime(start, "%Y-%m-%dT%H:%M:%SZ")).total_seconds())


def _unique(values: list[str], kind: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate {kind}")


class AnswerKey(Record):
    header: Header
    institutions: list[Institution]
    applications: list[Application]
    workflow_expectations: list[WorkflowExpectation]
    clock_expectations: list[ClockOperation]
    p2_extensions: ReservedExtensions
    p3_extensions: ReservedExtensions

    @model_validator(mode="after")
    def relationships(self) -> Self:
        _unique([i.id for i in self.institutions], "institution IDs")
        _unique([a.id for a in self.applications], "application IDs")
        _unique([w.application_id for w in self.workflow_expectations], "workflow application IDs")
        _unique([c.id for c in self.clock_expectations], "clock expectation IDs")
        institutions = {i.id for i in self.institutions}
        apps = {a.id: a for a in self.applications}
        if set(apps) != {w.application_id for w in self.workflow_expectations}:
            raise ValueError("exactly one workflow expectation is required per application")
        for app in self.applications:
            if app.institution_id not in institutions:
                raise ValueError("unknown institution reference")
            if app.route_id != app.category or app.pinned_ruleset_key != self.header.ruleset_key:
                raise ValueError("route/category or pinned ruleset mismatch")
        loops = [loop for w in self.workflow_expectations for loop in w.deficiency_loops]
        items = [item for loop in loops for item in loop.items]
        responses = [loop.response_id for loop in loops if loop.response_id is not None]
        delays = [d for w in self.workflow_expectations for d in w.evc_delays]
        letters = [letter for w in self.workflow_expectations for letter in w.letters_to_issue]
        for values, kind in [([loop.id for loop in loops], "loop IDs"), ([i.id for i in items], "item IDs"),
                             (responses, "response IDs"), ([d.request_id for d in delays], "EVC request IDs"),
                             ([letter.id for letter in letters], "letter IDs")]:
            _unique(values, kind)
        for w in self.workflow_expectations:
            _unique([r.response_id for r in w.late_responses], "late response IDs")
        for c in self.clock_expectations:
            if c.application_id not in apps or (c.subject_type == "application" and c.subject_id != c.application_id):
                raise ValueError("clock application/subject reference mismatch")
        actual = Counts(
            institutions=len(self.institutions), applications=len(self.applications),
            deficiency_loops=len(loops), deficiency_items=len(items),
            late_responses=sum(len(w.late_responses) for w in self.workflow_expectations),
            evc_delays=len(delays), letters=len(letters), clock_expectations=len(self.clock_expectations),
        )
        if self.header.counts != actual:
            raise ValueError("header counts mismatch")
        return self


def answer_key_json_schema() -> dict:
    """Return the proposal's draft 2020-12 schema without writing any file."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:sih26262:p1:answer-key:0.1.0",
        **AnswerKey.model_json_schema(mode="validation"),
    }
