"""Workflow-local typed commands and immutable core inputs; no shared contracts."""
from dataclasses import dataclass, field
from datetime import date
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from contracts.enums import ApplicationStatus, LetterType, Stage
from contracts.errors import Conflict, ValidationFailed
from contracts.types import Principal, ResourceRef


class WorkflowValidationFailed(ValidationFailed):
    def __init__(self, reason_code: str, missing_item_keys: tuple[str, ...] = ()):
        self.reason_code = reason_code
        self.missing_item_keys = missing_item_keys
        super().__init__(reason_code)


class WorkflowConflict(Conflict):
    def __init__(self, reason_code: str):
        self.reason_code = reason_code
        super().__init__(reason_code)


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LetterPayload(Record):
    type: LetterType
    academic_year: Annotated[str, Field(pattern=r"^[0-9]{4}-[0-9]{2}$")]
    issue_date: date
    issue_date_source: Literal["PORTAL_EVENT", "CONFIRMED_FACT"]
    lists_deficiencies: Annotated[bool, Field(strict=True)]
    issue_date_fact_id: UUID | None = None
    document_version_id: UUID | None = None


class ItemResponse(Record):
    item_id: UUID
    response_ref: UUID


class Payload(Record):
    dsc_present: Annotated[bool, Field(strict=True)] | None = None
    target_stage: Stage | None = None
    item_refs: tuple[UUID, ...] = ()
    item_keys: tuple[Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]*$")], ...] = ()
    responses: tuple[ItemResponse, ...] = ()
    response_ref: UUID | None = None
    evidence_refs: tuple[UUID, ...] = ()
    decision_ref: UUID | None = None
    second_approver_ref: UUID | None = None
    letter: LetterPayload | None = None


class Command(Record):
    application_id: UUID
    action: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]
    expected_version: Annotated[int, Field(strict=True, ge=1)]
    reason_code: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]*$")] | None = None
    note_body: str | None = None
    payload: Payload = Field(default_factory=Payload)
    actor: Principal


@dataclass(frozen=True)
class GuardFacts:
    deficiency_status: str | None = None
    missing_item_keys: tuple[str, ...] | None = None
    provided_item_keys: tuple[str, ...] = ()
    dsc_required: bool | None = None
    dsc_present: bool | None = None
    open_item_count: int | None = None
    checklist_complete: bool | None = None
    has_assignment: bool | None = None
    reason_codes: frozenset[str] | None = None
    item_refs: frozenset[UUID] | None = None
    response_refs: frozenset[UUID] | None = None
    decision_refs: frozenset[UUID] | None = None
    confirmed_letter: LetterPayload | None = None
    applicability: dict[str, bool] = field(default_factory=dict)
    live_clock_rules: frozenset[str] | None = None
    second_approval_required: bool | None = None
    second_approver_refs: frozenset[UUID] | None = None


@dataclass(frozen=True)
class State:
    application_id: UUID
    route_id: str
    ruleset_key: str
    current_stage: str | None
    status: ApplicationStatus
    version: int

    @property
    def source(self) -> str:
        if self.status == ApplicationStatus.DRAFT:
            return "DRAFT"
        return self.current_stage or self.status.value


@dataclass(frozen=True)
class Spec:
    position: int
    action: str
    source: str
    target: str
    roles: tuple[str, ...]
    guards: tuple[str, ...]
    timers: tuple[dict[str, Any], ...]
    letter: dict | None
    reason_required: bool
    definition: dict
    emits_event: str


@dataclass(frozen=True)
class CaseContext:
    state: State
    resource: ResourceRef
    stages: tuple[tuple[str, str], ...]
    transitions: tuple[Spec, ...]
    visited: frozenset[str]
    facts: GuardFacts


@dataclass(frozen=True)
class Options:
    demo_mode: bool = True
    enable_letter_issuance: bool = False


@dataclass(frozen=True)
class Decision:
    transition: Spec
    status: ApplicationStatus
    current_stage: str | None


@dataclass(frozen=True)
class ActionAvailability:
    action: str
    targets: tuple[str, ...]
    enabled: bool
    reason_code: str | None
    reason_codes_required: bool
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class OpenedDeadline:
    deadline_id: UUID
    rule_id: str


@dataclass(frozen=True)
class ClosedDeadline:
    subject_id: UUID
    rule_id: str
    outcome: str


@dataclass(frozen=True)
class Result:
    application_id: UUID
    route_id: str
    ruleset_key: str
    current_stage: str | None
    status: ApplicationStatus
    version: int
    event_seqs: tuple[int, ...]
    letter_ref: UUID | None
    assumption_status: str | None
    opened_deadlines: tuple[OpenedDeadline, ...] = ()
    closed_deadlines: tuple[ClosedDeadline, ...] = ()
