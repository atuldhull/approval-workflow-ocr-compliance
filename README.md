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
- Documents: upload with `Idempotency-Key`, ClamAV malware scan (nothing is used before it is clean), local text
  extraction (PDF text layer, Tesseract eng + hin for scans), blind entry before the OCR suggestion is revealed,
  review, and four-eyes confirmation by a second officer.
- Compliance: the bureau registers approval letters (LoA, EoA), which open obligations with deadlines; institutions
  submit evidence and an officer verifies it.
- Deadline alerts: a timer worker raises the alert ladder (reminder, breach, escalation, vacancy), delivered through
  the notifier; the addressed role acknowledges.
- Scorecard that keeps how each check was measured apart from what it found: ledger integrity, replay, alert delivery,
  alert timeliness, document scanning, four-eyes and OCR agreement are evaluated from live data.
- Role-based UI: applications and case view, dashboards built from events, inbox, alerts, documents, fact review,
  compliance, audit, alert delivery, scorecard, and a clearly marked preview of the EVC screen.

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
docker compose --profile worker --profile scanning up --build    # + notifier, deadline timers, ClamAV
cp .env.security.example .env.security                          # real sign-in (LOCAL DEMO accounts)
docker compose --env-file .env.security --profile security --profile worker --profile scanning up --build
python scripts/smoke_security.py                                 # end-to-end checks with real tokens
python scripts/smoke_demo.py --docker                            # demo-day checks on the default stack
docker compose exec backend python -m app.platform.demo_seed --sample-alerts   # demo alerts to deliver
docker compose --profile web up --build web                      # production UI image (nginx) on :8088
```

Uploads need the `scanning` profile: without ClamAV a file is accepted but stays `scan_pending` and cannot be
used. ClamAV downloads its signatures on first start, which takes a few minutes. `smoke_demo.py` moves the demo
clock forward (time travel), so run it on a stack whose data you do not need.

To try a branch next to a stack that is already running, use another project name and spare host ports, e.g.
`docker compose -p awoc-try --env-file try.env -f docker-compose.yml -f try.override.yml up` with `DB_PORT`,
`KEYCLOAK_PORT`, `CERBOS_PORT` and `WEB_PORT` set in `try.env`, and `ports: !override [...]` for `backend`,
`frontend`, `mailpit` and `clamav` in the override file. `docker compose -p awoc-try down -v` removes only that stack.

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
to also compare both policy engines decision by decision. `backend/tests/test_role_matrix.py` pins the status every
role gets from every endpoint; run it with `AUTHZ_ENGINE=cerbos CERBOS_URL=http://localhost:3592` to send the same
table through Cerbos.

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
infra/          local Keycloak realm and generated Cerbos policies (LOCAL DEMO ONLY)
tests/e2e/      demo-script steps as end-to-end tests
docs/           architecture, ownership, team workflow
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/OWNERSHIP.md](docs/OWNERSHIP.md) and
[docs/TEAM_WORKFLOW.md](docs/TEAM_WORKFLOW.md).
