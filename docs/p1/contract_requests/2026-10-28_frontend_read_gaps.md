# Read endpoints for the frontend — three-way approval request

Date: 28 October 2026. P1. Status: **pending three-way approval (P1, P2, P3)**. The regenerated OpenAPI is committed on its own so it can be reviewed, approved or reverted independently of the code.

## Why this is needed

The frontend (P3) reported reads it had to work around: no list or read of EVC runs, no per-case EVC read, committees only discoverable from timeline events, a mirrored deficiency vocabulary and a 403 on `GET /api/applications/{id}` for regional officers. Plan 4.5 adds read-only endpoints for each. Permissions reuse existing actions (`evc.expert.read`, `application.read`, `ruleset.read`, `committee.read`); policy.py and the Cerbos policies are unchanged. No event schema, port, shared type, enum or fake changes.

## Generated OpenAPI changes

Refreshed with `python scripts/check_contracts.py --write` (Python 3.12), no hand edits:

- `GET /api/evc/schedule/runs` → RunPage {items: RunSummary[], total, offset, limit}; query status (PROPOSED|PUBLISHED|DISCARDED), algorithm (EDF|CPSAT), region, offset, limit.
- `GET /api/evc/schedule/runs/{run_id}` → RunDetail (RunSummary + solver, proposals with `published`, unscheduled with `application_id` and `explanation_code`, withdrawn).
- `GET /api/applications/{application_id}/evc` → CaseEvcOut {application_id, region, current, requests[] with visit}.
- `GET /api/evc/queue` gains the `application_id` query parameter.
- `GET /api/rulesets/{key}/deficiency-vocabulary` → DeficiencyVocabularyOut.
- `GET /api/cases/{application_id}/committees` → CommitteeSummaryOut[].
- `GET /api/applications/{application_id}`: description only (now region-scoped for regional officers); the response is unchanged.

Behaviour change worth noting for P2/P3: `POST /api/applications/{id}/items` (and items on create) now refuses a `document_ref` that is not an AVAILABLE version of the same application (422 DOCUMENT_REF_UNKNOWN / DOCUMENT_REF_NOT_AVAILABLE); UUID5 DEMO fixture references are still accepted in DEMO_MODE (DOC-REF-001). The propose response's `region_scope` now carries the officer's own region when an RO proposes without naming one. Request and response shapes are unchanged.

## Impact if refused

The endpoints are additive; reverting the OpenAPI commit only removes them from the published contract. The frontend would go back to its workarounds.
