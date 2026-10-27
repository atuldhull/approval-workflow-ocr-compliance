# EVC schedule discard event and scheduling response fields — three-way approval request

Date: 28 October 2026. P1. Status: **pending three-way approval (P1, P2, P3)**. The schema and the regenerated OpenAPI are committed on their own so they can be reviewed, approved or reverted independently of the scheduler code.

## Why this is needed

Plan 3.7 adds `POST /api/evc/schedule:discard` {run_id}: a bureau officer withdraws an unpublished PROPOSED run so its requests can be re-planned. Drafts are deleted, their requests go back to QUEUED and the run becomes DISCARDED. That is a state change, and no existing event describes it: evc.schedule_proposed and evc.assignment_proposed record the opposite, evc.request_cancelled closes the request and its clock, and evc.assignment_published is publication. `LedgerPort.append` refuses an event type without a versioned schema, so one new schema is unavoidable. Permissions are unchanged: the route reuses `evc.schedule.publish` (BUREAU_OFFICER, BUREAU_HEAD). No port, shared type, enum, fake, P2 deadline or P3 policy changes.

## Exact schema addition

`contracts/events/evc/schedule_discarded.v1.json` — aggregate `evc_schedule_run`, aggregate id = run id (the same aggregate as evc.schedule_proposed). One event per discarded run:

```text
run_id: UUID; algorithm: EDF | CPSAT; discarded_count: integer >= 0
withdrawn: [{application_id, request_id, assignment_id}: UUIDs]
request_status: const QUEUED; simulation_status: const SIMULATED; source_status: const DEMO_ASSUMPTION
```

No names, contact details, notes or free text: every string is a UUID, enum or constant, so `scripts/check_contracts.py` accepts the file.

## Generated OpenAPI

Refreshed with `python scripts/check_contracts.py --write` (Python 3.12), no hand edits:

- new route `POST /api/evc/schedule:discard` (DiscardBody {run_id} → DiscardOut);
- propose response: `expert_daily_cap` (integer) and, per unscheduled request, `explanation_code` next to the unchanged `reason_code` NO_FEASIBLE_SLOT; `solver.candidate_slots` (integer);
- route descriptions for propose/publish (daily cap, region codes, slot_capacity as the demo slot path).

The existing event payloads (evc.schedule_proposed.v1, evc.assignment_proposed.v1, evc.assignment_published.v1) are unchanged; explanations exist only in the HTTP response.

## Impact if refused

Without the schema, discard fails with `no contract schema` and rolls back; proposing and publishing still work. Reverting the schema commit withdraws the request; the scheduler code, tests and docs stay P1-owned.
