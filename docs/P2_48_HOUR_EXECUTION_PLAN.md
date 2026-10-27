# Person 2 — 48-hour execution plan

**Repository:** `approval-workflow-ocr-compliance`<br>
**Owner:** Person 2<br>
**Planning basis:** inspection of the current `person-2` worktree on 2026-10-24.
**Status:** working plan; legal rules, holiday calendars, reminder schedules, and escalation policies remain configurable until confirmed by an authoritative source and the team.

## Current inventory

| Responsibility | Current status | Evidence / next step |
| --- | --- | --- |
| Deadline rules and date arithmetic | Partially implemented; pure tests pass | `backend/app/deadlines/rules.py` parses rules, supports calendar-day/month-clamp arithmetic, and converts anchors to Indian dates. Complete edge cases and database-backed `DeadlineEngine.open` coverage. |
| Working-day calendars | Partially implemented; pure tests pass | The worktree has `WorkingCalendar`, DB models, and `dl_0002_calendar_versions`. No approved real calendar data or calendar-management API exists. Keep unapproved calendars out of production configuration. |
| Legal/internal clock behavior | Partially implemented | `DeadlineEngine` prevents pausing legal clocks and extends internal due time on resume. Add transaction-backed tests and define expiry/catch-up behavior. `SystemClock` is wired as the shared `ClockPort`; demo time travel is explicitly demo-only. The demo offset is stored in `dl.sim_clock` (migration `dl_0006_sim_clock`, one row) and re-read at most once a second, so the API and a separate timer worker agree; outside demo mode it is never read. |
| Timer worker / restart recovery | Implemented; PostgreSQL tests pass | `python -m app.deadlines.worker [--once]` (`backend/app/deadlines/worker.py`) claims due rows from `dl.deadline.next_fire_at` with `FOR UPDATE SKIP LOCKED`, a lease and a fence (`timer_fence`), processes each deadline in one transaction, catches up after downtime and records one `dl.timer_outcome` per claim. Migration `dl_0005_timer_alerts`. Time comes only from `ClockPort`. Runs in compose as `deadline-worker` (profile `worker`, `--poll-seconds 10`). |
| Alerts, acknowledgements, escalation | Implemented against current platform code; event schemas await three-way approval | `dl.alert` is unique on `(deadline_id, level, due_version)`; alert row, `dl.alert_*` events and outbox rows share one unit of work. Ladder, offsets, owner roles and channels are in `deadlines.yaml` under `alerts` (demo assumption). Recipients are role groups (`RecipientDirectory.resolve`); `has_members() == False` is an explicit vacancy, any directory exception is an outage and is retried. `GET /api/alerts`, `POST /api/alerts/{id}/ack`; both return the deadline's `rule_id`, `due_date`, `deadline_status` and the case `application_id`. Application, obligation and approval-letter deadlines are scoped. Uses `RecipientDirectory` directly until `RecipientPort` (C2) is approved. |
| Lease stop-academic-year calculation | Implemented as a pure function; boundary is a configurable demo assumption | `lease_eoa_stop_year(lease_end_date, max_course_duration_years, AcademicYearStart)` in `rules.py`; `academic_year.starts` (`07-01`, demo assumption) in `deadlines.yaml`. Not yet attached to an intake field (lease dates are not captured). Confirm the academic-year start and the reading of "equals" with the team. |
| Approval letters, obligations, evidence verification | Missing | `backend/app/compliance/` contains only a README; no models, API, service, migration, or module tests. Shared `CompliancePort.register_letter` and `LetterIn` exist, but field requiredness and `f_no`/`fr_no` need team resolution. |
| Document upload, versioning, OCR, fact confirmation | Implemented; PostgreSQL tests pass; OCR accuracy not measured | Upload, ClamAV scan, extraction, type-before-reveal review and four-eyes confirmation over HTTP (`backend/app/documents/README.md`). Default text engine `text_engine.py`: pypdf for PDF text layers, Tesseract CLI (`eng`+`hin`, installed in the backend image) for scans; Tesseract missing means a FAILED, retryable run (`ADAPTER_UNAVAILABLE`). Confidence is uncalibrated; every value stays PROPOSED until reviewed. Do not create deadlines from proposed/unconfirmed OCR facts. |
| API integration | Implemented for the demo path | Deadline listing/explanation, demo clock and timer run, alerts and ack, compliance letters/obligations/evidence/notes, and document upload/scan/extract/review/confirm/content endpoints exist (module READMEs). No calendar admin API. No document checklist endpoint: the ruleset does not publish a checklist yet. |
| Database migrations | Partial | Platform, workflow, and deadline base migrations exist; the current worktree adds the deadline calendar migration. No document/compliance migrations exist. Check all Alembic heads and metadata parity when PostgreSQL is available. |
| Shared-contract integration | Blocked pending approval | `contracts/` is jointly owned. P1 case context exposes application/institution/region, but not committee/stage. P3's outbox accepts a UUID recipient reference but currently only stores it; no role resolver or delivery consumer is implemented. |
| Tests / integration | Partially tested; full baseline blocked | `python -m pytest -q backend/tests/test_deadline_rules.py backend/tests/test_rulesets.py` passed **22 tests**. The DB-backed suite could not complete: its fixture needs PostgreSQL and drops/recreates its configured test database; Docker is stopped and `localhost:5432` is unreachable. Do not point it at a database with user data. |

### Preserve as working foundations

- Keep the existing modular FastAPI/SQLAlchemy layout, per-owner migration chains, `UnitOfWork`, `ClockPort`, `LedgerPort`, and event/outbox transaction boundary.
- Keep source status and rule revision visible in deadline explanations. Preserve the configurable demo assumptions in `rulesets/aph-2024-27/r1/deadlines.yaml`; do not turn them into legal defaults.
- Keep working calendars versioned and sourced. A working-day rule must fail closed when its exact version or anchor-day convention is missing.
- Keep OCR facts proposed until a human confirms or corrects them. Only an accepted fact state may supply a deadline anchor.
- Keep proposal event schemas under `docs/proposals/`; no schema is approved for activation by this plan.

## Work sequence

Time is measured from the team’s agreed start (`T+0`). If a dependency is unavailable, use the time for independent P2 work and record the blocker rather than inventing an interface or policy.

### P0 — End-to-end demo essentials

| Window / task | Files and dependencies | Implementation steps | Acceptance tests |
| --- | --- | --- | --- |
| **T+0–4h: finish deadline arithmetic** | `backend/app/deadlines/rules.py`; `backend/tests/test_deadline_rules.py`; depends on no external service | Cover leap years, month-end clamping, timezone date boundaries, invalid duration types/units, and explicit working-day counting. Keep unsupported legal interpretations configurable. | Unit tests cover month ends, leap dates, IST rollover, invalid inputs, and working-day anchor inclusion/exclusion. |
| **T+4–8h: finish calendar persistence** | `backend/app/deadlines/calendars.py`, `models.py`, `service.py`, `backend/migrations/versions/deadlines/dl_0002_calendar_versions.py`, `calendars/README.md`; PostgreSQL required for integration | Verify migration/model parity; test loading an exact calendar version and skipping configured holidays; make calendar immutability/version behavior explicit. Add no real holidays without an approved source. | Migration applies cleanly; metadata matches; working-day deadline uses the pinned calendar version; unknown version fails without writing a deadline or event. |
| **T+8–12h: harden clock semantics** | `backend/app/deadlines/service.py`, `clock.py`, `api.py`, `backend/tests/test_deadline_service.py`; PostgreSQL needed for transaction tests | Cover legal clock pause rejection, internal pause/resume, repeated calls, date/version updates, and injected clock use. Confirm time travel cannot be enabled outside demo mode. | Tests prove legal due dates do not move; internal held time is applied once; resume increments `due_version`; rollback preserves both deadline and event state. |
| **T+12–20h: timer catch-up and restart recovery** | P2-owned `backend/app/deadlines/` worker and model/migration files; depends on approved timer claim/idempotency approach and `ClockPort` | Add a bounded worker entry point that queries due rows from persisted state (no in-memory-only schedule), claims work transactionally, handles process restart, and exposes health/operational logging without personal data. Do not infer reminder schedules from demo comments. | A due timer survives worker restart; repeated/overlapping worker runs do not create duplicate timer outcomes; future timers are untouched; outages leave work retryable. |
| **T+20–28h: alerts and escalation** | P2 deadline alert files/migration/API/tests; depends on team review of proposal schemas, P1 resource context, and P3 resolver/outbox contract | First agree typed outcomes for resolved target, explicit vacancy, invalid/unauthorized scope, resolver outage, and delivery failure. Then persist alert uniqueness on `(deadline_id, level, due_version)`, write alert/event/outbox in one UOW, add acknowledgement, and advance only on explicit vacancy per configured ladder. Keep roles in events and individual contacts in P3-owned private delivery state. | Concurrent duplicate attempts create one alert; vacancy advances to the next configured role; outage/unauthorized scope aborts or retries without being treated as vacancy; ack stops further escalation; delivery retry does not create another domain alert; replay never sends messages. |
| **T+28–32h: lease stop-year calculation** | `backend/app/deadlines/rules.py`, ruleset config, `backend/tests/test_deadline_rules.py`; requires confirmed `ay_start_rule` | Implement a pure function with explicit academic-year boundary and input validation. If the boundary remains unconfirmed, keep the rule disabled and report the decision needed. | Tests cover lease end on/before/after boundary, leap day, course duration, and the configured academic-year start rule. |

### P1 — Core compliance and document/OCR functionality

| Window / task | Files and dependencies | Implementation steps | Acceptance tests |
| --- | --- | --- | --- |
| **T+32–38h: approval letters and obligations** | `backend/app/compliance/{models,service,api,wiring}.py`; new `backend/migrations/versions/compliance/`; compliance tests; P1 `CompliancePort` caller; team approval of `LetterIn` naming/requiredness | Add Person 2-owned letter/obligation tables and service. Validate source/provenance, owner reference, due date, and officer confirmation. Create conditional obligations only from accepted letter facts. Do not change `contracts/` or activate proposal schemas without all three approvals. | Registration persists traceable letter metadata; invalid/missing required source blocks creation; only confirmed officer conditions trigger the configured EOA obligation; caller transaction rollback removes row and event together. |
| **T+38–41h: evidence and human verification** | Compliance service/API/models/migration/tests; depends on document-version reference contract and agreed reason-code vocabulary | Add evidence submission by immutable document-version ID and human ACCEPTED/REJECTED verification. Reject arbitrary reason codes; keep explanatory text in the approved note store. | Valid evidence links to one obligation; invalid references fail; accepted/rejected decisions are auditable; rejected decisions require a stable approved reason code; non-human actors cannot verify. |
| **T+41–45h: document versioning and fact confirmation** | `backend/app/documents/`; new documents migration; content-store boundary; P3 UI integration | Add upload metadata, immutable versions, hash/size/media validation, OCR-run state, fact state transitions, and a confirmation endpoint. Keep binaries outside event payloads and follow P3 storage/scan interfaces. | Duplicate content behavior is deterministic; corrupted/unsupported files are rejected or quarantined; proposed facts cannot anchor deadlines; only CONFIRMED/CORRECTED facts can be used. |
| **T+45–47h: OCR normalization** | Document module, OCR adapter/configuration, focused OCR fixtures | Add a replaceable OCR adapter, script routing, numeral/date normalization, and confidence handling. Do not bundle or claim a model license that has not been approved; uncertain handwriting/date results go to human review. | Indic/Latin routing is deterministic; normalization tests cover supported numerals/date forms; low-confidence and ambiguous values remain proposed; OCR failure is visible and retryable. |

### P2 — Safe follow-ups after the demo path

| Task | Files / dependencies | Acceptance criteria |
| --- | --- | --- |
| Production OCR model and malware-scanning integration | document module and approved model/scanner deployment; model/license review | Reproducible OCR evaluation set with measured language/date accuracy; malicious files never enter the document store. |
| Calendar administration and source import | calendar API/UI, P3 admin flow, approved regional/holiday sources | Every active calendar version has an immutable source reference and change history; no silent default calendar. |
| Delivery reconciliation and operations UI | P3 delivery ledger/worker and P2 alert status view | Operators can distinguish pending, delivered, retrying, failed, vacant, and acknowledged states without exposing contact data to P2. |
| Broader projection/replay and retention tooling | P3 replay harness and team data-retention decision | Rebuilds are side-effect-free; retention/deletion behavior is documented and tested across linked records. |

## Cross-person blockers and decisions

1. **Letter number:** approve `f_no` → `fr_no` or document a compatibility mapping; also decide whether `document_version_id` may be absent and how optional `LetterIn` values serialize into required event keys.
2. **Role recipient resolution:** P3 must define the role-and-scope resolver, explicit vacancy versus retryable resolver outage, and how `recipient_ref` denotes an opaque role group. P1 must supply trusted institution/region and any stage/committee context required for authorization.
3. **Schema review:** Persons 1, 2, and 3 must review privacy, retention, event replay, outbox retries, role-group membership changes, and vocabulary before copying draft schemas into `contracts/events/`.
4. **Legal configuration:** confirm legal day-count conventions, holiday sources, reminder schedules, escalation levels, RO vacancy fallback, lease academic-year boundary, and penalty calculations. Until then, keep these values configurable and label demo assumptions.
5. **Database availability:** provide PostgreSQL for migration/integration checks. The shared test fixture destroys and recreates only the database named by `DATABASE_URL`; use a dedicated disposable test database, never a development or production database.

## Completion gates

- [ ] P0 date, clock, calendar, timer, and alert tests pass; unresolved alert dependencies are recorded rather than bypassed.
- [ ] P1 compliance, evidence, document, and OCR interfaces are tested with human confirmation gates.
- [ ] All Person 2 migrations apply; Alembic heads and SQLAlchemy metadata agree.
- [ ] Full test suite passes against a dedicated disposable PostgreSQL test database; record the exact command and result.
- [ ] API smoke test and end-to-end demo procedure are documented.
- [ ] No shared contract or active proposal schema was changed without the required approvals.
- [ ] Report completed/incomplete features, exact run/test commands, and remaining P1/P3/team blockers before any commit or push.

## Execution log

### 2026-10-24 — deadline arithmetic hardening

- Added validation for non-object rules/durations, unsupported month-end policies, non-positive month counts, invalid direct `Duration` values, unsupported units, and naive datetimes.
- Tightened calendar ID, source-status, weekday arithmetic, and rules-document validation so malformed configuration becomes a domain validation error instead of an unhandled type error.
- Changed end-of-day deadlines to the final representable instant of the configured Indian calendar date, including microseconds.
- Hardened internal-clock pause/resume against naive clock values, missing pause timestamps, and a clock moving backwards; rejected operations leave the deadline unchanged.
- Added regression tests for these cases.
- Added isolated tests for loading a pinned calendar version and failing closed when a configured version is missing.
- **Verification:** `python -m pytest -q backend/tests/test_deadline_rules.py backend/tests/test_deadline_calendars.py backend/tests/test_deadline_service.py backend/tests/test_rulesets.py` — **40 passed**. `python scripts/check_migration_heads.py` — **3 migration chains checked**. `git diff --check` — clean.
- **Shared-contract check:** `python scripts/check_contracts.py` reports that `contracts/openapi.json` is stale. That file is jointly owned and is unchanged in this worktree, so it was left untouched pending the required all-three approval.
- **Still blocked:** PostgreSQL-backed migration/model/API/transaction tests. Docker Desktop is not running and `localhost:5432` is not reachable. The shared test fixture drops and recreates the database named by `DATABASE_URL`; rerun only with a dedicated disposable test database.
- **Interface review:** created `docs/proposals/person-2-week-2-event-schemas/CODEX_COMPATIBILITY_AUDIT.md` and clarified the draft interface mapping in `INTERFACE_RESOLUTION.md`. Resolver outage, vacancy, authorization, delivery retry, `document_version_id` requiredness, and three-person approval remain blockers; no active shared contract or event schema was changed.

### 2026-10-27 — timer worker, alerts and lease stop year

- **Timer worker:** `backend/app/deadlines/worker.py`. Claim query mirrors the platform notifier (lease + fence); a claim whose fence moved on records nothing. Outcomes: `SCHEDULED`, `ALERTED`, `ACKNOWLEDGED`, `LADDER_DONE`, `NOT_RUNNING`, `RETRY` (directory outage or processing error, after `alerts.retry_after_minutes`), `FAILED` (`SCOPE_UNRESOLVED` or `ATTEMPTS_EXHAUSTED`). `DeadlineEngine.open` schedules the first level; `resume_internal` restarts the ladder for the new `due_version`; `close` clears the schedule.
- **Escalation rule:** a level is raised when `due_at + offset` passes. The next level follows when its own offset passes without an acknowledgement (`WINDOW_ELAPSED`), or at once when the addressed group has no members (`VACANCY`, nothing queued for the vacant level). An outage never counts as a vacancy. Only the addressed role may acknowledge; an acknowledgement stops further levels for that `due_version`.
- **Catch-up choice:** after downtime every missed level is raised in one pass (each with its own event). An alternative is to raise only the highest due level; this needs a team decision.
- **Scope:** alerts carry the subject's institution and region for list scoping: from `CasePort` for `application` subjects, from the compliance row for `obligation` and `approval_letter` subjects (added 2026-10-27, see below). Any other subject type, or a subject that cannot be found, stops with `FAILED / SCOPE_UNRESOLVED` rather than guess a recipient.
- **Events:** `dl.alert_raised`, `dl.alert_escalated`, `dl.alert_acknowledged` v1 in `contracts/events/dl/`, copied to `docs/proposals/alert-events/` for the required three-way approval. Replay projector `alerts` rebuilds alert status read-only.
- **Policy:** new `alert` resource kind (region-scoped, committee assignment-scoped); `alert.read` and `alert.ack`; Cerbos policies regenerated.
- **Lease stop year:** the first blocked academic year is the one containing the last day from which a full course of the longest duration still fits in the lease (end date inclusive; a 29 February start rolls to 1 March).
- **Shared contracts:** `contracts/openapi.json` is stale (new endpoints) and was not regenerated, pending approval.

### 2026-10-27 — text engine, timer worker in compose, shared demo clock

- **Text engine:** `backend/app/documents/text_engine.py`, selected by `DOCUMENT_TEXT_ENGINE` (`local` default, `none` restores the 503). PDF text layers via pypdf page by page (confidence 1, not an OCR estimate); images and pages without a text layer via `tesseract stdin stdout -l eng+hin tsv`, languages limited to what `--list-langs` reports. Tesseract missing: run FAILED with `ADAPTER_UNAVAILABLE`, retryable. Candidates, Indic-digit and date normalisation unchanged. Tests use a synthetic text-layer PDF and a faked Tesseract CLI (found and missing); Tesseract itself is not installed on the dev host, so recognition quality is untested.
- **Compose:** `deadline-worker` service (profile `worker`), `python -m app.deadlines.worker --poll-seconds 10`.
- **Demo clock:** `dl.sim_clock` (single row, `id = 1`), written by `advance`/`reset` with an upsert, read by `SystemClock` with a 1 s cache. Non-demo mode ignores any stored row. Migration down/up tested.
- **Shared contracts:** unchanged; `contracts/openapi.json` still stale pending approval.

### 2026-10-27 — gaps found by the UI build

- **Viewing a document:** `GET /api/document-versions/{id}/content` serves the stored file of an `AVAILABLE` (scanned clean) version to anyone with `document.facts.read` on it (same scoping as facts). Quarantined and rejected versions: 409 `DocumentNotViewable`. Bytes are re-checked against size, sha256 and signature (409 `StoredContentMismatch`). Headers: stored media type, inline `Content-Disposition` with `filename*=UTF-8''...`, `nosniff`, `private, no-store`, `default-src 'none'; sandbox`. No page-image endpoint.
- **Version status:** every version view carries `status` (`QUARANTINED`/`AVAILABLE`/`REJECTED`) beside `scan_status`; the facts listing adds `version_status` and `scan_status`.
- **Reload mid-review:** facts in an officer's listing carry `my_entry` (own blind entry, `entered_at`, `suggestion_revealed`, `revealed_at`) for the caller only. `entered_by`/`reviewed_by`/`confirmed_by` are `{role, is_you, who}`; **breaking change** for the UI: `reviewed_by` and `confirmed_by` were user ids and are now these objects (use `is_you`). Migration `doc_0005_fact_actor_roles` stores the roles; a trigger keeps them fixed.
- **Evidence notes:** `GET /api/compliance/evidence/{id}/note` for officers with `compliance.evidence.verify` on the obligation and the owning institution; auditors 403 (they see `has_note`). Read from the platform note store by `note_ref` and checked against `note_hash`, because `NotesPort` has no read method; a `NotesPort.read` contract change would replace that.
- **Alerts traceable:** alert responses add `rule_id`, `due_date`, `deadline_status`, `application_id`. Obligation and letter deadlines used to stop with `SCOPE_UNRESOLVED`, so an overdue obligation never alerted; they are now scoped from their compliance rows.
- **Demo letters:** `python -m app.compliance.demo_seed` (DEMO_MODE only, idempotent) registers three DEMO LoAs dated from `ClockPort.now()`: two with obligations due in the future, one five days overdue that the timer worker escalates. The rules are unchanged.
- **Checklist:** not built. No ruleset on this branch has checklist data (`rulesets/aph-2024-27/r1` has only `deadlines.yaml` and `routes.yaml`), so there is nothing to serve without inventing items; the UI keeps its own list in `recordText.js`. Needs a checklist file owned by the ruleset loader (Person 1) first.
- **Policy:** unchanged; every new endpoint uses an existing action. Cerbos not regenerated.
- **Shared contracts:** unchanged; `contracts/openapi.json` stale pending approval.

## Current end-to-end demo procedure

This exercises the implemented baseline workflow. For compliance obligations and their alerts, run `docker compose exec backend python -m app.compliance.demo_seed` after the stack is up (demo mode only): it adds three DEMO letters, one of them overdue, then run the timers as below. To see alerts, after step 3 call `POST /api/sim/clock` with `{"days": 29}`, then either wait for the `deadline-worker` (`docker compose --profile worker up`; the offset is shared through `dl.sim_clock`, so it sees time travel within about a second plus its poll interval) or call `POST /api/sim/timers/run`, and open `GET /api/alerts` as the Southern regional officer.

1. From the repository root, start the stack with `docker compose up --build` and wait for PostgreSQL health. Open the UI at `http://localhost:5173` or API docs at `http://localhost:8000/docs`.
2. In the UI, act as the seeded demo institution and create an application with a supported category and academic year.
3. Submit the application. Confirm it routes through the configured workflow and starts the configured internal processing deadline.
4. Open the deadline explanation and check its ruleset revision, source status, due date, and clock owner.
5. As an auditor, call the ledger verification endpoint and confirm the event chain verifies.

For automated checks, install `backend/requirements-dev.txt` if needed and run the focused command below. The full `python -m pytest -q` suite needs PostgreSQL and will recreate the database named in `DATABASE_URL`; use a dedicated disposable test database.

```powershell
python -m pytest -q backend/tests/test_deadline_rules.py backend/tests/test_deadline_calendars.py backend/tests/test_deadline_service.py backend/tests/test_rulesets.py
python -m pytest -q
```
