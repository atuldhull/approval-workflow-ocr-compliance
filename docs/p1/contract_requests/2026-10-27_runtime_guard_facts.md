# Contract request — runtime guard facts, idempotent P1 POSTs, checklist reads (27 October 2026)

Status: **pending three-way approval**. Only `contracts/openapi.json` changes, regenerated with `python scripts/check_contracts.py --write` (Python 3.12) and committed on its own. No event schema, port, shared type, enum or fake changes.

## OpenAPI changes

- New `GET /api/rulesets/{key}/checklists/{category}` → `ChecklistOut` (ruleset.read).
- New `GET /api/applications/{application_id}/checklist` → `ApplicationChecklistOut` (application.read, institution/region scoped).
- `LetterPayload` (inside `ActionIn.payload.letter`) gains optional `f_no` (1–100 chars), passed to `LetterIn.f_no`.
- `Idempotency-Key` header parameter (optional, 8–128 of `A-Za-z0-9_-:.`) on: case actions, intake create/items/submit, committee create/task/observation/report, deficiency review, EVC experts/availability/coi. Case-action description now documents replay (`Idempotent-Replayed: true`), 422 and 409. The intake/committee/EVC POSTs gain short descriptions.

## Behaviour behind the snapshot

See plans 4.1–4.4 and ASSUMPTIONS GF-001..GF-006, EVC-COMPLETE-001, IDEM-P1-001, CHK-READ-001, ROUTING-KEY-001. P2 can build its checklist view on the two read endpoints without changes to the documents module.
