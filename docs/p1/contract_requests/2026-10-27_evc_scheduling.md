# EVC scheduling events — three-way approval request

Date: 27 October 2026. P1 / p1/evc-schedule. Status: **pending three-way approval (P1, P2, P3)**. The schemas are committed on their own so they can be reviewed, approved or reverted independently of the scheduler implementation.

## Why this is needed

`POST /api/evc/schedule:propose` and `POST /api/evc/schedule:publish` change EVC state (proposed panels, published reservations, request status). Every state change must be appended to the ledger, and `LedgerPort.append` refuses any event type without a versioned schema under `contracts/events/`. The existing evc schemas cover request lifecycle and expert pool management only. No port, shared type, enum or fake changes: `EvcPort.status` already returns `PUBLISHED`, which is what a workflow guard for `complete_evc` needs.

## Exact schema additions

`contracts/events/evc/schedule_proposed.v1.json` — aggregate `evc_schedule_run`, aggregate id = run id. One event per proposal run.

```text
run_id: UUID
algorithm: EDF | CPSAT
region_scope: upper-case region code or null (all regions)
proposals[]: request_id, assignment_id, slot_id (UUIDs), date (ISO date), slot_part AM|PM,
             expert_ids (unique UUIDs, >=1), lateness_days (integer >= 0)
unscheduled[]: request_id, reason_code NO_AVAILABILITY | COI_ONLY | PANEL_INCOMPLETE | CAPACITY_EXHAUSTED
scheduled_count, unscheduled_count, total_lateness_days: integers >= 0
selector_label: const "SIMULATED authorised selector (stand-in)"
simulation_status: const SIMULATED
source_status: const DEMO_ASSUMPTION
assumption_code: const EVC_SCHEDULING_POLICY_UNCONFIRMED
```

`contracts/events/evc/assignment_published.v1.json` — aggregate `application`, aggregate id = application id, so the publication appears on the case timeline next to evc.request_created/completed. One event per published assignment.

```text
run_id, application_id, request_id, assignment_id, slot_id: UUIDs
algorithm: EDF | CPSAT
date, due_by: ISO dates; slot_part AM|PM; lateness_days integer >= 0
expert_ids: unique UUIDs (>=1); panel_role: upper-case code
selector_label / simulation_status / source_status / assumption_code: same constants as above
```

No names, contact details, notes or free text: every string is a UUID, ISO date, enum, constant or upper-case code pattern, so `scripts/check_contracts.py` accepts both files. Expert UUIDs are opaque EVC identifiers; personal details stay behind PersonalDataPort.

## Generated OpenAPI

The two new routes also need the generated `contracts/openapi.json` refreshed with `python scripts/check_contracts.py --write` (Python 3.12). No hand edits. Approval covers that regeneration as in the earlier selector-preview request.

## Impact if refused

The scheduler module, its tests and docs stay P1-owned and can remain on the branch, but the propose/publish commands cannot append their ledger events and would fail with `no contract schema`. Reverting the schema commit is sufficient to withdraw the request.
