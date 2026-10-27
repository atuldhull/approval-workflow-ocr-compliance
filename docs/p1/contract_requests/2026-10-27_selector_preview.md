# Simulated selector preview — generated OpenAPI approval request

Status: the user explicitly approved the OpenAPI-only update on 27 October 2026 before protected edits. Shared ports/types/enums/fakes, event schemas and P3 auth remain unchanged.

## What and why

The user requests a deterministic selector, ranked criterion scores and the label "SIMULATED authorised selector (stand-in)" in API output. Add a read-only preview of the actual selector result so the label and ranking can be tested through FastAPI. Existing shared ports/types/enums/fakes already suffice; the selector's input/result models live in P1's EVC module. No state is changed and no new ledger event, table or migration is proposed.

AGENTS requires: "If a task seems to need a change in contracts/: STOP, do not edit it, and write the proposed change". This request is specifically for **generated OpenAPI only**, leaving contracts/fakes.py unchanged because no port or shared value contract changes. No artificial fake edit is needed. No P3 auth or P2 edit is requested.

## Exact API operation to generate

```text
GET /api/evc/requests/{id}/panel-preview
path: id — UUID, required
query: date — ISO calendar date, required
query: slot_part — AM | PM, required
headers: existing X-Demo auth headers
authorization: existing evc.expert.read plus authoritative case.timeline scope
side effects: none
```

Institutions are refused. An RO must own the case region and use a SAME_REGION policy; cross-region previews require an existing global pool-reader role. QUEUED/PROPOSED requests are previewable. This reuses existing permissions without broadening P3 policy.

## Exact successful response fields

```text
request_id: UUID
ruleset_key: pinned string key
date: ISO calendar date
slot_part: AM | PM
selector_label: literal "SIMULATED authorised selector (stand-in)"
simulation_status: literal SIMULATED
source_status: literal DEMO_ASSUMPTION
assumption_code: literal SELECTOR_POLICY_UNCONFIRMED
identity_status: literal P3_USER_REF_UNVERIFIED
policy_version: literal DEMO_SELECTOR_V1
criteria_order: [ELIGIBILITY, EXPERTISE_MATCH, WORKLOAD, ROTATION, EXPERT_ID]
requested_size: positive integer from pinned YAML
status: SELECTED | INSUFFICIENT_CANDIDATES
panel: ordered array of expert UUIDs (exactly requested_size, or empty on shortage)
eligible_count: integer count after hard eligibility and minimum expertise threshold
required_expertise_tags: sorted coded string array
ranked_experts: ordered array of:
  rank: positive integer
  expert_id: UUID
  selected: boolean
  matched_expertise_tags: sorted coded string array
  criterion_scores:
    eligibility_passed: literal true
    expertise_matches: nonnegative integer (higher is preferred)
    workload_assignments: nonnegative integer (lower is preferred)
    last_assignment_date: ISO calendar date | null (null first, then oldest)
    rotation_days: nonnegative integer | null (null means no assignment on an earlier date)
    rotation_ordinal: nonnegative integer (0 for never assigned; lower preferred)
```

The UUID is the final deterministic tie-break; do not expose 128-bit UUID integers as JSON numbers. Raw names, emails, phones and notes are absent. A shortage is an explained successful preview with no partial panel. Invalid/missing policy or nonschedulable request uses a coded 422; missing request 404; denied scope 403.

## Exact protected-file change and impact

After implementing the P1 router/models, run `python scripts/check_contracts.py --write` and commit its generated contracts/openapi.json diff. It adds only this operation and the selector response components/references needed by FastAPI; existing operations remain. Do not hand edit the artifact. `contracts/fakes.py`, `ports.py`, `types.py`, `enums.py`, event schemas and P3 auth are unchanged. Approval is requested explicitly for this OpenAPI-only update as the applicable exception to the generic same-commit fake-edit procedure.

The rest of implementation is P1-owned: selector/adapter/API/tests/docs and labelled DEMO selector policy in r1 routes.yaml. Existing r1 cache/checksum rejection is preserved with fresh disposable demo test databases. Full pytest, contract and migration-head checks must pass before the authorized person-1 push.
