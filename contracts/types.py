"""Value types passed between modules through the ports in ports.py."""
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from uuid import UUID

from contracts.enums import LetterType, Role, Stage


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    role: Role
    region: str | None = None
    institution_id: UUID | None = None


@dataclass(frozen=True)
class SubjectRef:
    type: str  # "application" | "obligation" | "evc_request" ...
    id: UUID


@dataclass(frozen=True)
class ResourceRef:
    type: str
    id: UUID | None = None
    owner_institution_id: UUID | None = None
    region: str | None = None


@dataclass(frozen=True)
class CaseRef:
    application_id: UUID
    institution_id: UUID
    region: str


@dataclass(frozen=True)
class Anchor:
    at: datetime
    event_seq: int | None = None


@dataclass(frozen=True)
class EventIn:
    aggregate_type: str
    aggregate_id: UUID
    event_type: str  # "<prefix>.<name>", schema in contracts/events/<prefix>/<name>.v<version>.json
    payload: dict[str, Any]
    event_version: int = 1
    reason_code: str | None = None
    ruleset_rev: str | None = None
    note_ref: UUID | None = None
    note_hash: str | None = None
    personal_ref: UUID | None = None


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    checked: int
    first_bad_seq: int | None = None
    detail: str | None = None


@dataclass(frozen=True)
class OutboundMessage:
    alert_id: UUID
    channel: str  # "email" | "sms" | "in_app"
    template: str
    recipient_ref: UUID


@dataclass(frozen=True)
class LetterIn:
    application_id: UUID
    institution_id: UUID
    letter_type: LetterType
    academic_year: str
    issue_date: date
    issue_date_source: str  # PORTAL_EVENT | CONFIRMED_FACT
    lists_deficiencies: bool
    f_no: str | None = None
    issue_date_fact_id: UUID | None = None
    document_version_id: UUID | None = None


@dataclass(frozen=True)
class RouteStage:
    stage: Stage
    when: str = "always"  # "always" | "as_applicable"


@dataclass(frozen=True)
class Route:
    category: str
    label: str
    stages: tuple[RouteStage, ...]


@dataclass(frozen=True)
class RuleSet:
    key: str  # "aph-2024-27@r1"
    ruleset: str
    revision: str
    status: str
    routes: dict[str, Route]
    deadline_rules: dict[str, Any]  # parsed by the deadlines module
    clocks_on_submit: tuple[str, ...] = ()
    roles: dict[str, str] = field(default_factory=dict)
    banner: str | None = None
