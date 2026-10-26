# P1 generator / answer-key verification report

Date: 26 October 2026. Branch: person-1. Generator version 1.0.0; proposed answer-key schema 0.1.0; pinned aph-2024-27@r1. All data is fictional DEMO and scenario time is SIMULATED.

## Method

Executed the standalone `python -m generator.cases.verify_answer_key --seed N --out <temporary-directory>` CLI for seeds 1–5 with default 300 institutions / 600 applications / 9 synthetic ROs. Each run uses a separate disposable PostgreSQL 16 database, already migrated through all three existing chains, and Python 3.12 with the repository's pinned development dependencies. No caller database was reset by the CLI.

The CLI generates immutable seed_data.json and answer_key.json, bootstraps only wf.institution, creates/submits/reviews/transitions cases through the real FastAPI API and engine, observes the real DeadlinePort, reads routes/timelines/deficiencies through APIs and verifies the real ledger chain. The logical clock and explicitly trusted DEMO assignment/SHC facts are the simulation adapters. No fake auth/deadline/ledger/compliance implementation is installed.

receipt.json maps deterministic scenario IDs to API-generated runtime IDs. observations.json contains observed API responses and successful real clock-port calls; verification.json contains status and every mismatch path with expected/actual values. A partial/failed replay exits ERROR, never PASS. Process-local clock observations prove the calls made during these successful replays; they are not a substitute for P2's missing production pause/resume/close ledger events.

## Coverage and exclusions

Each seed exercises all 22 categories with the documented equal-weight DEMO mix, exact YAML route plans, selected optional SHC stages, 0–3 deficiency rounds, rejected-round carry-forward, late responses, EVC stage holds and terminal REJECTED/WITHDRAWN outcomes. The comparator checks ordered visited stages, final status/stage/pin, round IDs/times/closure/items/response references, exact ordered clock operations and opening dates/times, plus observed letter triggers.

Both reserved extensions remain empty `{}` and valid under the unchanged JSON Schema/Pydantic models. P2/P3 metrics are NOT_SUPPLIED. EVC delays are simulated stage holds, not scheduler records. Letter expectations are zero because issuance remains blocked by the existing LetterIn/ruleset_rev contract request; each result must say NO_POSITIVE_COVERAGE. Zero unexpected letter triggers does not prove positive issuance or approval-letter obligations. No new legal/APH assertion is made; SCALE-001..003 and VERIFY-001..002 document the assumptions.

The verifier's independent oracle and negative tests deliberately alter route plans, stages, pins, rounds, item response/state/times, clock count/order/time, letters, replay completion and ledger verification. Positive letter field comparison is unit-tested using explicit observations, not claimed as an end-to-end issued-letter test. The standalone CLI smoke test also proves duplicate-seed refusal and checks real persisted results in a dedicated test database.

## Measured full-size results

All five standalone CLI processes exited **0**, with **0 mismatches**, and the real ledger verification passed in every database. Each checked 600 application routes/outcomes. Deficiency item count equals round count in this generator. Letters expected/observed were 0/0 for each seed, explicitly NO_POSITIVE_COVERAGE.

| Seed | Institutions | ROs | Applications | Deficiency rounds | Late responses | EVC holds | Clock operations | Mismatches | Result |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | 300 | 9 | 600 | 788 | 393 | 326 | 4352 | 0 | PASS |
| 2 | 300 | 9 | 600 | 854 | 429 | 326 | 4616 | 0 | PASS |
| 3 | 300 | 9 | 600 | 830 | 427 | 326 | 4520 | 0 | PASS |
| 4 | 300 | 9 | 600 | 762 | 382 | 326 | 4248 | 0 | PASS |
| 5 | 300 | 9 | 600 | 827 | 405 | 326 | 4508 | 0 | PASS |

Totals: **3000 applications, 4061 deficiency rounds, 22244 observed clock operations, zero mismatches**. Both extensions were empty and valid in every generated key. Independently ran Draft202012Validator with UUID/date/date-time format checks (explicit date-time checker) and AnswerKey.model_validate against all five actual CLI artifacts; all passed. The checked-in schema/models remain unchanged.

SHA-256 of each canonical generated answer_key.json, to identify the exact inputs independently of runtime UUIDs:

| Seed | SHA-256 |
|---|---|
| 1 | c28c3e9e64009e1e56e7a6fca352d1fec1faef34006f45d08faf7f4aa08e6abb |
| 2 | eae5308089ecaac7ab5359659eb2238a05f758921c6921a3639b1559ed696e6f |
| 3 | 2a941429a8fbd72c6b2d31ec78585ca563eb842db10fd14492925d49521ea3c0 |
| 4 | 6cd18365bb58ce01adadd6b5f66b2b2bff7f2980be18f49a41f1e272aa99ab25 |
| 5 | a476608d3512b14dc730a9618962e330fea9237262123c4fd16032fe36bdddab |

The large generated inputs/observations/runtime receipts are disposable validation artifacts, not checked-in datasets. RUN.md documents how to reproduce them.

## Regression and repository checks

- Focused verifier tests: **27 passed**, including the standalone 22-application CLI replay and duplicate-seed refusal.
- Full `python -m pytest -p no:cacheprovider --tb=short --junitxml=/tmp/verifier-regression.xml`: **6089 passed**, zero failures/errors/skips, 1 existing Starlette/AnyIO deprecation warning, **2757.19 seconds**. The five full CLI runs ran concurrently with this suite in separate databases. This includes all 6062 pre-existing cases and 27 new cases.
- `python scripts/check_contracts.py`: **contracts ok**; no API or OpenAPI changes.
- `python scripts/check_migration_heads.py`: **checked 3 migration chains**. Alembic heads: plat_0001 (platform), wf_0006 (workflow), dl_0001 (deadlines), exactly one per module.
- All **146** code/config/schema files in the test copy match the source by SHA-256. `git diff --check` passes. New verifier code has no wall-clock calls.

Changed files: generator/cases/verification.py, verification_runtime.py, verify_answer_key.py, scale_loader.py; tests/test_verify_answer_key.py, tests/acceptance/test_verifier_cli.py; docs/p1/RUN.md, generator_report.md, plans/2.6_answer_key_verifier.md, answer_key_schema.md and ASSUMPTIONS.md. No new endpoints, events, tables, migrations, shared contracts, dependencies or external-owner files. Follow-ups remain positive letter issuance/contract approval, production clock observability and P2/P3 extensions/scoring.
