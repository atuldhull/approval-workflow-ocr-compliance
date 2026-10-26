# W1 events end to end — 26 October 2026

Branch: `person-1`. Audited code: `ad6306a`. Scope: the API submission → pinned route → P2 deadline → P3 ledger → timeline checkpoint. This is a backend integration checkpoint, not a claim that every Week 1 deliverable, production security, the browser UI, or later demo steps are complete. Historical plans/audit describe their dated snapshots; the observations below describe current code.

## Verification results

**W1 checkpoint: PASS with real P2/P3 implementations.** All requested checks completed successfully:

| Command (run from the isolated repository root) | Result |
|---|---|
| `python -m pytest -p no:cacheprovider --tb=short --junitxml=/tmp/w1-full.xml` | **6,012 passed**, one existing Starlette/AnyIO deprecation warning, 380.92 seconds |
| `python scripts/check_contracts.py` | Exit 0, `contracts ok`; no `--write` needed |
| `python scripts/check_migration_heads.py` | Exit 0, `checked 3 migration chains` |
| `python -m alembic -c backend/alembic.ini heads` | Exactly `plat_0001 (platform)`, `wf_0003 (workflow)`, `dl_0001 (deadlines)`, one head each |

No tests were filtered, skipped or modified. The cache-provider flag disables only pytest's cache. All 175 original source-file hashes still matched both checkout and test copy after execution; only this new report is added to Git. No lint repair was needed.

Fresh API-only probe: **PASS**, no fake ports and no injected guard facts. It used a separate disposable `w1_probe` database and the normal app/startup plus demo seed. Request results: draft create 201; submit with a missing mandatory item 422 / MANDATORY_ITEMS_MISSING; item update 200; valid submit 200; deadlines 200; own timeline 200; foreign-institution timeline 403; ledger verify 200 / `ok=true`, `checked=4`. Fictional application ID: `905aa499-211a-4aa3-bfc0-e399970d8a3d`. Persisted evidence:

| seq | event_type | event_version |
|---|---|---|
| 1 | wf.application_created | 1 |
| 2 | wf.application_item_updated | 1 |
| 3 | wf.application_submitted | 2 |
| 4 | dl.deadline_opened | 1 |

The real deadline's `anchor_event_seq=3` points to the submitted event. Its provider-supplied `anchor_at=2026-10-26T06:32:07.336298Z` yields `due_date=2026-11-25`; returned state is RUNNING. Timeline subject/deadline IDs match the submitted application and returned clock. The probe issued create/items/submit/read requests through FastAPI TestClient, not direct fixture insertion of application items; only test-database provisioning and fictional institution seeding used the standard fixtures. It was an ephemeral verification script, not a new committed test or a browser/deployed-service check.

Checks run in Python 3.12/Linux and disposable PostgreSQL 16. The suite recreates only its dedicated test database. An isolated copy of all 175 source files was hash-compared with the checkout before testing, avoiding Windows shared-folder overhead and Alembic's space-separated-path issue. Source changes in this task are confined to this status document; there is no OpenAPI regeneration, production fix, new endpoint/event/table or new committed test.

## What works

1. `POST /api/applications` creates an institution-owned draft. `POST /api/applications/{id}/items` records coded checklist items and opaque document references. `POST /api/applications/{id}/submit` with `dsc_present=true` validates mandatory items, picks the category route and pins `aph-2024-27@r1`. A missing item or DSC yields coded 422, not a successful submission. `POST /api/applications` also supports atomic create + items + submit with `submit=true`.
2. Submit returns `route_id`, ordered `stages[]` including SHC's `as_applicable`, `ruleset_key`, YAML/cache-backed `clause_citation` and `assumptions[]`. `NEW_PROGRAMME` resolves to SCRUTINY → EVC → conditional SHC. All 21 Table 2.3 representations plus Chapter I NEW_INSTITUTION are present; current acceptance evidence covers 22 routes and pin preservation.
3. Intake reads `clocks.on_submit` through RulesetPort and synchronously calls the real P2 `DeadlineEngine.open` with the submission instant and ledger sequence anchor. `GET /api/deadlines?subject_id={id}` exposes one RUNNING `AICTE_PROCESSING`, INTERNAL, AICTE-owned clock. Its 30-calendar-day duration and end-of-day IST convention are existing DEMO ASSUMPTIONS, not independently verified APH law.
4. The real P3 `Ledger.append` schema-validates and persists events/hash-chain rows in the same unit of work. The legacy submit path records `wf.application_submitted` **version 2**, followed by `dl.deadline_opened` version 1. Version is separate from `event_type`; neither timeline token includes a `.v2` suffix.
5. `GET /api/cases/{id}/timeline` returns sequence-ordered application and attached-deadline events. With items written through the API, the order is `wf.application_created`, one `wf.application_item_updated` per changed item, `wf.application_submitted`, `dl.deadline_opened`. P3's `GET /api/ledger/verify` verifies the chain. Other institutions receive 403 for this timeline.
6. Existing `tests/e2e/step01_submit_test.py::test_submission_routes_opens_clock_and_records_everything` proves the route, real clock/due date, timeline and ledger. Its prerequisite helper inserts fictional item rows directly, so that test intentionally has no item-update event. Its rollback companion replaces DeadlinePort with a failure adapter and proves draft/ledger preservation. Existing case-action integration tests exercise real HTTP/auth/deadlines/ledger through submit → deficiency → compliance → advance, with fictional trusted guard facts.

The alternate `POST /api/cases/{id}/actions` submit path opens the clock before appending `wf.application_submitted` and `wf.stage_entered`, as required by the engine's timer-before-ledger order. Both paths are tested; consumers must use sequence and event identity rather than assume the legacy ordering for every command. Legacy intake submit has no `case_state` until the first successful case action adopts its existing pin/visit without replaying its clock/events. GET is read-only.

## Real ports and explicit stubs

The fresh W1 happy path uses **no fake ports and no injected guard facts**. Startup wiring is:

| Port | Runtime implementation | W1 usage |
|---|---|---|
| AuthzPort | `app.platform.auth.Authz` | Real policy with demo identity headers |
| CasePort | `app.intake.service.Cases` | Real owner/region lookup |
| RulesetPort | `app.workflow.registry.RulesetRegistry` | Real YAML validation/route selection |
| DeadlineRuleParserPort | `app.deadlines.rules.RuleParser` | Real P2 parser |
| ClockPort | `app.deadlines.clock.SystemClock` | Real provider, resettable demo offset; not FakeClock |
| DeadlinePort | `app.deadlines.service.DeadlineEngine` | Real persisted clock |
| LedgerPort | `app.platform.ledger.Ledger` | Real event/hash-chain persistence and verification |
| NotesPort | `app.platform.records.Notes` | Registered, not needed for this submit |
| PersonalDataPort | `app.platform.records.PersonalStore` | Registered, not exercised by submit |
| OutboxPort | `app.platform.records.OutboxWriter` | Registered, no delivery claim |
| CompliancePort | **No production registration** | Not called by W1; letter issuance defaults off |

Broader test results must not be mistaken for an all-real later workflow:

| Fake port / adapter actually used by behavioral tests | Where / limitation |
|---|---|
| DeadlinePort → test-local `FailingDeadlines` | step01 rollback test only; raises Conflict on open, never the happy-path clock |
| ClockPort → `FakeClock` (and `NoClockRead` tripwire) | persistence/engine transaction tests; explicit logical time or proof that loader makes no time read |
| DeadlineRuleParserPort → `FakeDeadlineRuleParser` | ruleset/grammar/core/checklist-validation/engine fixture setup and acceptance raw-YAML oracle; not the fresh W1 runtime parser |
| AuthzPort → `AllowAllAuthz` / denial adapter | pure action-list and transactional engine tests; case HTTP/acceptance/W1 tests retain real Authz |
| CasePort → `FakeCases` | isolated engine transaction fixture; in-memory case references |
| DeadlinePort → `TxDeadlines(FakeDeadlines)` | isolated engine transaction fixture; journaled test state and injected LEGAL refusal, not P2 persistence |
| LedgerPort → `TxLedger(FakeLedger)` | isolated engine transaction fixture; schema checks/journaled memory, optionally delegates to real Ledger for selected rollback tests |
| NotesPort → `TxNotes(FakeNotes)` | isolated engine transaction fixture; journaled in-memory protected notes |
| CompliancePort → `TxCompliance(FakeCompliance)` | isolated engine transaction fixture; journaled in-memory letters |
| CompliancePort → `FakeCompliance` | route acceptance terminal runs only; test flag enables letters, no real P2 letter/obligation integration |

`scripts/check_contracts.py` additionally instantiates all eleven shared fake implementations for structural protocol checks: FakeClock, FakeLedger, FakeNotes, FakePersonalData, FakeOutbox, AllowAllAuthz, FakeRulesets, FakeCases, FakeDeadlineRuleParser, FakeDeadlines and FakeCompliance. This checks conformance, not production registration or behavior. `FakeRulesets`, `FakePersonalData` and `FakeOutbox` are not used for the W1 submission.

Other explicit simulation boundaries: X-Demo-* supplies caller-declared identity, not Keycloak/Cerbos login; seeded institutions/doc UUIDs are fictional; DSC is a presence boolean, not signature verification; PROVIDED is not document validation; full Annexure-2 content remains unknown. Later engine tests inject assignment/open-item/response/reason/decision/SHC/live-clock facts through `_fact_loader`; those missing production providers fail closed. The answer-key schema is a team-review proposal with empty P2/P3 extensions, not a running scale generator/scorecard. No new business/legal assumption is introduced by this verification.

## Exact ownership audit

Current task: **only `docs/p1/week1_status.md` changes**. No outside-owned file is changed now.

Historical feature baseline: `git diff --name-only 6349b0d..ad6306a` (after the requested root-agent bootstrap, before P1 implementation). Treat tests for P1 modules/fixtures as P1-owned per AGENTS, regardless of their shared `backend/tests/` location. The complete list outside explicitly listed P1 areas is **nine files**, not just generated OpenAPI and event schemas:

| File | Evidence / disposition |
|---|---|
| `contracts/openapi.json` | Generated API snapshot, authorized regeneration in `665aeca` and `730356b` |
| `contracts/events/wf/transition_applied.v1.json` | Authorized wf schema, `04cbdd3` |
| `contracts/events/wf/stage_entered.v1.json` | Authorized wf schema, `04cbdd3` |
| `contracts/events/wf/stage_exited.v1.json` | Authorized wf schema, `04cbdd3` |
| `contracts/events/wf/application_submitted.v2.json` | Authorized versioned schema, v1 retained, `730356b` |
| `contracts/events/wf/application_item_updated.v1.json` | Explicit additional-schema approval/request, `730356b` |
| `backend/app/platform/auth.py` | **P3 exception:** user-approved narrow case-action policy and RO-region checks, `665aeca`; 19 added lines |
| `backend/tests/test_ledger.py` | **P3 exception:** user-approved `submit_one` fixture-only prerequisites update, `730356b`; ledger/tamper assertions unchanged |
| `rulesets/aph-2024-27/r1/checklists.yaml` | Explicitly requested in task 1.5, `730356b`; belongs to P1 intake requirements but is not in AGENTS' literal file allowlist; confirm ownership entry with team |

For completeness, expanding the baseline to original scaffold `5ff5049` also includes these six setup/reference paths outside the literal P1 allowlist: `.gitattributes` (`d87e479`, line-ending setup), `AGENTS.md` (`6349b0d`, expressly requested root rules), `docs/reference/SIH26262_Team_Split.pdf`, `docs/reference/SIH26262_Team_Split.txt`, `docs/reference/SIH26262_Person1_Work_Pack.pdf`, `docs/reference/SIH26262_Person1_Work_Pack.txt` (`453ca0c`, expressly requested reference import). These are historical setup changes, not hidden feature edits. This inventory describes Git history, not proof of team-wide approval beyond recorded user authorizations. Shared ports/types/enums/fakes, P2 runtime/deadline YAML, frontend, scripts, CI and Compose are unchanged over the feature baseline.

## Open questions and follow-ups — no fixes in this task

**P2**

- Agree authoritative same-unit-of-work live-clock inspection for conditional terminal closes: approved port or published read-only view? Existing proposal remains unapproved; P1 must not read/write `dl` internals.
- Add/agree deadline close/pause/resume event schemas and emission. Today only open emits a `dl.*` event; resume changes due date/version without refreshing the stored explanation. W1 open works, but full clock mutation audit is incomplete.
- Supply real CompliancePort registration and letter/obligation behavior before enabling letters; agree verified Annexure-2 lists, document checks, DSC semantics and official citations/durations. P1 must not invent them.
- Provide calendars/working-day support and later alert/escalation behavior; define P2 answer-key extensions and scorecard expectations with P3.

**P3**

- Confirm acceptance of the two explicitly approved P3-file exceptions above, including action-role policy/RO checks; decide production identity/policy integration. Legacy intake list/detail do not enforce RO region like the new case APIs do; audit that scope before production use.
- Implement Idempotency-Key middleware/replay semantics; the header is currently documented/reserved, and stale expected versions return 409. Agree projection handling for both submit event orders, application_submitted v2 and attached-deadline timeline matching.
- Supply independent signed ledger checkpoints and replay/scorecard/notifier integrations. Passing local hash-chain verification is not independent tail-deletion or rehash protection, nor proof of notification delivery.
- Resolve Windows Alembic path splitting (Linux checks see three chains; the historical Windows check saw zero), the existing Starlette/AnyIO deprecation warning, and whether the designated ClockPort provider is exempt from AGENTS' literal datetime.now ban. Current sole match is `backend/app/deadlines/clock.py:14`; no P1 wall-clock call is introduced.

**P1 / team**

- Supply production guard-fact backends for deficiency items/responses, committee assignment, coded reasons, decisions/second approval and optional SHC; later successful fake-backed transitions do not establish these integrations. Deficiency/committee/EVC persistence and scale generation remain follow-ups.
- Obtain the original APH/Final Report: all 22 expected-route CSV rows remain PRIMARY_SOURCE_UNAVAILABLE, citations explicitly UNCONFIRMED, checklists DEMO ASSUMPTION. Tests establish current configured behavior, not legal fidelity.
- Approve/activate rulesets through a real lifecycle API and settle immutable-source rollout. Existing cached r1 checksums reject the prior task's requested source changes; this verification uses a fresh disposable demo database and does not reset or rewrite a user database.
- Confirm checklist ownership and reconcile historical audit/wireframe statements with implemented APIs when revising those documents; they are dated designs, not today's availability list. `RulesetPort.available()` remains a concrete-method/Protocol mismatch on the list endpoint.

No trivial lint edit was necessary. All substantive findings are follow-ups; no other owner's code, dependency, schema or configuration is repaired here.
