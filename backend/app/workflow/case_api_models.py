"""HTTP-only workflow shapes; shared ports and value types remain unchanged."""
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.workflow.commands import Payload
from contracts.enums import ApplicationStatus, Stage


class ActionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]
    expected_version: Annotated[int, Field(strict=True, ge=1)]
    reason_code: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]*$")] | None = None
    note: str | None = None
    payload: Payload = Field(default_factory=Payload)


class ActionOut(BaseModel):
    action: str
    targets: list[str]
    enabled: bool
    reason_code: str | None
    reason_codes_required: bool
    aliases: list[str]


class OpenedDeadlineOut(BaseModel):
    deadline_id: UUID
    rule_id: str


class ClosedDeadlineOut(BaseModel):
    subject_id: UUID
    rule_id: str
    outcome: str


class CaseActionOut(BaseModel):
    case_id: UUID
    stage: Stage | None
    status: ApplicationStatus
    version: int
    available_actions: list[ActionOut]
    opened_deadlines: list[OpenedDeadlineOut]
    closed_deadlines: list[ClosedDeadlineOut]
    assumption_status: Literal["DEMO_ASSUMPTION"] | None


class VisitOut(BaseModel):
    id: UUID
    stage: Stage
    entered_at: datetime
    exited_at: datetime | None
    outcome: str | None
    reason_code: str | None
    note_ref: UUID | None


class RouteStageOut(BaseModel):
    stage: Stage
    when: Literal["always", "as_applicable"]


class CaseOut(BaseModel):
    case_id: UUID
    institution_id: UUID
    region: str
    stage: Stage | None
    status: ApplicationStatus
    version: int
    route_id: str
    ruleset_key: str | None
    # Draft route previews are not a persisted ruleset pin.
    preview_ruleset_key: str | None
    route: list[RouteStageOut]
    clause_citation: dict | None
    stage_history: list[VisitOut]
    available_actions: list[ActionOut]
    assumption_status: Literal["DEMO_ASSUMPTION"] | None


class CasePageOut(BaseModel):
    items: list[CaseOut]
    total: int
    offset: int
    limit: int


class CaseErrorOut(BaseModel):
    error: str
    detail: str


class CaseInputErrorOut(BaseModel):
    detail: list[dict]


class CaseSubmissionErrorOut(CaseErrorOut):
    reason_code: Literal["MANDATORY_ITEMS_MISSING"]
    missing_item_keys: list[str]


ERROR_RESPONSES = {code: {"model": CaseErrorOut} for code in (403, 404, 409)}
ERROR_RESPONSES[422] = {"model": CaseErrorOut | CaseInputErrorOut | CaseSubmissionErrorOut}
