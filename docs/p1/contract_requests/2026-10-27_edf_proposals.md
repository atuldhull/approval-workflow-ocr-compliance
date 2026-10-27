# EDF proposal audit schemas and scheduling permission request

Status: the user explicitly approved the two schema files and single P3 permission entry on 27 October 2026 before protected edits. No other shared contract/auth change is authorized or made.

## Why and scope

The requested EDF persistence creates a schedule_run, assignments and PROPOSED request state. AGENTS requires authz.check first and ledger records for state changes. Existing evc.expert.read/register permissions do not authorize scheduling, and existing lifecycle schemas do not describe proposals.

AGENTS says: "If a task seems to need a change in contracts/: STOP, do not edit it, and write the proposed change". It also requires approval for backend/app/platform/. Request the two exact schema files below plus one permission entry. This is specifically a **schema-only contracts exception**: ports.py, types.py, enums.py and fakes.py stay unchanged because no shared port/value interface changes. No new endpoint is part of this module task, so OpenAPI remains unchanged. Run the contract checker/generator and commit approved schemas together, mentioning approval.

## Exact P3 auth addition

Add this one entry to POLICY in backend/app/platform/auth.py; existing entries and auth logic remain unchanged:

```python
"evc.schedule.propose": {Role.RO_OFFICER, Role.BUREAU_OFFICER, Role.BUREAU_HEAD},
```

P1 enforces RO own-region scope on the command and authoritative cases through CasePort/AuthzPort. A global manager can propose a multi-region queue. Read-only experts/committee/auditor permissions do not grant mutation. No publishing permission is requested.

## Exact event schemas

### contracts/events/evc/schedule_proposed.v1.json

Run aggregate: evc_schedule_run / run_id. Payload has the following complete draft-2020-12 schema. EDF is implemented now; CPSAT is already an existing ScheduleRun algorithm enum, reserved for the later planner.

```json
{"$schema":"https://json-schema.org/draft/2020-12/schema","type":"object","additionalProperties":false,"required":["run_id","algorithm","horizon_start","horizon_end","input_fingerprint","metrics","simulation_status","source_status"],"properties":{"run_id":{"type":"string","format":"uuid"},"algorithm":{"enum":["EDF","CPSAT"]},"horizon_start":{"type":"string","format":"date"},"horizon_end":{"type":"string","format":"date"},"input_fingerprint":{"type":"string","pattern":"^[a-f0-9]{64}$"},"simulation_status":{"const":"SIMULATED"},"source_status":{"const":"DEMO_ASSUMPTION"},"metrics":{"type":"object","additionalProperties":false,"required":["queue_count","scheduled","unscheduled","late_count","total_lateness","max_lateness","total_waiting","hard_constraint_violations","lateness_days"],"properties":{"queue_count":{"type":"integer","minimum":0},"scheduled":{"type":"integer","minimum":0},"unscheduled":{"type":"integer","minimum":0},"late_count":{"type":"integer","minimum":0},"total_lateness":{"type":"integer","minimum":0},"max_lateness":{"type":"integer","minimum":0},"total_waiting":{"type":"integer","minimum":0},"hard_constraint_violations":{"const":0},"lateness_days":{"type":"array","items":{"type":["integer","null"],"minimum":0}}}}}}
```

### contracts/events/evc/assignment_proposed.v1.json

Application aggregate: application / application_id, ruleset_rev set from the pinned request. This event records both the created proposed assignment and QUEUED -> PROPOSED request transition. No personal details or free-text reason is emitted.

```json
{"$schema":"https://json-schema.org/draft/2020-12/schema","type":"object","additionalProperties":false,"required":["application_id","request_id","assignment_id","run_id","slot_id","date","slot_part","expert_ids","ruleset_key","request_status","simulation_status","selector_policy_version","source_status"],"properties":{"application_id":{"type":"string","format":"uuid"},"request_id":{"type":"string","format":"uuid"},"assignment_id":{"type":"string","format":"uuid"},"run_id":{"type":"string","format":"uuid"},"slot_id":{"type":"string","format":"uuid"},"date":{"type":"string","format":"date"},"slot_part":{"enum":["AM","PM"]},"expert_ids":{"type":"array","minItems":1,"uniqueItems":true,"items":{"type":"string","format":"uuid"}},"ruleset_key":{"type":"string","pattern":"^[a-z0-9-]+@[A-Za-z0-9-]+$"},"request_status":{"const":"PROPOSED"},"simulation_status":{"const":"SIMULATED"},"selector_policy_version":{"const":"DEMO_SELECTOR_V1"},"source_status":{"const":"DEMO_ASSUMPTION"}}}
```

## Impact and validation

No fake or protocol signature changes; FakeLedger already accepts EventIn generically. No OpenAPI diff or checker-script edit is expected. All runtime/model/policy/test/docs changes stay in P1 paths. Proposed assignments use published=false with PROPOSED run/request status; no redundant assignment-status column or migration is required.

Parameters/metrics retain the existing numeric_json constraint. Dates use ordinals and the input fingerprint uses byte integers in parameters; the ledger schema uses formatted dates and a constrained hash. Slot capacity counts panels, and scheduling after due_by uses a separate explicit planning horizon without changing due_by or P2 clocks. These are labelled DEMO assumptions. Full tests, contract and migration-head checks must pass before pushing person-1.
