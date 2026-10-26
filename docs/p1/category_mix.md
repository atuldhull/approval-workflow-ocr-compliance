# DEMO category mix and scale-generator use

**DEMO ASSUMPTION SCALE-001:** Table 2.3 lists routes, not application frequencies. No frequency or institution/RO taxonomy is asserted to be APH-derived. All 21 Table 2.3 categories plus NEW_INSTITUTION have equal weight 1 (probability 1/22). The default allocation uses Hamilton/largest-remainder rounding: 27 per category, one extra for the first six alphabetically. Seeded shuffling assigns these counts to institutions; changing the seed changes identities, assignments and events, not the quota. Tolerance is strictly less than one application from the ideal quota, rather than a statistical sampling tolerance.

| Category | Weight | Applications at 600 |
|---|---:|---:|
| BANK_DETAILS | 1 | 28 |
| CHANGE_OF_NAME | 1 | 28 |
| CHANGE_OF_SITE | 1 | 28 |
| CLOSURE_INSTITUTION | 1 | 28 |
| CLOSURE_PROGRAMME | 1 | 28 |
| COLLABORATION_TWINNING | 1 | 28 |
| CONVERSION_COED | 1 | 27 |
| CONVERSION_LEVEL | 1 | 27 |
| COURSE_CHANGE_REDUCTION | 1 | 27 |
| DEEMED_UNIVERSITY | 1 | 27 |
| EOA_SELF_DISCLOSURE | 1 | 27 |
| FELLOW_PROGRAMME | 1 | 27 |
| INCREASE_INTAKE | 1 | 27 |
| INTEGRATED_DUAL | 1 | 27 |
| MERGER | 1 | 27 |
| NEW_INSTITUTION | 1 | 27 |
| NEW_PROGRAMME | 1 | 27 |
| NRI_SEATS | 1 | 27 |
| ODL | 1 | 27 |
| RESTORATION | 1 | 27 |
| SUPERNUMERARY_SEATS | 1 | 27 |
| TRUST_NAME | 1 | 27 |

## Generate files

From the repository root with backend requirements installed:

```powershell
python -m generator.cases.scale_generator --seed 1 --out demo-output/seed-1
1..5 | ForEach-Object { python -m generator.cases.scale_generator --seed $_ --out "demo-output/seed-$_" }
```

Optional flags: `--institutions 300 --applications 600 --regions 9`. Sizes must be positive integers, seed nonnegative; 1 <= regions <= min(institutions, 9). Each output directory receives `seed_data.json` and `answer_key.json`; existing files are refused. Outputs are disposable artifacts, not checked-in datasets. JSON has sorted keys, fixed indentation, UTF-8 and LF; repeated generation with the same options/version/sources is byte-identical. UUID5 names include DEMO and seed; UUID spelling cannot contain a DEMO prefix, so each entity has a DEMO label. Names and RO/region codes explicitly include DEMO. Regions/institutions are assigned round-robin, ensuring all requested ROs exist.

## Replay through the API

`generator.cases.scale_loader.load_seed(data, answer, client, clock, bootstrap_institutions=..., configure_scenario=...)` is the load adapter. `client` can be a real FastAPI TestClient or a compatible HTTP client pointing to a demo server. It creates applications with YAML-derived mandatory checklist items, submits via `/api/cases/{id}/actions`, records deficiencies, submits per-item responses, reviews through `/api/cases/{id}/deficiencies/{round}/review`, advances and terminates through the real API/engine. It checks final status and the route against the answer key. It never inserts applications, case states, deficiency items, deadlines or ledger rows itself.

There is no institution-create endpoint. The explicit `seed_demo.seed_scale_institutions` callback extends P1's existing master-data bootstrap and writes **only wf.institution** in demo mode. Its names/labels/regions are validated; repeated master-data bootstrap is harmless. No direct SQL is performed against another owner's schema. The whole multi-command scenario is not one transaction: each API command retains its normal atomic unit of work. A failed replay requires a fresh disposable database; P3 idempotency middleware is not implemented by this loader.

The demo server must use the **same LogicalClock instance** as the replay, registered through ClockPort. LogicalClock implements `now()` and explicit monotonic movement. The loader does not change production wiring or invoke P2's wall-clock-offset endpoint. A remote server needs an owner-approved logical-clock transport before this adapter can drive its times. The integration test demonstrates the in-process real FastAPI server. It uses trusted demo assignment/applicability facts (has_assignment and selected optional SHC); these missing committee-assignment integrations are not inferred from untrusted HTTP payloads or shipped as production policy. All other guards, authorization, deadlines and ledger use real implementations.

To run the full working integration example against a disposable test database configured with DATABASE_URL, DEMO_MODE=true and DEMO_AUTH=true:

```powershell
python -m pytest 'tests/acceptance/test_scale_loading.py::test_seed_one_full_scale_matches_key_through_real_api[600]'
```

The repository's test database fixture recreates its configured test database. Use a dedicated test database as for the rest of this project's integration suite. The example bootstraps institutions, wires the logical clock/trusted DEMO facts, replays seed 1, and verifies every final state, route history, item response, opening due date, timer call and the full ledger chain.

Applications have deterministic **scenario IDs**; existing APIs assign their own runtime UUIDs. The receipt maps application/round/response identities to runtime identifiers. Do not compare database UUIDs across runs or silently rewrite the answer key. The answer key stays immutable and P3 joins via the receipt. Runtime ledger IDs/hashes are not promised byte-identical.

## Planted events and limits

**DEMO ASSUMPTION SCALE-002:** An isolated local `random.Random(seed)` chooses 0–3 rounds for routes with SCRUTINY, 2-day or 17-day responses, optional SHC applicability and 1–4-day EVC holds. There are no deficiency rounds on SELF_DISCLOSURE-only routes. Earlier rounds reject and carry forward the one controlled DEMO_CORE_REFERENCE item; the final round accepts it. The snapshot key marks earlier rejected items OPEN, with their response references and review-time snapshot; final items are RESOLVED. This is not a claim that superseded database rounds remain OPEN. Review creates the next rejected round and advances on final acceptance through existing YAML.

The logical clock starts at 2026-07-01T04:30:00Z, with one-second command ordering. Applications replay sequentially on a single global logical timeline; long runs may span many logical years, not a real academic-year forecast. Academic year 2027-28 is a fixed DEMO token. Deadline rules/durations come from the pinned YAML. For its currently supported calendar-day clocks, due instants follow P2's existing IST end-of-day convention. Late responses are measured against that actual due instant, not blindly against 15*86400 seconds. Clock expectations include exact open/pause/resume/close order and times; P2 currently emits opening events but does not emit ledger events for every pause/resume/close. Those missing observability events are a P2/P3 follow-up, not silently treated as passing scorecard metrics.

**DEMO ASSUMPTION SCALE-003:** Scenarios visit their full selected plan, then choose REJECTED or WITHDRAWN; terminal API stage is null and status carries the outcome. Each key includes the complete YAML stage list plus actual visited stages including deficiency loops. Letter issuance remains contract-blocked, so letters_to_issue is empty; this generator does not claim approval/letter or six-month obligation coverage. EVC delays represent simulated stage holds with stable DEMO demand references; no real EVC scheduling/request API exists yet. Do not treat these references as existing evc rows.

The answer-key proposal remains version 0.1.0 / PROPOSED_TEAM_REVIEW; this task authorizes P1 generator use, not P2/P3 adoption. Both reserved extensions remain empty and their metrics NOT_SUPPLIED. P2 supplies OCR/alert data, P3 supplies tamper targets and scorecard matching. No shared contracts are changed.
