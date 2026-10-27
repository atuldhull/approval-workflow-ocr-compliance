# EVC publication event and scheduling routes — three-way approval request

Date: 27 October 2026. P1. Status: **pending three-way approval (P1, P2, P3)**. P1 accepted the schema as-is on 28 October 2026 (plan 3.7); P2 and P3 approval are still pending. The schema and the regenerated OpenAPI are committed on their own so they can be reviewed, approved or reverted independently of the scheduler code.

## Why this is needed

The EDF baseline (3.5) already has its approved schemas, evc.schedule_proposed.v1 and evc.assignment_proposed.v1; CP-SAT runs emit exactly those payloads with algorithm CPSAT, which the approved schema already allows. Publication (3.6) is new: `POST /api/evc/schedule:publish` turns proposed assignments into published reservations and moves requests to PUBLISHED. Every state change must be appended to the ledger, and `LedgerPort.append` refuses any event type without a versioned schema under `contracts/events/`. No port, shared type, enum or fake changes: `EvcPort.status` already returns `PUBLISHED`, which is what a workflow guard for `complete_evc` needs. Permissions are unchanged: `evc.schedule.propose` and `evc.schedule.publish` are already in the platform policy.

## Exact schema addition

`contracts/events/evc/assignment_published.v1.json` — aggregate `application`, aggregate id = application id, so the publication appears on the case timeline next to evc.assignment_proposed. One event per published assignment. It mirrors evc.assignment_proposed.v1 and adds the run's algorithm, the due date and lateness:

```text
application_id, request_id, assignment_id, run_id, slot_id: UUIDs
algorithm: EDF | CPSAT
date, due_by: ISO dates; slot_part AM|PM; lateness_days integer >= 0
expert_ids: unique UUIDs (>=1); panel_role: upper-case code (DEMO_PANEL)
ruleset_key: pinned ruleset key; request_status: const PUBLISHED
simulation_status: const SIMULATED; selector_policy_version: const DEMO_SELECTOR_V1; source_status: const DEMO_ASSUMPTION
```

No names, contact details, notes or free text: every string is a UUID, ISO date, enum, constant or code pattern, so `scripts/check_contracts.py` accepts the file. Expert UUIDs are opaque EVC identifiers; personal details stay behind PersonalDataPort.

## Generated OpenAPI

The two routes `POST /api/evc/schedule:propose` (algorithm EDF|CPSAT over the EDF baseline's command) and `POST /api/evc/schedule:publish` need the generated `contracts/openapi.json` refreshed with `python scripts/check_contracts.py --write` (Python 3.12). No hand edits.

## Impact if refused

The scheduler code, its tests and docs stay P1-owned. Without the schema, publication cannot append its ledger event and fails with `no contract schema`; proposing (EDF or CP-SAT) still works through the approved 3.5 schemas. Reverting the schema commit is sufficient to withdraw the request.
