# Architecture

A FastAPI + PostgreSQL **modular monolith**. One process, one database, separate modules with clear owners.

```
frontend (React)  ──HTTP /api──►  FastAPI app
                                    ├── platform    auth, unit of work, ledger, notes, personal data, outbox
                                    ├── intake      institutions, applications
                                    ├── workflow    versioned rule registry (APH Table 2.3), state machine
                                    ├── evc         EVC queue and date scheduling
                                    ├── documents   upload, OCR, extracted facts
                                    ├── compliance  approval letters, obligations, evidence
                                    ├── deadlines   deadline rules, engine, alerts, clock
                                    └── analytics   projections, dashboards, scorecard
                                  PostgreSQL: one schema per module (wf, evc, doc, cmp, dl, plat, an)
```

## How modules talk

Through **ports** (`contracts/ports.py`): plain Python calls made inside the caller's transaction.
`app/main.py` discovers each module's `models.py`, `wiring.py` (registers its ports) and `api.py`
(its router), so adding a module never means editing someone else's file.

Example - submitting an application (`POST /api/applications/{id}/submit`):

1. Auth resolves the caller; `AuthzPort` checks the role and that an institution only touches its own records.
2. Intake loads the application under a row lock and pins the default ruleset (`aph-2024-27@r1`).
3. `RulesetPort` returns the route for the category from `routes.yaml`.
4. `LedgerPort.append` writes `wf.application_submitted` (schema-validated, hash-chained).
5. For each clock in `clocks.on_submit`, `DeadlinePort.open` creates the deadline and writes `dl.deadline_opened`.
6. Commit. If any step fails, nothing is saved.

## Rulesets

`rulesets/<ruleset>/<revision>/` holds `routes.yaml` (Person 1) and `deadlines.yaml` (Person 2).
An application pins the revision at submission and keeps it. `r3-DEMO` is an overlay used only for the
rule-change simulation; the registry refuses it unless `DEMO_MODE=true`.

Values without a handbook source (e.g. the 30-day processing timer) are marked `source.status: demo_assumption`
and shown as such in every deadline explanation.

## Audit ledger

`plat.domain_event` stores full event payloads (ids, enums, dates, hashes - no free text).
`plat.ledger_entry` chains them: `entry_hash = SHA-256(prev_hash + event_hash)`.
`GET /api/ledger/verify` recomputes everything and reports the first broken entry. This detects tampering
relative to a trusted chain head; independent signed checkpoints come next.

## Demo switches

| Variable | Effect | Production |
|---|---|---|
| `DEMO_AUTH` | Accept `X-Demo-*` headers as identity | must be `false` (Keycloak) |
| `DEMO_MODE` | Allow time travel and the `r3-DEMO` overlay | must be `false` |
