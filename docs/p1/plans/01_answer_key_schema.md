# Answer-key proposal plan

1. Read ENGINEERING_RULES.md, the repository audit, Team Split 3.1/5.1/7, and the P1 generator requirements.
2. Define a versioned, DEMO-only per-seed document with typed IDs, logical times, workflow scenarios, route outcomes and clock expectations.
3. Reserve empty, closed extension objects for P2 and P3; document their intended scope without inventing their fields.
4. Generate draft 2020-12 JSON Schema from Pydantic models and validate a hand-written example, schema/model parity, invalid inputs and relational invariants.
5. Run the complete pytest suite and both repository checks in Python 3.12/Linux with disposable PostgreSQL. Review the diff and push only person-1.

No contracts, application services, rulesets, migrations, or other owners' modules will change. This is a proposal, not a scale-generator or scorecard implementation. Design assumptions are recorded in docs/p1/ASSUMPTIONS.md.

## Verification results

- Isolated Windows Python 3.12: `python -m pytest -p no:cacheprovider tests/test_answer_key_schema.py`: 45 passed.
- Python 3.12 Linux with dedicated disposable PostgreSQL 16 and the repository mounted read-only: `python -m pytest -p no:cacheprovider`: 76 passed, 1 dependency deprecation warning, in 75.17 seconds. All 31 pre-existing cases and 45 new cases ran.
- Same Linux environment: `python scripts/check_contracts.py`: exit 0, `contracts ok`; `python scripts/check_migration_heads.py`: exit 0, `checked 3 migration chains`.
- `git diff --cached --check`: passed. No existing files or contracts changed; no endpoints, events, tables, migrations or dependency changes.
- Review remains necessary for P2/P3 extensions, scorecard matching rules and proposed vocabularies; this does not block publishing the proposal for team review.
