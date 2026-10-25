# Standing user push instructions

When the user says "push to git", first verify the current branch is exactly person-1, review the pending diff, and run:

```sh
python -m pytest
python scripts/check_contracts.py
python scripts/check_migration_heads.py
git add -A && git commit -m "<short imperative message>" && git push
```

Commit only the authorized task files. Push exclusively to origin/person-1; use the explicit safe destination `git push origin HEAD:refs/heads/person-1` after checking the branch. Never switch to, commit on, or push main. Do not claim success if a check fails. In this Windows checkout, authoritative checks use Python 3.12/Linux and disposable PostgreSQL because the Alembic config's space-separated paths misparse the local path; disable pytest's cache when mounting source read-only. This records the user's instruction in the repository, not a claim of global memory outside this workspace.
