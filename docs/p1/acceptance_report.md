# P1 acceptance evidence — 26 October 2026

## Re-Scrutiny 2.2 — PASS

The new GET `/api/cases/{id}/rescrutiny` queries the active round and returns only non-ACCEPTED items, with the current response_ref and ordered response_history. Accepted item keys cannot be re-recorded. Each carried item has a previous_item_id; historical response references/decisions are preserved. After every item in a round has a decision, only rejected keys roll into the next round. Partial review retains undecided items. Per-item optional notes use NotesPort, outside event payloads.

**72 focused tests passed** in 209.60 seconds (one existing Starlette/AnyIO deprecation warning). This includes eight new Re-Scrutiny tests plus existing deficiency, case API, transactional engine, persistence and schema/model checks. Full regression: **6,030 passed**, zero failures/errors/skips, one existing Starlette/AnyIO deprecation warning, in **293.45 seconds**.

The five-item test uses real FastAPI, PostgreSQL, P2 deadlines and P3 ledger/timeline, with only the existing missing-assignment guard fact supplied as a fictional fixture:

| Checkpoint | Returned Re-Scrutiny scope / evidence |
|---|---|
| Initial deficiency / compliance | 5 OPEN, then 5 RESPONDED, each linked to its own response UUID |
| Officer start_rescrutiny | Same stored response references; no deadline opens/closes or duplicate timer effects |
| Round 1: 3 accepted | Exactly 2 remaining items; all 3 accepted IDs/keys absent |
| Remaining 2 rejected | Round 1 closes as SUPERSEDED; round 2 contains exactly those 2 OPEN keys |
| Round 2 traceability | previous_item_id links each rejected predecessor; old response remains in history, current response is null until resubmission |
| Resubmission | Exactly 2 new response references attached to the correct carried items, with both rounds' mappings preserved |
| Final acceptance | Round 2 closes as ACCEPTED; scope is empty; YAML advance moves NEW_PROGRAMME to EVC |

Exact rejection-finalization suffix: two `wf.deficiency_item_decided`, `wf.deficiency_superseded`, `dl.deadline_opened`, `wf.transition_applied`, `wf.deficiency_recorded`, `wf.stage_exited`, `wf.stage_entered`. Exact final-acceptance suffix: two `wf.deficiency_item_decided`, `wf.deficiency_closed`, `wf.transition_applied`, `wf.stage_exited`, `wf.stage_entered`. Ledger verification passes; five per-item protected notes exist outside event payloads. The superseded event is distinct from an accepted closure.

Additional tests reject accepted/foreign item IDs, response rewrites and stale versions, enforce institution/RO scope, roll back the entire rollover (decisions, notes, rounds, clocks, ledger and version) when the new round's ledger append fails, and roll back acceptance when the onward assignment guard fails. A last route stage closes its deficiency but awaits its separately authorized letter/decision; no approval is invented. Migration downgrade/upgrade preserves existing accepted rounds and response IDs. The user explicitly approved the new wf event and OpenAPI refresh; shared ports/types/enums/fakes remain unchanged.

Final commands: `python -m pytest -p no:cacheprovider --tb=short --junitxml=/tmp/rescrutiny-final.xml`, `python scripts/check_contracts.py`, `python scripts/check_migration_heads.py`, and `python -m alembic -c backend/alembic.ini heads` all passed. OpenAPI was generated with the explicitly approved `python scripts/check_contracts.py --write`. Heads are plat_0001/platform, wf_0005/workflow and dl_0001/deadlines: exactly one each. Python 3.12/PostgreSQL 16 ran in disposable containers; 130 code/config/schema files matched the checkout. No tests were skipped or removed.

The current route checkpoint still passes all 22 CSV routes, 34 terminal executions and the SHC/pinning checks. Its complete 5,148-pair matrix now contains 695 valid and **4,453 invalid pairs — 100% correctly rejected**. All 22 original route stage lists remain unchanged. Original APH/Final Report verification is still unavailable (0/22 source rows independently confirmed); the five codes and rollover policies are explicitly DEMO ASSUMPTIONS, not legal rules.

Changed API: GET /api/cases/{id}/rescrutiny; existing review accepts per-item notes and finalizes/advances/rolls over atomically. New event: wf.deficiency_superseded v1. Existing wf tables gain closure_kind and previous_item_id via wf_0005; no new table or P2/P3 runtime change. Remaining integrations are P1 production committee-assignment facts, P3 identity/idempotency and P2 confirmation of response windows/clock mutation events. Rejected-response resubmission is now implemented and is no longer a follow-up.

## Historical route checkpoint at ad6306a

**PASS.** JUnit confirms 5,197 acceptance tests, zero failures/errors/skips.

| Check | Passed / tested |
|---|---:|
| Frozen CSV route plans (21 Table 2.3 + NEW_INSTITUTION) | 22 / 22 |
| Transactional engine runs to APPROVED | 34 / 34 |
| EVC/conditional-SHC invariant | 22 / 22 |
| Complete route × stage × action matrix (22 × 13 × 18) | 5,148 / 5,148 |
| Invalid pairs rejected with INVALID_TRANSITION / 422 | **4,473 / 4,473 — 100%** |
| Valid pairs dispatched with favorable guard facts | 675 / 675 |
| Pinning/demo-gate tests | 3 / 3 |

The 12 EVC routes each run with SHC applied and skipped, producing 34 terminal runs. Matrix actions include all 14 canonical actions, three aliases and an unknown action; states include all eight stages, DRAFT, three terminal statuses and an unknown stage. A test-owned raw-YAML matcher also checks production expansion. Pinning covers old-state preservation, new submission using the selected r3-DEMO registry default, and refusal by registry/loader/HTTP/engine outside demo mode.

Full regression: **6,012 passed** in 863.15 seconds (one existing Starlette/AnyIO deprecation warning). `python -m pytest -p no:cacheprovider --tb=short --junitxml=/tmp/p1-route-acceptance-full.xml`, `python scripts/check_contracts.py` and `python scripts/check_migration_heads.py` all passed. Alembic heads: plat_0001, wf_0003, dl_0001 — one per module. Environment: Python 3.12/PostgreSQL 16; all 174 files in the temporary source snapshot matched the checkout before testing and remained unchanged afterward.

Real HTTP/auth, PostgreSQL state/visits, deadlines and ledger are exercised; missing guard facts and CompliancePort are explicit fictional fixtures, with the letter flag enabled only in tests. **Primary-source verification: 0/22** — every CSV row is flagged PRIMARY_SOURCE_UNAVAILABLE / ACCEPTANCE_SOURCE_UNVERIFIED in ASSUMPTIONS.md because the original APH/Final Report is absent. The CSV is a manually frozen regression oracle transcribed from the current project representation.

Changes are tests and P1 documents only. Production bugs found/fixed: **none**. No endpoints, events, tables, production code or contracts changed.
