# Ownership

One owner per folder and per database schema. Change someone else's area only with their agreement,
and never write to another person's tables - call their port (`contracts/ports.py`) instead.

| Area | Owner |
|---|---|
| `backend/app/intake/`, `backend/app/workflow/`, `backend/app/evc/` | Person 1 |
| `rulesets/**/routes.yaml`, `rulesets/**/overlay.yaml` | Person 1 |
| `backend/migrations/versions/workflow/`, `backend/migrations/versions/evc/` | Person 1 |
| `generator/cases/` | Person 1 |
| `tests/e2e/` steps 1-4 and 10 | Person 1 |
| `backend/app/documents/`, `backend/app/compliance/`, `backend/app/deadlines/` | Person 2 |
| `rulesets/**/deadlines.yaml`, `calendars/` | Person 2 |
| `backend/migrations/versions/documents/`, `compliance/`, `deadlines/` | Person 2 |
| `generator/documents/` (incl. the OCR evaluation set) | Person 2 |
| `tests/e2e/` steps 5-9 | Person 2 |
| `backend/app/platform/`, `backend/app/analytics/`, `backend/app/main.py` | Person 3 |
| `frontend/`, `docker-compose.yml`, `backend/Dockerfile`, `.github/`, `scripts/` | Person 3 |
| `backend/migrations/versions/platform/`, `analytics/`, `backend/migrations/env.py`, `backend/alembic.ini` | Person 3 |
| `tests/e2e/` steps 11-13, `conftest.py` | Person 3 |
| `contracts/` | All three must approve |
| `docs/`, `README.md` | Anyone; keep it accurate |

## Database schemas

| Schema | Owner | Tables |
|---|---|---|
| `wf` | Person 1 | institution, application, stage_visit (next: ruleset, transition, deficiency, deficiency_item, committee, task, observation, inbound_event) |
| `evc` | Person 1 | evc_request, expert, availability, coi, slot, assignment, schedule_run |
| `doc` | Person 2 | document, document_version, fact, ocr_run |
| `cmp` | Person 2 | approval_letter, obligation, evidence, verification |
| `dl` | Person 2 | deadline (next: calendar_version, holiday, alert, ack, ladder) |
| `plat` | Person 3 | domain_event, ledger_entry, case_note, personal_data, outbox (next: checkpoint, delivery, idempotency_key, export) |
| `an` | Person 3 | projections, report_snapshot, scorecard_run |

## Where two areas meet

| Point | Owner | Other side |
|---|---|---|
| Ruleset registry vs `deadlines.yaml` | Person 1 owns the loader and versioning | Person 2 owns the file and its parser (`DeadlineRuleParserPort`) |
| Issuing a letter vs storing it | Person 1 triggers `CompliancePort.register_letter` | Person 2 owns the letter row and its obligations |
| Alerts | Person 2 decides what alert exists, for whom and when, and the escalation | Person 3 delivers it from the outbox, retries and logs delivery |
| Acknowledgement | Person 2 (endpoint and logic) | Person 3 (button) |
| OCR review screen | Person 3 builds the UI | Person 2 owns the type-then-reveal rule, backend and acceptance test |
| Time | Person 2 `ClockPort` is the only clock | Everyone calls it; never `datetime.now()` |
| Free text and personal data | Person 3 (`case_note`, `personal_data`) | Others store references only |
| Projections for replay | Each owner for their own events | Person 3 owns the replay harness |
