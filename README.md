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
- Hash-chained audit ledger with tamper detection, signed checkpoints held by an independent witness, and
  read-only replay that checks read models against the event log ([docs/AUDIT.md](docs/AUDIT.md)).
- Sign-in: demo role switcher locally, or Keycloak (OIDC, PKCE) with Cerbos policy decisions
  ([docs/SECURITY.md](docs/SECURITY.md)). Institutions see only their own records, regional officers only their region.
- Safe retries with `Idempotency-Key` ([docs/IDEMPOTENCY.md](docs/IDEMPOTENCY.md)).
- Notification worker: in-app, email (SMTP) and mock SMS with retries, dead letters and delivery metrics
  ([docs/NOTIFICATIONS.md](docs/NOTIFICATIONS.md)).
- Role-based UI: applications and case view, dashboards built from events, inbox, audit, alert delivery, scorecard,
  and clearly marked previews of screens whose backend is still being built.

## Run it (Docker - recommended)

```bash
cp .env.example .env
docker compose up --build
```

- UI: http://localhost:5173
- API docs: http://localhost:8000/docs

If port 5432 is already used on your machine, set `DB_PORT=5433` in `.env`.

Optional extras:

```bash
docker compose --profile worker up --build                       # + notification worker
cp .env.security.example .env.security                          # real sign-in (LOCAL DEMO accounts)
docker compose --env-file .env.security --profile security --profile worker up --build
python scripts/smoke_security.py                                 # end-to-end checks with real tokens
docker compose exec backend python -m app.platform.demo_seed --sample-alerts   # demo alerts to deliver
```

Keycloak: http://localhost:8081 · Mailpit (captured demo email): http://localhost:8025 ·
demo accounts: [infra/keycloak/README.md](infra/keycloak/README.md)

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
python scripts/gen_cerbos_policies.py --check            # Cerbos policies match the policy table
node --test .github/scripts/contract-approval.test.js    # contract approval rule
cd frontend && npm test && npm run build                  # UI tests and production build
```

With Cerbos running (`docker compose --profile security up -d cerbos`), set `CERBOS_TEST_URL=http://localhost:3592`
to also compare both policy engines decision by decision.

Tests use `DATABASE_URL` pointing at a database named `awoc_test` by default
(`postgresql+psycopg://awoc:awoc@localhost:5432/awoc_test`).

## Repository layout

```
contracts/      shared ports, enums, event schemas, OpenAPI snapshot (all three approve changes)
backend/app/    one package per module (see docs/OWNERSHIP.md)
backend/migrations/versions/<module>/   one migration chain per module
rulesets/       versioned APH rules (routes.yaml, deadlines.yaml)
generator/      synthetic data
frontend/       React UI
infra/          local Keycloak realm and generated Cerbos policies (LOCAL DEMO ONLY)
tests/e2e/      demo-script steps as end-to-end tests
docs/           architecture, ownership, team workflow
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/OWNERSHIP.md](docs/OWNERSHIP.md) and
[docs/TEAM_WORKFLOW.md](docs/TEAM_WORKFLOW.md).
