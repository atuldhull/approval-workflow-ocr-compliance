# Person 1 repository audit

Date: 24 October 2026 (Asia/Calcutta). Branch: `person-1`. Audited HEAD: `6349b0d`.
This report describes checked-out source, not deployed infrastructure or verified APH law. Reference documents are requirements and historical claims, not authorization to implement them. Only this new audit file is written. No source fixes, commit, push, or contract refresh was performed. Verification dependencies were installed outside the repository; database mutations were restricted to a dedicated disposable PostgreSQL container. No separate plan or assumptions file was created because the user authorized exactly one new file.

## 1. Directory map: actual files

The following is the complete tracked-file inventory at the start of the audit, including hidden configuration and empty-directory markers. The audit itself is the only addition. `.git/` internals and ignored Python bytecode are not project source and are excluded. A folder with only `.gitkeep` is not an implemented feature.

```text
.env.example
.gitattributes
.github/CODEOWNERS
.github/pull_request_template.md
.github/workflows/ci.yml
.github/workflows/contracts-approval.yml
.gitignore
AGENTS.md
README.md
backend/Dockerfile
backend/alembic.ini
backend/app/__init__.py
backend/app/analytics/README.md
backend/app/analytics/__init__.py
backend/app/compliance/README.md
backend/app/compliance/__init__.py
backend/app/deadlines/__init__.py
backend/app/deadlines/api.py
backend/app/deadlines/clock.py
backend/app/deadlines/models.py
backend/app/deadlines/rules.py
backend/app/deadlines/service.py
backend/app/deadlines/wiring.py
backend/app/documents/README.md
backend/app/documents/__init__.py
backend/app/evc/README.md
backend/app/evc/__init__.py
backend/app/intake/__init__.py
backend/app/intake/api.py
backend/app/intake/models.py
backend/app/intake/service.py
backend/app/intake/wiring.py
backend/app/main.py
backend/app/platform/__init__.py
backend/app/platform/api.py
backend/app/platform/auth.py
backend/app/platform/db.py
backend/app/platform/ledger.py
backend/app/platform/models.py
backend/app/platform/records.py
backend/app/platform/registry.py
backend/app/platform/settings.py
backend/app/platform/wiring.py
backend/app/workflow/__init__.py
backend/app/workflow/api.py
backend/app/workflow/registry.py
backend/app/workflow/wiring.py
backend/migrations/env.py
backend/migrations/script.py.mako
backend/migrations/versions/analytics/.gitkeep
backend/migrations/versions/compliance/.gitkeep
backend/migrations/versions/deadlines/dl_0001_deadline.py
backend/migrations/versions/documents/.gitkeep
backend/migrations/versions/evc/.gitkeep
backend/migrations/versions/platform/plat_0001_event_store.py
backend/migrations/versions/workflow/wf_0001_intake.py
backend/requirements-dev.txt
backend/requirements.txt
backend/tests/test_deadline_rules.py
backend/tests/test_ledger.py
backend/tests/test_rulesets.py
backend/tests/test_schema_matches_models.py
conftest.py
contracts/__init__.py
contracts/enums.py
contracts/errors.py
contracts/events/dl/deadline_opened.v1.json
contracts/events/wf/application_created.v1.json
contracts/events/wf/application_submitted.v1.json
contracts/fakes.py
contracts/openapi.json
contracts/ports.py
contracts/types.py
docker-compose.yml
docs/ARCHITECTURE.md
docs/OWNERSHIP.md
docs/TEAM_WORKFLOW.md
docs/p1/.gitkeep
docs/p1/plans/.gitkeep
docs/reference/SIH26262_Person1_Work_Pack.pdf
docs/reference/SIH26262_Person1_Work_Pack.txt
docs/reference/SIH26262_Team_Split.pdf
docs/reference/SIH26262_Team_Split.txt
frontend/index.html
frontend/package-lock.json
frontend/package.json
frontend/src/App.jsx
frontend/src/api.js
frontend/src/components/ApplicationList.jsx
frontend/src/components/CaseDetail.jsx
frontend/src/components/NewApplication.jsx
frontend/src/main.jsx
frontend/src/styles.css
frontend/vite.config.js
generator/cases/seed_demo.py
generator/documents/.gitkeep
pyproject.toml
rulesets/aph-2024-27/r1/deadlines.yaml
rulesets/aph-2024-27/r1/routes.yaml
rulesets/aph-2024-27/r3-DEMO/overlay.yaml
scripts/check_contracts.py
scripts/check_migration_heads.py
tests/e2e/step01_submit_test.py
```

Actual module packages: `platform`, `analytics`, `compliance`, `deadlines`, `documents`, `evc`, `intake`, `workflow`. `analytics`, `compliance`, `documents`, and `evc` have only `__init__.py` and a planned-feature README. `generator/documents/` is a `.gitkeep` placeholder. Only platform, workflow, and deadlines migration chains contain revisions; the other version directories are placeholders. No `calendars/` implementation exists. `docs/p1/plans/` contains only `.gitkeep`; no `docs/p1/ASSUMPTIONS.md`, contract requests, or Final Report text exists.

## 2. Existing P1 implementation inventory

### Tables and models

All three persisted P1 models are in `backend/app/intake/models.py`, schema `wf`, created by `backend/migrations/versions/workflow/wf_0001_intake.py` (`revision="wf_0001"`, `down_revision=None`, `branch_labels=("workflow",)`). No separate intake migration chain exists.

| Model / table | Fields (nullable indicated by `?`) |
|---|---|
| `Institution` / `wf.institution` | `id UUID PK` (uuid4 default), `name Text`, `ro_region Text`, `is_demo Boolean` (default true) |
| `Application` / `wf.application` | `id UUID PK` (uuid4), `institution_id UUID FK wf.institution.id` (indexed), `category Text`, `academic_year Text`, `status Text`, `current_stage Text?`, `ruleset_rev Text?`, `route JSONB?`, `created_at timestamptz`, `submitted_at timestamptz?` |
| `StageVisit` / `wf.stage_visit` | `id UUID PK` (uuid4), `application_id UUID FK wf.application.id` (indexed), `stage Text`, `entered_at timestamptz`, `left_at timestamptz?` |

There are no workflow `models.py` or EVC `models.py`. No `submission`, persisted `ruleset`, `route_def`, `transition`, deficiency, committee, or EVC tables are implemented. `stage_visit` currently records only submission entry; nothing closes or advances it.

API Pydantic models in `backend/app/intake/api.py`: `InstitutionOut(id, name, ro_region, is_demo)`, `ApplicationIn(institution_id, category, academic_year)` with category/academic-year regex validation, and `ApplicationOut(id, institution_id, category, academic_year, status, current_stage, ruleset_rev, route, created_at, submitted_at)`. `backend/app/workflow/api.py` defines `StageOut(stage, when)`, `RouteOut(category, label, stages)`, `RulesetOut(key, status, banner, is_default, routes)`. There are no EVC or generator API models.

### Endpoints

Every router is prefixed `/api` by `backend/app/main.py`.

| Method and path | Source / behavior |
|---|---|
| GET `/api/institutions` | `backend/app/intake/api.py:list_institutions`; demo institution list |
| POST `/api/applications` | `intake/api.py:create`; 201; `service.create_application` |
| POST `/api/applications/{application_id}/submit` | `intake/api.py:submit`; `service.submit_application` |
| GET `/api/applications` | `intake/api.py:list_applications`; institution-scoped for institution role |
| GET `/api/applications/{application_id}` | `intake/api.py:get_application`; object authorization |
| GET `/api/rulesets` | `workflow/api.py:list_rulesets`; directory keys via registry `available()` |
| GET `/api/rulesets/{key}` | `workflow/api.py:get_ruleset`; route representation and demo banner |

No `/cases/{id}/actions`, EVC, admin ruleset write/validate/approve, letter issuance, or generator endpoints exist. Timeline is supplied by P3 at `backend/app/platform/api.py`, not P1.

### Events, ports, YAML, generator

- `wf.application_created` v1: emitted by `backend/app/intake/service.py:create_application`; schema `contracts/events/wf/application_created.v1.json`. Required payload: application_id, institution_id, category, academic_year.
- `wf.application_submitted` v1: emitted by `submit_application`; schema `contracts/events/wf/application_submitted.v1.json`. Required payload: application_id, institution_id, category, ruleset_rev, first_stage, route. Route payload is a list of stage strings, not `when` objects. Both schemas prohibit additional properties.
- Submission synchronously invokes P2 `DeadlinePort.open`, which emits `dl.deadline_opened` v1 (`backend/app/deadlines/service.py`, `contracts/events/dl/deadline_opened.v1.json`). This is not a P1-owned event. No other workflow or EVC event schemas exist.
- P1 `CasePort` implementation: `backend/app/intake/service.py:Cases.lookup`, registered by `intake/wiring.py`; returns institution and region for an application.
- P1 `RulesetPort` implementation: `backend/app/workflow/registry.py:RulesetRegistry.default_key/get/route_for`, registered by `workflow/wiring.py`. Extra concrete method `available()` is used by the API but absent from the Protocol. No EVC or generator port implementation exists.
- P1 YAML: `rulesets/aph-2024-27/r1/routes.yaml` and `rulesets/aph-2024-27/r3-DEMO/overlay.yaml`. P2 YAML consumed through `DeadlineRuleParserPort`: `rulesets/aph-2024-27/r1/deadlines.yaml` (six rules: AICTE_PROCESSING, INSTITUTION_RESPONSE, APPEAL_7D, DEPOSIT_15D, EOA_DEFICIENCY_6M, LEASE_EOA_STOP).
- `generator/cases/seed_demo.py` contains `seed() -> int`: three fixed-UUID fictional DEMO institutions, Southern/Northern/Western regions, PostgreSQL insert-on-conflict-do-nothing, direct session commit, returns 3. It generates no applications, seeded distributions, workflow scenarios, EVC demand, or answer key. No dedicated generator test exists; integration fixtures call it.

### Tests: exact existing names

P1-focused tests are the ruleset tests and step01 tests below. Ledger and schema tests are integration evidence involving P1; deadline-rule tests belong to P2. There are no step02, step03, step04, step10, EVC, deficiency, committee, or scale-generator tests.

`backend/tests/test_deadline_rules.py`:

- `test_month_end_is_clamped`
- `test_due_dates_use_the_indian_calendar_date`
- `test_working_days_need_a_calendar`
- `test_r1_rules_parse`
- `test_invalid_rules_are_rejected`
- `test_duplicate_rule_ids_are_rejected`

`backend/tests/test_ledger.py`:

- `test_unknown_event_types_are_rejected`
- `test_payloads_must_match_their_schema`
- `test_untouched_chain_verifies`
- `test_editing_an_event_is_detected`
- `test_deleting_an_event_is_detected`
- `test_institutions_cannot_verify_the_ledger`

`backend/tests/test_rulesets.py`:

- `test_r1_has_all_table_2_3_rows_plus_new_institution`
- `test_shc_is_optional_exactly_where_evc_is_required`
- `test_rows_corrected_from_the_page_image`
- `test_new_institution_follows_chapter_one`
- `test_unknown_category_is_rejected`
- `test_static_validation_rejects_bad_routes`
- `test_unverified_overlay_is_refused_outside_demo_mode`
- `test_overlay_changes_roles_but_not_routes`

`backend/tests/test_schema_matches_models.py`:

- `test_models_match_migrations`

`tests/e2e/step01_submit_test.py`:

- `test_submission_routes_opens_clock_and_records_everything`
- `test_a_failure_anywhere_rolls_back_the_whole_submission`
- `test_submitting_twice_is_refused`
- `test_an_institution_cannot_touch_another_institutions_application`
- `test_officers_cannot_file_applications`
- `test_categories_without_a_route_are_rejected`
- `test_self_disclosure_route_has_a_single_stage`

`conftest.py` provides demo headers, a PostgreSQL database fixture and client fixture. It drops/recreates the configured test database, migrates all heads, truncates non-public schemas, seeds institutions, and resets the clock. `test_invalid_rules_are_rejected` has four parameter cases: 28 named test functions therefore imply 31 cases by static counting; the final Linux verification below independently confirmed all 31 cases pass.

## 3. Exact YAML shape and behavior

`routes.yaml` top-level keys: `ruleset` (string), `revision` (string), `status` (string), `source` (mapping doc/clause/page), `roles` (mapping evc_constituted_by), `clocks` (mapping on_submit), `routes` (category-keyed mapping), `appeal` (trigger/window/max_appeals), `transitions` (list of mappings).

`routes.<CATEGORY>` has `label` and `stages`. A stage item is a scalar enum string (implicit `when="always"`) or a mapping `{stage: <enum>, when: always|as_applicable}`. Missing mapping `when` defaults to always. There is no numeric route-id field: category keys ARE route identifiers. SHC is optional in the actual YAML wherever EVC occurs. The parser checks EVC/SHC presence equivalence, known stages, known when values, and nonempty lists; it does not enforce ordering, uniqueness, or SHC optionality itself.

`clocks.on_submit` is an ordered list of deadline rule IDs; each must be returned by P2's parser. Intake opens every listed clock at submission time with the workflow event sequence as Anchor.event_seq.

`transitions` represents scalar, list, and wildcard `from`; literal actions; literal or symbolic targets `next_stage`/`$target`; optional roles, require, guard, timers. Timers map `pause/start/stop/resume` to scalar rule IDs, not lists. The final require list is mixed: `reason` is a scalar and `second_approver_if: target_is_terminal` is a mapping. These are unexecuted declarations: `RuleSet` has no transitions, appeal, source, or timer fields and `_load` drops them.

Real excerpt 1: complete current base YAML, preserving all 22 category IDs, stage lists, transition declarations, and submit clocks:

Source: `rulesets/aph-2024-27/r1/routes.yaml`

```yaml
# Default ruleset: base Approval Process Handbook 2024-25 to 2026-27, as read.
# Still a demo configuration until an authorised AICTE reviewer signs it off.
ruleset: aph-2024-27
revision: r1
status: verified_text
source: {doc: "APH 2024-25 to 2026-27", clause: "Table 2.3", page: 30}

roles:
  evc_constituted_by: REGIONAL_OFFICER

# Clocks opened when an application is submitted (rule ids from deadlines.yaml).
clocks:
  on_submit: [AICTE_PROCESSING]

# Table 2.3: SHC is "as applicable" exactly where an EVC is required.
routes:
  EOA_SELF_DISCLOSURE:
    label: Extension of Approval based on self-disclosure
    stages: [SELF_DISCLOSURE]
  NRI_SEATS:
    label: Introduction/continuation of NRI seats
    stages: [SELF_DISCLOSURE]
  CONVERSION_LEVEL:
    label: Conversion diploma to degree level or vice versa
    stages: [SCRUTINY, EVC, {stage: SHC, when: as_applicable}]
  CHANGE_OF_NAME:
    label: Change of name of institution / affiliating university / board / type
    stages: [SCRUTINY]
  NEW_PROGRAMME:
    label: New programme / level in existing institution
    stages: [SCRUTINY, EVC, {stage: SHC, when: as_applicable}]
  MERGER:
    label: Merger of institutions
    stages: [SCRUTINY, EVC, {stage: SHC, when: as_applicable}]
  RESTORATION:
    label: EoA after a break / restoration of intake / hibernation
    stages: [SCRUTINY, EVC, {stage: SHC, when: as_applicable}]
  SUPERNUMERARY_SEATS:
    label: Supernumerary seats (foreign nationals / OCI / children of Indian workers in Gulf)
    stages: [SCRUTINY]
  INCREASE_INTAKE:
    label: Increase in intake / additional course(s)
    stages: [SCRUTINY, EVC, {stage: SHC, when: as_applicable}]
  INTEGRATED_DUAL:
    label: Integrated / dual degree course
    stages: [SCRUTINY, EVC, {stage: SHC, when: as_applicable}]
  FELLOW_PROGRAMME:
    label: Fellow Programme in Management
    stages: [SCRUTINY, EVC, {stage: SHC, when: as_applicable}]
  COURSE_CHANGE_REDUCTION:
    label: Change of course name / merger of courses / reduction in intake
    stages: [SCRUTINY]
  COLLABORATION_TWINNING:
    label: Collaboration and twinning programme
    stages: [SCRUTINY, EVC, {stage: SHC, when: as_applicable}]
  CHANGE_OF_SITE:
    label: Change of site / location
    stages: [SCRUTINY, EVC, {stage: SHC, when: as_applicable}]
  CLOSURE_INSTITUTION:
    label: Closure of the institution
    stages: [SCRUTINY]
  CONVERSION_COED:
    label: Conversion women's to co-ed institution or vice versa
    stages: [SCRUTINY]
  CLOSURE_PROGRAMME:
    label: Closure of programme(s) / course(s)
    stages: [SCRUTINY]
  BANK_DETAILS:
    label: Change in bank details
    stages: [SCRUTINY]
  TRUST_NAME:
    label: Change of name of trust / society / company
    stages: [SCRUTINY]
  DEEMED_UNIVERSITY:
    label: Conversion into a deemed-to-be university
    stages: [SCRUTINY, EVC, {stage: SHC, when: as_applicable}]
  ODL:
    label: Online Learning / ODL courses
    stages: [SCRUTINY, EVC, {stage: SHC, when: as_applicable}]
  # Chapter I route (sections 1.3-1.12), not part of Table 2.3
  NEW_INSTITUTION:
    label: Setting up a new institution
    stages: [SCRUTINY, EVC, {stage: SHC, when: as_applicable}, EC, COUNCIL]

appeal:
  trigger: decision.adverse_uploaded
  window: APPEAL_7D
  max_appeals: 1

# Timers below are INTERNAL processing timers; legal deadlines are never paused.
transitions:
  - {from: SCRUTINY, action: record_deficiency, to: DEFICIENT,
     roles: [SCRUTINY_COMMITTEE], require: [reason, items],
     timers: {pause: AICTE_PROCESSING, start: INSTITUTION_RESPONSE}}
  - {from: DEFICIENT, action: submit_compliance, to: RESCRUTINY,
     roles: [INSTITUTION],
     timers: {stop: INSTITUTION_RESPONSE, resume: AICTE_PROCESSING}}
  - {from: [SCRUTINY, RESCRUTINY], action: complete, to: next_stage,
     guard: "open_items == 0"}
  - {from: "*", action: authorised_revert, to: "$target", roles: [BUREAU_OFFICER],
     require: [reason, second_approver_if: target_is_terminal]}
```

Real excerpt 2: complete current overlay:

Source: `rulesets/aph-2024-27/r3-DEMO/overlay.yaml`

```yaml
# Used ONLY in the rule-change simulation scenario. Refused outside demo mode.
extends: aph-2024-27@r1
revision: r3-DEMO
status: unverified_demo
# unverified: secondary source only
effective_from: 2025-12-02
banner: "SIMULATION - models a reported corrigendum that has NOT been verified"
roles:
  evc_constituted_by: COUNCIL
```

Overlay keys: extends (base key), revision (string), status (string), effective_from (unquoted YAML date), banner (string), roles (mapping). `_load` reads extends/status/banner/roles; derives revision from requested folder key and ignores the file's revision and effective_from. It reuses the base routes, deadline_rules and clocks_on_submit and shallow-merges roles. It refuses status `unverified_demo` outside demo mode, rather than universally refusing every possible overlay or every r3 folder by name. There are no overlay deadline overrides or transition overrides today. No effective-date enforcement exists.

## 4. Exact shared contracts

The following verbatim source snapshots preserve annotations, argument order, fields, defaults and enum values. All 12 types in `types.py` are frozen dataclasses, not Pydantic models. The UnitOfWork Protocol has two attributes and no command methods. All Protocols are runtime-checkable.

Source: `contracts/ports.py`

```python
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
```

Source: `contracts/types.py`

```python
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
```

Source: `contracts/enums.py`

```python
"""Shared vocabularies. Every module uses these values; nobody invents their own copies."""
from enum import StrEnum


class Role(StrEnum):
    INSTITUTION = "INSTITUTION"
    SCRUTINY_COMMITTEE = "SCRUTINY_COMMITTEE"
    RO_OFFICER = "RO_OFFICER"
    BUREAU_OFFICER = "BUREAU_OFFICER"
    BUREAU_HEAD = "BUREAU_HEAD"
    AUDITOR = "AUDITOR"
    SYSTEM = "SYSTEM"


class Stage(StrEnum):
    SELF_DISCLOSURE = "SELF_DISCLOSURE"
    SCRUTINY = "SCRUTINY"
    RESCRUTINY = "RESCRUTINY"
    DEFICIENT = "DEFICIENT"
    EVC = "EVC"
    SHC = "SHC"
    EC = "EC"
    COUNCIL = "COUNCIL"


class ApplicationStatus(StrEnum):
    DRAFT = "DRAFT"
    IN_PROCESS = "IN_PROCESS"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class ClockKind(StrEnum):
    LEGAL = "LEGAL"        # set by the handbook or a letter; never paused by workflow actions
    INTERNAL = "INTERNAL"  # processing timer; may pause while the other side holds the case


class ClockOwner(StrEnum):
    AICTE = "AICTE"
    INSTITUTION = "INSTITUTION"
    COMMITTEE = "COMMITTEE"


class DeadlineStatus(StrEnum):
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    MET = "MET"
    BREACHED = "BREACHED"
    WAIVED = "WAIVED"
    EXTENDED = "EXTENDED"


class FactState(StrEnum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    CORRECTED = "CORRECTED"
    REJECTED = "REJECTED"


class ObligationKind(StrEnum):
    UNDERTAKING = "UNDERTAKING"
    AFFIDAVIT = "AFFIDAVIT"
    LETTER_CONDITION = "LETTER_CONDITION"
    DEPOSIT = "DEPOSIT"
    DOCUMENT_VALIDITY = "DOCUMENT_VALIDITY"
    RECURRING_FILING = "RECURRING_FILING"


class LetterType(StrEnum):
    LOA = "LOA"
    EOA = "EOA"
    LOD = "LOD"
    LOR = "LOR"
    CORRIGENDUM = "CORRIGENDUM"


# Every event_type starts with one of these prefixes, e.g. "wf.application_submitted".
MODULE_PREFIXES = frozenset({"wf", "evc", "doc", "cmp", "dl", "plat"})
```

Source: `contracts/errors.py`

```python
"""Errors any module may raise; the API layer maps them to HTTP status codes."""


class ContractError(Exception):
    status_code = 400


class ValidationFailed(ContractError):
    status_code = 422


class NotFound(ContractError):
    status_code = 404


class Forbidden(ContractError):
    status_code = 403


class Conflict(ContractError):
    status_code = 409
```

There is NO reason-code enum or defined reason-code value set in enums.py. `EventIn.reason_code` is an unrestricted optional string, stored as Text by platform. `ApplicationStatus` and `DeadlineStatus` are separate vocabularies; Stage.DEFICIENT is a stage rather than an ApplicationStatus value. MODULE_PREFIXES is a frozenset, not an enum; it excludes `an` despite the analytics schema existing in ownership plans.

`contracts/fakes.py` supplies FakeClock, FakeLedger, FakeNotes, FakePersonalData, FakeOutbox, AllowAllAuthz, FakeRulesets, FakeCases, FakeDeadlineRuleParser, FakeDeadlines, FakeCompliance. FakeDeadlines records only method/subject/rule tuples; FakeCompliance collects LetterIn objects and returns UUIDs; neither proves real persistence or transaction rollback. FakeRulesets returns the same test ruleset regardless of requested key. Fake notes/personal/deadlines/compliance use uuid4. `scripts/check_contracts.py` checks structural fake compatibility, event schema constraints, and exact OpenAPI serialization, not full behavior.

## 5. Discovery and port lookup

`backend/app/main.py:module_names()` discovers packages with `pkgutil.iter_modules(app_pkg.__path__)`; platform sorts first, then remaining names alphabetically. `load_models()` imports each optional models module, registering SQLAlchemy classes on `app.platform.db.Base.metadata`. `create_app()` loads models, calls every optional `wiring.wire()`, then includes each optional `api.router` at `/api`. Only an absent exact optional module is ignored; an internal missing import is re-raised. Module import ends with `app = create_app()`.

Actual wiring order: platform, analytics (none), compliance (none), deadlines, documents (none), evc (none), intake, workflow. Platform's five implementations are LedgerPort→Ledger, NotesPort→Notes, PersonalDataPort→PersonalStore, OutboxPort→OutboxWriter, AuthzPort→Authz. Deadlines registers ClockPort→SystemClock, DeadlineRuleParserPort→RuleParser, DeadlinePort→DeadlineEngine. Intake registers CasePort→Cases, workflow registers RulesetPort→RulesetRegistry. **CompliancePort has a fake but no real registration**.

`backend/app/platform/registry.py` maintains a process-global `_impls` dictionary keyed by Protocol type. `provide(type, impl)` checks `isinstance(impl, type)` then assigns/replaces the value; `port(type)` returns it or raises RuntimeError `No implementation wired for <name>`. Runtime Protocol checks verify member presence, not semantic correctness or all signature details. Recreating the app rewires the same global registry. Wiring is lazy for ruleset loading, so its parser exists before first get().

## 6. Auth and transactions today

`backend/app/platform/auth.py:current_principal` parses X-Demo-User (UUID), X-Demo-Role (Role), optional X-Demo-Institution (UUID), X-Demo-Region (string). User and role are required; institution-role callers also need the institution header. Missing required identity gives 401; malformed typed headers get FastAPI validation errors. When DEMO_AUTH=false, every protected request gets 401 `identity provider not configured`; no Keycloak integration is present. Headers are caller-supplied identity, suitable only for the demo. Demo switches default true in settings and compose.

Authz POLICY allows all roles institution.list/ruleset.read/application.read/deadline.read/case.timeline/sim.clock; application.create/submit only INSTITUTION; ledger.verify only AUDITOR/BUREAU_OFFICER/BUREAU_HEAD. Unknown actions and role/object failures raise Forbidden 403. For institution callers, resource.owner_institution_id is checked. Region, stage and committee assignment are not checked; X-Demo-Region is retained but not enforced. GET health is public. No Idempotency-Key middleware exists.

Shortest real P1 command wrapper (`backend/app/intake/api.py`), copied verbatim:

```python
def submit(application_id: UUID, principal: Principal = Depends(current_principal)):
    with unit_of_work(principal) as uow:
        return _out(service.submit_application(uow, application_id))
```

`backend/app/platform/db.py:unit_of_work` opens a session, yields UnitOfWork(session, principal), commits after return, rolls back on BaseException, and always closes. The wrapper's return expression is evaluated inside the context, but context exit commits before the HTTP return completes.

`intake/service.py:submit_application` row-locks application; rejects missing rows; checks authorization; requires DRAFT; obtains default ruleset and category route; reads ClockPort; sets IN_PROCESS, pinned key, route snapshot, first stage, submitted_at; adds StageVisit; appends wf.application_submitted; opens YAML clocks synchronously in the same uow. `DeadlineEngine.open` appends dl.deadline_opened through P3. There is no mandatory async work. The step01 rollback test injects a failing DeadlinePort and asserts the draft and prior event survive unchanged. Note that lookup/NotFound precedes authz in submit; create_application checks authz first.

## 7. Gap list against Work Pack section 1.1 and section 2

DONE means the stated narrow starter capability exists in source, with test execution separately recorded in section 8. PARTIAL means some required subfeatures exist. NOT STARTED means no executable implementation found; YAML prose, shared types, fakes, README plans and planned tables do not count as implementation.

| Reference requirement | Status | Evidence and remaining gap |
|---|---|---|
| 1.1 Intake: institution/application/submission | PARTIAL | intake/models.py and service.py implement institution, application, submission operation and timestamps; no submission model/history table. |
| Category Annexure-2 checklist, DSC flag, mandatory-item submit guard | NOT STARTED | No such fields/models/guards in intake; submit checks only existence, authorization and DRAFT. |
| Route plan returned on submit | DONE | submit_application stores route objects; ApplicationOut exposes route; step01 asserts stages. |
| Route clause citation in submission output | NOT STARTED | Global YAML source exists, but Route/RouteOut/ApplicationOut omit citation. |
| Registry loading/version keys/pinning | DONE | RulesetRegistry and submit_application pin aph-2024-27@r1; no later mutation path exists. |
| Static ruleset validation | PARTIAL | parse_routes validates stages/conditions/presence, validates submit clock IDs; transitions/appeal metadata and full YAML shape are not validated. |
| New-ruleset approval workflow | NOT STARTED | No persisted approval records or /admin/rulesets APIs. |
| r3-DEMO overlay and refusal | DONE | Registry roles merge/banner/status gate and test_overlay_changes_roles_but_not_routes/test_unverified_overlay_is_refused_outside_demo_mode. |
| Rule-change impact replay (Tier 2) | NOT STARTED | No replay runner, diffs or projection comparison; overlay alone is not replay. |
| All 21 Table 2.3 routes plus NEW_INSTITUTION | DONE | routes.yaml contains 22 keys; test count/selected rows/SHC invariant; legal fidelity to unavailable Final Report not independently verified. |
| SHC as_applicable exactly where EVC appears | DONE | Every relevant YAML row uses the conditional object; test_shc_is_optional_exactly_where_evc_is_required checks it. |
| State machine: route_def, ruleset, transition, stage_visit | PARTIAL | Only stage_visit persisted; rulesets/routes in files and memory; four transitions declared but not loaded/executed. |
| Guards, reasoned reverts, invalid-transition rejection | PARTIAL | Initial DRAFT submit guard and repeat-submit rejection exist; general guard evaluator, authorised_revert, target validation and reason codes absent. |
| Deficiency/items/open-only Re-Scrutiny/response traceability | NOT STARTED | No models, commands, schemas, action API or tests. |
| Committee/task/observation/member-attributed append-only reports | NOT STARTED | No models or services in workflow. |
| EVC evc_request/expert/availability/coi/slot/assignment | NOT STARTED | evc/README.md only; no EVC models/migrations/queue. |
| Authorised-selector stand-in; dates-only CP-SAT; EDF; explanations; propose/publish | NOT STARTED | EVC README plans; no solver dependency, scheduler, routes or tests. |
| Letter issuance trigger calling P2 register_letter for LoA/EoA/LoD | NOT STARTED | LetterIn/CompliancePort/FakeCompliance exist; P1 has no issuer and real CompliancePort is unwired. |
| AICTE/NSWS SIMULATED adapters and inbound dedup | NOT STARTED | No adapter/inbound_event implementation; P3 idempotency storage also absent. |
| Synthetic case generator | PARTIAL | seed_demo.py seeds three labelled institutions, but no applications or case scenarios. |
| ~300 institutions / 9 ROs / ~600 applications / Table 2.3 mix / 5 seeds | NOT STARTED | Seed is three institutions in three named regions, with no configurable seeds or application generation. |
| Planted deficiency loops/late responses/EVC delays and answer key | NOT STARTED | No generator scenarios or answer-key schema/output; reference Day 0 marks schema open. |
| Tier 2 BPMN route-version views / cited optional local-LLM summaries | NOT STARTED | No implementation or artifact. |
| Operaton two-day decision spike | NOT STARTED | No spike code or decision write-up. |
| Section 2 starter submit clocks driven by YAML | DONE | RuleSet.clocks_on_submit consumed by submit; no hardcoded timer ID in intake. |
| Section 2 starter create/submit one transaction | DONE | unit_of_work wrapper plus step01 rollback test source. |
| Section 2 starter read APIs and three DEMO institutions | DONE | intake/api.py, workflow/api.py, seed_demo.py. |
| Section 2 tests all routes/corrected rows/static validation/overlay refusal | PARTIAL | Existing ruleset tests cover count/invariants and selected exact sequences; no independent expected-stage table for every category. All 31 existing tests pass in the isolated Linux environment; the broader coverage gaps remain. |
| Section 2 next step 1: YAML state machine, record_deficiency/submit_compliance with pause/resume | NOT STARTED | YAML and P2 DeadlineEngine methods exist; no P1 dispatcher/call sites. |
| Section 2 next step 2: deficiency loop with items | NOT STARTED | No deficiency model or command. |
| Section 2 next step 3: committee backend | NOT STARTED | No committee/task/observation/report implementation. |
| Section 2 next step 4: EVC queue | NOT STARTED | No EVC router/service/models. |
| Section 2 next step 5: scale generator and answer key | NOT STARTED | Seed-only generator; no answer key. |

Dependency boundaries: P2 must coordinate deadline mutation events, EVC clocks/rules and real letter registration. P3 must supply idempotency and stronger policy enforcement; answer-key schema is a shared P1/P3 decision with P2 fields. New event schemas and API snapshots require the AGENTS.md contract-request procedure and explicit authorization. These are future dependencies, not reasons to change other owners' files during this audit.

## 8. Commands and observed results

Initial attempts: all three requested commands were run from repository root with the current `python` (`C:\Python314\python.exe`, Python 3.14). PYTHONDONTWRITEBYTECODE=1 was set for these checks to avoid generating bytecode. These initial attempts preceded isolated dependency installation. Tests were not modified.

| Command | Exit | Actual result |
|---|---|---|
| `python -m pytest` | 1 | `No module named pytest`; no collection/execution occurred. |
| `python scripts/check_contracts.py` | 1 | Import contracts.ports failed: `ModuleNotFoundError: No module named 'sqlalchemy'`; no completed contract validation. |
| `python scripts/check_migration_heads.py` | 1 | Import alembic.config failed: `ModuleNotFoundError: No module named 'alembic'`; no migration-head validation. |

### Final verification: PASS (24 October 2026)

After the user required the 31-test baseline to pass, Docker Desktop was started. It initially reported a WSL disk-attachment timeout, then recovered. Dependencies from `backend/requirements-dev.txt` were installed into an isolated temporary Windows Python 3.12 environment outside this repository. That environment returned `contracts ok`, but the Windows migration check misleadingly returned `checked 0 migration chains` (exit 0). This did not count as successful migration verification: the checkout path contains spaces and `backend/alembic.ini` uses `version_path_separator = space`, splitting paths incorrectly.

The authoritative final run used Linux `python:3.12-slim` and a dedicated `postgres:16-alpine` container, matching CI's Python/PostgreSQL major versions. Repository source was mounted **read-only** at `/repo`, avoiding Windows path splitting. The test runner installed the unchanged declared development requirements into its disposable container. `DATABASE_URL` targeted only `sih_p1_audit_test` inside the dedicated PostgreSQL container; no application database was used. The suite's database recreation, migrations, fixture truncation and writes executed only there.

Environment: `PYTHONDONTWRITEBYTECODE=1`, `DEMO_MODE=true`, `DEMO_AUTH=true`. Pytest's cache provider was disabled solely to preserve the read-only repository constraint; no tests were skipped, filtered, rewritten or replaced. The exact command sequence after installing dependencies was:

```sh
python -m pytest -p no:cacheprovider
python scripts/check_contracts.py
python scripts/check_migration_heads.py
```

| Final command | Exit | Observed output |
|---|---|---|
| `python -m pytest -p no:cacheprovider` | 0 | `31 passed, 1 warning in 43.02s` |
| `python scripts/check_contracts.py` | 0 | `contracts ok` |
| `python scripts/check_migration_heads.py` | 0 | `checked 3 migration chains` |

The one warning is a Starlette TestClient dependency deprecation: `anyio.abc.BlockingPortal` is deprecated in favor of `anyio.from_thread.BlockingPortal`. It did not fail a test. This run verifies the existing 31 cases, OpenAPI snapshot comparison, contracts, and the three actual migration chains. It does not certify missing future features or a deployed Docker/UI flow. The temporary test runner removes itself; the dedicated PostgreSQL container and its anonymous volume are removed after recording results. No source changes were needed.

## 9. Inconsistencies and risks (observed vs inferred)

1. **Route count is consistent when scoped correctly:** 21 Table 2.3 rows plus Chapter I NEW_INSTITUTION = 22 YAML entries. Work Pack week 1's shorthand "all 21" is ambiguous, not evidence of an extra erroneous route. No live official APH verification was requested or performed.
2. **Plans resemble inventory:** OWNERSHIP lists EVC/doc/cmp/an tables, architecture names a state machine and scheduling, but these are unimplemented packages/plans. Only wf's three tables, dl.deadline, and plat's five tables are modeled/migrated. No actual evc schema-creation revision exists.
3. **YAML transitions are dead configuration:** routes.yaml declares guards/timers/reverts/appeals, but RuleSet and loader omit them; callers cannot access these through the contract today. This is a contract design dependency, not permission to alter contracts.
4. **Validation weaker than documentation:** parser docstring says SHC is optional exactly with EVC; implementation enforces presence parity only. An `always` SHC with EVC passes parsing (current YAML and tests still assert as_applicable). No comprehensive transition/schema/order validation.
5. **Submission requirements missing:** no DSC/checklist/mandatory-document blocker or submission table. No citation returned despite reference's cited route requirement.
6. **Ledger gaps in existing P2 mutations:** DeadlineEngine.close/pause_internal/resume_internal update rows without LedgerPort.append. Only open emits an event. No close/pause/resume schemas exist. Resume updates due_at/due_date/due_version but leaves stored explanation unchanged; inferred risk of stale explanations. Coordinate with P2 rather than compensating by editing their module.
7. **Reason codes absent:** no enum despite the reference discussing shared vocabularies/reason codes; EventIn accepts arbitrary reason_code string. No general invalid-transition errors exist to prove 100% rejection.
8. **Authz-first rule mismatch:** submit reads/locks and may return NotFound before authz.check; object reads likewise load before checking. This can expose existence distinctions; no writes occur before its authorization check. Region/stage/assignment scope is absent.
9. **Demo-only security:** arbitrary identity headers, true-by-default demo flags, and no production identity provider. DEMO_AUTH=false is fail-closed 401. No Idempotency-Key middleware; repeat submit is a 409, not replay-safe idempotency. ORM/fakes use uuid4, so deterministic replay needs deliberate design.
10. **Clock wording/CI mismatch:** AGENTS bans datetime.now anywhere, while `backend/app/deadlines/clock.py:14` uses datetime.now(timezone.utc) inside the designated clock source. CI currently has no grep step enforcing that ban. This requires clarification of the clock-provider exception, not replacement of time calls in this audit.
11. **Ruleset metadata and provenance:** r1 status is verified_text but comment says demo until authorized review; registry drops source, and API omits it. Unknown legal values cannot be certified from this checkout; Final Report and official source snapshots are missing. P2 APPEAL_7D uses verified status while comment says calendar-vs-working is unconfirmed; avoid presenting that choice as verified law.
12. **Overlay limits:** effective_from/revision metadata ignored, gate is status-based, no approval/publishing flow, routes/deadlines share base mutable dictionaries despite frozen dataclass wrappers. Pinning protects key selection but not external edits to the same revision file; no content hash/immutability enforcement or explicit loaded-overlay pinning regression test.
13. **Protocol/API mismatch:** list_rulesets calls available() not declared on RulesetPort; FakeRulesets lacks it. Real registry works, alternate conforming ports may fail this endpoint.
14. **Compliance integration missing:** FakeCompliance does not imply actual registration; calling port(CompliancePort) currently raises RuntimeError. Letter trigger cannot complete until P2 provides a real implementation.
15. **Contract CI approval claim is stronger than implementation:** contracts-approval counts any two non-author approving users; it does not restrict to the named team accounts or bind approvals to current commit SHA. Whether branch protection prevents bypass cannot be determined from local files. CODEOWNERS lists all three globally, not per-folder owners.
16. **Reference branch typo:** Work Pack section 8 example says git switch person-2 even for P1. Follow AGENTS and user's person-1 instruction. TEAM_WORKFLOW sync example is also person-2; this audit made no branch change.
17. **Deadline and scale limitations:** computed lease rule cannot be opened by generic DeadlineEngine.open; working_days raises a missing-calendar error; timers/alerts/escalation are not executable from YAML extra fields. Scale answer-key agreement remains open; no evidence of COI/conflict-free schedules or EDF comparison.
18. **Ledger verification boundary:** current hash-chain verification lacks independent signed checkpoints; removal of the tail and recomputation cannot be proven detectable against an independent trusted head by this implementation alone. Existing deletion test deletes the first entry, not the tail.
19. **Windows migration-check false green:** an isolated Windows Python 3.12 run returned exit 0 with `checked 0 migration chains`, because space-separated version locations split the checkout path. Final Linux verification returned `checked 3 migration chains` and passed the schema/model comparison as part of all 31 tests. No configuration was fixed. Browser behavior, deployed services, and current GitHub CI status were not inspected.

## 10. Supporting current-source appendices

OpenAPI was parsed in full as JSON. Current snapshot operations follow; the initial live generation comparison was blocked by missing dependencies, but the final Linux `contracts ok` result confirms it matches the generated API schema at this commit.

```text
GET /api/applications
POST /api/applications
GET /api/applications/{application_id}
POST /api/applications/{application_id}/submit
GET /api/cases/{application_id}/timeline
GET /api/deadlines
GET /api/deadlines/{deadline_id}/explain
GET /api/health
GET /api/institutions
GET /api/ledger/verify
GET /api/rulesets
GET /api/rulesets/{key}
GET /api/sim/clock
POST /api/sim/clock
```

Snapshot title: Approval Workflow, OCR & Compliance; version 0.1.0. Component schemas: AdvanceIn, ApplicationIn, ApplicationOut, ClockOut, DeadlineOut, HTTPValidationError, InstitutionOut, Role, RouteOut, RulesetOut, StageOut, TimelineEvent, ValidationError, VerifyOut.

P1 acceptance gaps: exact independently expected stages for all routes; generalized invalid actions/reason codes; r1 pin remaining unchanged after overlay load; open-item-only Re-Scrutiny; scheduler hard constraints and EDF comparison. Existing tests provide only the narrower evidence catalogued above.

Scope completion: one file added, all 31 tests pass, both contract and migration checks pass in Linux, no endpoints/events/tables/tests created, no new business/legal assumptions introduced, and no P2/P3 code modified. Findings requiring coordination are recorded above. Repository status is checked after writing to verify the one-file constraint.
