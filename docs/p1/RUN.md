# P1 generator and answer-key verification

Use branch person-1 and the installed backend development requirements. The verifier is an explicit **DEMO / SIMULATED harness**, not production server wiring. No scripts/ or Makefile changes are needed.

## One-command replay and verification

Set DATABASE_URL to a dedicated, migrated PostgreSQL database whose name ends in `_verify`, and explicitly set DEMO_MODE=true and DEMO_AUTH=true. Do not use an application/deployment database. Provision a fresh disposable database through your normal local setup, then apply existing migrations with `python -m alembic -c backend/alembic.ini upgrade heads`. The verifier itself never creates, drops, resets or truncates a database.

```powershell
$env:DATABASE_URL = 'postgresql+psycopg://awoc:awoc@localhost:5432/p1_seed1_verify'
$env:DEMO_MODE = 'true'
$env:DEMO_AUTH = 'true'
python -m generator.cases.verify_answer_key --seed 1
```

The last line is the one-command target: generate immutable seed data/key, bootstrap P1 institutions, replay all applications through the real API/engine, collect observations and compare them. Defaults are 300 institutions, 600 applications, 9 synthetic ROs. Optional `--institutions`, `--applications`, `--regions` permit smaller smoke tests. `--out <new-directory>` chooses an artifact folder; the default is `sih26262-verify-seed-N` in the OS temporary directory. Existing output directories and a seed already present in the database are refused; choose a new folder/fresh migrated database for a rerun. A partial replay is not automatically retried.

For seeds 1–5, use five independently provisioned/migrated databases p1_seed1_verify through p1_seed5_verify, then:

```powershell
1..5 | ForEach-Object {
    $env:DATABASE_URL = "postgresql+psycopg://awoc:awoc@localhost:5432/p1_seed${_}_verify"
    python -m generator.cases.verify_answer_key --seed $_
    if ($LASTEXITCODE -ne 0) { throw "Seed $_ failed" }
}
```

## Outputs and exit status

Each seed writes canonical `seed_data.json`, `answer_key.json`, `receipt.json`, `observations.json` and `verification.json`. The first two are deterministic generated inputs. The receipt maps deterministic DEMO IDs to API-generated runtime UUIDs. Observations contain actual API responses and real DeadlinePort calls, not values copied from the answer key. Runtime receipts, actor/ledger identifiers and hashes are not promised byte-identical across replays. Keep these disposable files outside the repository.

- Exit 0 / PASS: zero mismatches in completed P1 replay evidence.
- Exit 1 / FAIL: replay completed, but observations differ; every mismatch prints its path, expected value and actual value and is saved in verification.json.
- Exit 2 / ERROR: unsafe/missing configuration, existing output/seed, invalid input, dependency failure or incomplete replay. No PASS is inferred from an interrupted run. Argparse also returns 2 for malformed CLI arguments.

The comparator checks the full pinned route list, ordered visited stages, final stage/status, deficiency count/IDs/times/status/closure/item states and response references, ordered exact open/pause/resume/close calls, opening due dates/times and observed letter triggers. Missing, duplicate, unexpected and reordered operations are mismatches. It also requires the real ledger API's verification to pass.

## Ownership and evidence limits

The harness uses a fixed logical ClockPort, explicitly trusted DEMO assignment/SHC facts, real authorization, real deadline engine and real ledger. The transparent deadline observer delegates every call to the real port and records successful calls. All commands must finish successfully before evidence is eligible for PASS; failed or rolled-back replays stop with ERROR. This process-local observation is needed because P2 currently emits opening events but not pause/resume/close events. Existing database state alone cannot reconstruct those calls; the CLI therefore **replays with observation enabled**, rather than guessing historical pauses from final status. A remote/historical verifier needs P2/P3 observability work first.

Application/item/transition/review mutations use real HTTP endpoints. Only institution master data uses the existing P1-only wf.institution bootstrap; no institution-create API exists. No direct writes or reads into other owners' tables are introduced. The CLI requires migrations already applied.

The current generator's outcomes remain REJECTED/WITHDRAWN. Its letter expectation count is zero because letter issuance is contract-blocked. The verifier detects non-null transition letter references and wf.letter_issuance_triggered events, including unexpected/duplicate triggers. Positive expectations require exact type/time/deficiency flag and a returned ID; missing event metadata becomes a mismatch, never an invented value. Reports label zero-letter runs **NO_POSITIVE_COVERAGE**. The prior letter contract request is still pending; no CompliancePort fake or newly enabled letter hook is installed here.

Both answer-key extensions remain `{}` and validate under the unchanged schema/models. P2/P3 metrics are **NOT_SUPPLIED**, not passing. EVC holds remain simulated stage delays, not real scheduler rows. The verifier does not claim legal/APH correctness or OCR/alert/tamper coverage. See category_mix.md, ASSUMPTIONS.md and generator_report.md for assumptions and measured results.
