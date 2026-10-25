# P1 route acceptance — 26 October 2026

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
