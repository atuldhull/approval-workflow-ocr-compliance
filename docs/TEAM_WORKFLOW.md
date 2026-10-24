# Team workflow

## Branches

```
main            always runs; changed only by integration pull requests
 ├── person-1   Person 1 works here
 ├── person-2   Person 2 works here
 └── person-3   Person 3 works here
```

- Work and commit on your own `person-N` branch. Push it often (at least daily) so the others can see progress.
- **Every 2-3 days we integrate.** The three person branches are merged into a short-lived
  `integration/YYYY-MM-DD` branch, conflicts are resolved, every check runs, and a pull request goes to `main`.
  Another team member reviews and approves it before it merges.
- **Right after each integration, everyone syncs** so the next round stays small:

```bash
git switch person-2
git pull origin main        # bring the integrated main into your branch
git push
```

Never let a person branch go more than a few days without syncing with `main` - long-lived divergence is
what makes integration painful.

## Daily routine

1. **Start (10 minutes, call):** what I finished, what I'm doing today, what I need from someone.
2. **Work** on your branch. Small commits with clear messages.
3. **End:** run the tests, push your branch.

```bash
git switch person-1
git pull origin person-1            # if you work from two machines
# ...code...
python -m pytest                    # must pass before you push
git add -A
git commit -m "Add deficiency loop transitions"
git push
```

## Commit messages

Short, imperative, about the change itself:

- `Add route registry with static validation`
- `Fix month-end clamp for 6-month obligations`
- `Show deadline explanation on case page`

## Rules that keep us out of each other's way

1. **Own folder, own tables.** See `docs/OWNERSHIP.md`. Need something from another module? Call its port.
2. **Contracts are shared.** Anything under `contracts/` (ports, enums, event schemas, OpenAPI snapshot)
   needs approval from all three. CI enforces this; CODEOWNERS alone does not.
3. **Migrations live in your module's folder** under `backend/migrations/versions/<module>/`.
   Create one with:
   ```bash
   alembic -c backend/alembic.ini revision -m "add deficiency tables" --head workflow@head \
     --version-path backend/migrations/versions/workflow
   ```
   Upgrade with `alembic -c backend/alembic.ini upgrade heads` (plural - one head per module).
4. **One command, one transaction.** A workflow transition, the deadlines it opens, its ledger events and any
   outbox rows commit together (`unit_of_work`). Only notification delivery happens afterwards, from the outbox.
5. **Time comes from `ClockPort`.** Never call `datetime.now()` in module code.
6. **No free text in events.** Reasons and observations go in `case_note`; personal fields in `personal_data`.
7. **Synthetic data only.** Fictional institutions marked DEMO; no real institution or personal data.

## Changing a contract

1. Edit `contracts/` and update `contracts/fakes.py` in the same branch.
2. If an API changed: `python scripts/check_contracts.py --write` to refresh `contracts/openapi.json`.
3. Explain the change in the pull request. All three approve.

## Repository settings (repo owner, once)

After the first push, in **Settings -> Branches -> Add rule** for `main`
(requires GitHub Pro / Team for private repositories; GitHub Education gives students Pro):

- Require a pull request before merging, with 1 approval
- Require review from Code Owners
- Require status checks: `backend`, `frontend`, `all-three-approve`
- Do not allow bypassing the above settings
