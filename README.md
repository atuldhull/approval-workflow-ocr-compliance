# Approval Workflow, OCR & Compliance

Rule-versioned approval workflow with OCR document extraction (Indic + English), a deadline and escalation
engine, and a hash-chained audit ledger. Built for SIH 2026, problem statement 26262
(AICTE approval workflow automation, compliance monitoring and alert management).

**Stack:** FastAPI · PostgreSQL · SQLAlchemy · Alembic · React (Vite) · Docker

> All data in this repository is synthetic. Institutions are fictional and marked DEMO.

## What works today

- Institution creates and submits an application; the route comes from the versioned APH ruleset
  (all 21 Table 2.3 categories plus new institutions), pinned at submission.
- Submission, its first processing clock and its audit events are saved in one transaction.
- Deadline engine with explainable due dates (calendar days, months with month-end clamp, Indian dates).
- Hash-chained audit ledger with tamper detection.
- Role-scoped access (institutions see only their own records).
- Basic UI: create, submit, route, clocks with "why", audit timeline, ledger check.

## Run it (Docker - recommended)

```bash
cp .env.example .env
docker compose up --build
```

- UI: http://localhost:5173
- API docs: http://localhost:8000/docs

If port 5432 is already used on your machine, set `DB_PORT=5433` in `.env`.

## Run it without Docker (backend)

Needs Python 3.12+ and a PostgreSQL database.

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows   (macOS/Linux: source .venv/bin/activate)
pip install -r backend/requirements-dev.txt
set DATABASE_URL=postgresql+psycopg://awoc:awoc@localhost:5432/awoc     # export on macOS/Linux
alembic -c backend/alembic.ini upgrade heads
python generator/cases/seed_demo.py
uvicorn app.main:app --app-dir backend --reload
```

Frontend: `cd frontend && npm install && npm run dev`

## Checks

```bash
python -m pytest                          # unit + end-to-end tests (creates its own test database)
python scripts/check_contracts.py         # shared contracts valid and up to date
python scripts/check_migration_heads.py   # one migration head per module
```

Tests use `DATABASE_URL` pointing at a database named `awoc_test` by default
(`postgresql+psycopg://awoc:awoc@localhost:5432/awoc_test`).
The database fixture drops and recreates that database. Before running tests that
use PostgreSQL, verify it is disposable and explicitly opt in:

```powershell
$env:AWOC_TEST_DATABASE_DISPOSABLE = "1"
python -m pytest
```

The fixture rejects non-local PostgreSQL hosts, database names other than
`awoc_test`, URL query overrides, and runs without this opt-in. Unit tests that
do not request the database fixture do not need the opt-in.

## Repository layout

```
contracts/      shared ports, enums, event schemas, OpenAPI snapshot (all three approve changes)
backend/app/    one package per module (see docs/OWNERSHIP.md)
backend/migrations/versions/<module>/   one migration chain per module
rulesets/       versioned APH rules (routes.yaml, deadlines.yaml)
generator/      synthetic data
frontend/       React UI
tests/e2e/      demo-script steps as end-to-end tests
docs/           architecture, ownership, team workflow
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/OWNERSHIP.md](docs/OWNERSHIP.md) and
[docs/TEAM_WORKFLOW.md](docs/TEAM_WORKFLOW.md).
