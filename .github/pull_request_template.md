## What this changes

<!-- One or two sentences. -->

## Checklist

- [ ] Only touches my own folders (see `docs/OWNERSHIP.md`), or the owner has agreed
- [ ] Tests added or updated, and `python -m pytest` passes locally
- [ ] If `contracts/` changed: fakes updated, `python scripts/check_contracts.py --write` run, all three approve
- [ ] If tables changed: a migration in my module's own folder, and `python scripts/check_migration_heads.py` passes
- [ ] Synthetic data only; no real institution or personal data
