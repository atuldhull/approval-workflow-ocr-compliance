# Deadline lifecycle events and obligation overdue fields — three-way approval request

Date: 28 October 2026. P2. Status: **approved by Person 1, Person 2 and Person 3 on 2026-10-28**. The schemas and the regenerated OpenAPI are committed on their own so they can be reviewed, approved or reverted independently of the deadline code.

## Why this is needed

Only `dl.deadline_opened` existed. Closing, pausing and resuming a clock changed `dl.deadline` without an event, and no clock was ever marked BREACHED, so:

- the audit trail could not show when or how a clock ended (F4);
- replay reported `CHANGED_WITHOUT_EVENT` for every paused or resumed deadline and could not compare status at all, which kept the scorecard at Attention and the dashboard's deadline card at Partial;
- an obligation whose clock had run out looked the same as one still in time.

`LedgerPort.append` refuses an event type without a versioned schema, so four new schemas are unavoidable. No port, shared type, enum or fake changes: `DeadlinePort.close/pause_internal/resume_internal` keep their signatures, and `DeadlineStatus.BREACHED` already existed.

## Exact schema additions

All under `contracts/events/dl/`, aggregate `deadline`, aggregate id = deadline id, written in the same unit of work as the change. Every string is a UUID, enum, pattern or date, so `scripts/check_contracts.py` accepts them.

```text
deadline_closed.v1    deadline_id, subject_type, subject_id, rule_id,
                      outcome: MET | WAIVED, from_status: RUNNING | PAUSED | BREACHED,
                      late: boolean (closed after its due time), due_date, due_version >= 1
deadline_paused.v1    deadline_id, subject_type, subject_id, rule_id,
                      from_status: RUNNING | BREACHED, due_date, due_version >= 1
deadline_resumed.v1   deadline_id, subject_type, subject_id, rule_id,
                      due_date (new), due_version >= 2 (new), held_seconds >= 0
deadline_breached.v1  deadline_id, subject_type, subject_id, rule_id, clock_kind, clock_owner,
                      due_date, due_version >= 1
```

## Behaviour

- The timer worker (and `POST /api/sim/timers/run`) marks a RUNNING clock past its due time BREACHED before firing alerts, once per due_version: the status change is the guard, so a second run writes nothing. Paused clocks are never breached.
- A BREACHED clock is still live: it keeps its alert ladder (the worker claims RUNNING and BREACHED), it can be closed (`late: true`, `from_status: BREACHED`) and an internal one can be paused; resuming gives it a new due_version, which is breached again if that due time has also passed.
- Accepting evidence on an obligation whose clock was BREACHED now closes the clock as MET late, which also stops its escalation. The breach stays in the ledger.
- Migration `dl_0007_breached_is_live` widens the partial indexes `uq_deadline_live` (RUNNING, PAUSED, BREACHED) and `ix_dl_deadline_timer_due` (RUNNING, BREACHED). No row is rewritten.

## Generated OpenAPI

Refreshed with `python scripts/check_contracts.py --write` (Python 3.12), no hand edits: `ObligationOut` gains `deadline_status` (string or null, read from the obligation's clock) and `overdue` (boolean, default false: the clock is BREACHED and the obligation is not MET). No obligation status is added; overdue is derived from the deadline.

## Consumers

- Analytics `DeadlinesProjection` folds the four events and now compares `status` and `due_version` as well; clocks changed before these events existed are reported as changed without an event, never as a mismatch.
- The alert-timeliness scorecard item checks breached clocks as well as running ones.

## Impact if refused

Without the schemas, every close, pause, resume and timer run would fail with `no contract schema` and roll back. Reverting this request means reverting the schema commit together with the deadline commit that emits them.
