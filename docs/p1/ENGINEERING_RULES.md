# Person 1 engineering rules

## Scope
Person 1 (P1): Approval workflow + EVC. Work only on branch person-1.
Reference docs: docs/reference/SIH26262_Team_Split.txt and docs/reference/SIH26262_Person1_Work_Pack.txt. Read the relevant section before every task.

## What P1 owns (may edit)
backend/app/intake/, backend/app/workflow/, backend/app/evc/
backend/migrations/versions/workflow/ and backend/migrations/versions/evc/ (own Alembic chains)
rulesets/aph-2024-27/r1/routes.yaml, rulesets/aph-2024-27/r3-DEMO/overlay.yaml (deadline keys in the overlay need P2 approval)
generator/cases/
tests/e2e/step01*, step02*, step03*, step04*, step10* and tests for P1 modules
docs/p1/
Postgres schemas P1 writes to: wf and evc ONLY.

## What P1 must NOT edit (ask Person 1 first)
contracts/ (needs approval from all three people; see "Contract change procedure")
backend/app/platform/, analytics/ (P3); documents/, compliance/, deadlines/, calendars/, generator/documents/ (P2); frontend/, docker-compose.yml, .github/, scripts/ (P3); rulesets/.../r1/deadlines.yaml (P2).

## Hard rules
1. One writer per table: never INSERT/UPDATE/DELETE on tables owned by another person's schema (doc, cmp, dl, plat, an). Call their ports. Cross-schema reads go only through published read-only views.
2. Modules talk only through ports in contracts/ports.py, looked up with port(PortType). Never import another module's internals.
3. One command = one transaction (unit_of_work). Transition + deadlines + ledger events + outbox rows commit atomically. No async processing for mandatory work.
4. Time: only clock.now() via ClockPort. datetime.now()/utcnow()/date.today() are banned (CI greps for them).
5. Events: names must start with wf.* or evc.*. Every event has a JSON Schema at contracts/events/<prefix>/<name>.v<N>.json. NO free-text fields in event payloads. Free text goes through notes.create (returns note_ref, note_hash). Personal data (names, phones, emails) goes through personal.store (reference only).
6. Every command: authz.check(...) first, then guards, then state change, then ledger.append for every state change.
7. Handlers must be deterministic so P3's Idempotency-Key middleware works (no random, no wall-clock, no unordered iteration affecting output).
8. Migrations: own Alembic chain per module with its own branch_labels; never create a second head (scripts/check_migration_heads.py must pass). Cross-schema FKs only to another owner's stable id.
9. Rulesets are versioned and pinned: a case pinned to aph-2024-27@r1 stays on r1. r3-DEMO is refused outside demo mode. Anything not confirmed from an official APH source is labelled as a DEMO ASSUMPTION in YAML and in API output. Anything simulated is labelled SIMULATED.
10. All demo/synthetic data is fictional and labelled DEMO.
11. Licences: no Camunda 8, immudb, n8n, AGPL packages (e.g. pm4py) in core. OR-Tools (Apache-2.0) is allowed.
12. Do not invent legal/APH clauses. If a clause or number is unknown, make it a configurable demo assumption and list it in docs/p1/ASSUMPTIONS.md.

## Contract change procedure
If a task seems to need a change in contracts/: STOP, do not edit it, and write the proposed change to docs/p1/contract_requests/<date>_<topic>.md (what, why, exact diff, impact on fakes.py and openapi.json). Person 1 takes it to the team. Once all three approve: edit contracts/ AND contracts/fakes.py in the same commit, run python scripts/check_contracts.py --write, and mention it in the commit message.

## Definition of done (every task)
- Code + migrations + event schemas + OpenAPI refreshed (python scripts/check_contracts.py --write only if the API changed)
- Tests added for every new behaviour including failure paths; python -m pytest passes (all pre-existing tests still pass)
- python scripts/check_contracts.py and python scripts/check_migration_heads.py pass
- No datetime.now()/utcnow() anywhere
- docs/p1/ASSUMPTIONS.md updated for any new assumption
- The commit or pull request description lists: files changed, new endpoints/events/tables, tests added, commands run with results, assumptions made, and anything blocked on P2/P3.

## Style
Python 3.x, FastAPI, SQLAlchemy, Alembic, Pydantic, pytest. Small functions, type hints, explicit error classes from contracts/errors.py (ValidationFailed 422, NotFound 404, Forbidden 403, Conflict 409). Commit messages short and imperative.
