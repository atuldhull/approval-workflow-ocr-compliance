# EDF baseline — SIMULATED authorised selector (stand-in)

The baseline sorts queued requests by due_by, requested_at and UUID; for each request it takes the earliest feasible slot by date, AM/PM and slot UUID. A complete deterministic selector panel must satisfy active status, availability, COI, region, expertise and reservation constraints. Capacity counts panels. Each new placement reserves both panel capacity and expert/date/part before the next request.

The pure interface is `plan_edf(SchedulingProblem)`. Persistence is `propose_edf(principal, ScheduleCommand(run_id, horizon_start, horizon_end, region=None))`, or `handle(uow, command)` when an enclosing command already owns the unit of work. Authorization precedes guards; requests, slots and expert roster are locked after an EVC scheduling advisory lock. Candidates registered after the locked roster snapshot wait for another run. Run IDs are explicit, assignment IDs deterministic, and a reused run conflicts.

Existing schedule_run/assignment/request columns represent PROPOSED state: run.status=PROPOSED, assignment.published=false, request.status=PROPOSED. Two approved audit schemas record run and per-application proposal changes. No table/migration/API endpoint is added. Publishing, completion, clocks and P2 escalation are unchanged.

## Metric definitions / comparison discipline

`evaluate_schedule(problem, allocations)` is independent of EDF and reusable by CP-SAT. Its violation checks cover queue membership, duplicate request/panel members, date bounds, capacity, eligibility, minimum expertise and expert double booking. A nonzero hard-violation count prevents persistence. A violation count is the sum of detected constraint occurrences; one bad placement can violate more than one constraint.

- scheduled/unscheduled count distinct input requests.
- lateness_days is in canonical EDF request order; null denotes an unscheduled request.
- lateness=max(0, placement date-original due_by), in calendar days.
- total/max lateness and late_count cover scheduled requests; empty maximum is zero.
- total_waiting sums calendar days from requested_at's IST date to placement date.
- comparison first minimises hard violations, then unscheduled count, total/max lateness and waiting. Dropping requests does not masquerade as improved lateness.

Use one immutable problem (same queue, policies, slots, reservations and logical clock) for EDF and CP-SAT. `compare_plans` verifies fingerprints and recomputes metrics. The run stores the input SHA-256 as numeric byte values; parameter/metric columns retain the existing numeric_json restriction. Do not persist EDF reservations and then capture a different input for a claimed CP-SAT comparison.

## Hand-verified small case

Three experts, panel size 1, all eligible. A and B are due day 0; A was requested on day -3, B on day -2. C was requested on day -4 but is due day 1. Slots: day-0 AM capacity 1; day-1 AM capacity 2.

| Request | Placement | Expert | Lateness | Waiting |
| --- | --- | --- | --- | --- |
| A | day-0 AM | 1 | 0 | 3 |
| B | day-1 AM | 2 | 1 | 3 |
| C | day-1 AM | 3 | 0 | 5 |

Measured and independently asserted: scheduled 3, unscheduled 0, lateness [0,1,0], total/max lateness 1, total waiting 11, hard violations 0. With late scheduling disabled, B stays unscheduled and original due dates remain unchanged.

## Forty-request fictional DEMO fixture

The pure fixture varies due/request dates, declared availability, COIs, inactive experts and an existing reservation. Twenty-four fictional profiles, N=3 and six days of AM/PM capacity-4 slots are used. An independent counter checks capacity, expert uniqueness, availability, exclusions and all metric totals.

| Metric | Measured |
| --- | --- |
| Queue / scheduled / unscheduled | 40 / 40 / 0 |
| Late requests | 24 |
| Total lateness | 25 days |
| Maximum lateness | 2 days |
| Total waiting | 205 days |
| Hard constraint violations | 0 |

A separate real-PostgreSQL fixture persists 40 proposals and checks stored allocations against the captured pre-proposal input, numeric parameters, unchanged due_by/pins, projection rows, event order, application timeline and ledger verification. Rollback after ledger writes, repeated runs, concurrent proposals, lock-snapshot expert insertion and role/region restrictions are tested.

## Assumptions / limits

Panel capacity and soft lateness are explicitly configurable DEMO ASSUMPTION policy, not APH legal rules. Planning uses a separate finite horizon; it never moves due_by or pauses a legal clock. Selection is SIMULATED authorised selector (stand-in), with unverified P3 user references. Future publication must cooperate with scheduling locks and recheck constraints; published-only DB uniqueness is insufficient for proposals. HTTP propose/publish integration and CP-SAT are later work.

Final verification: **6,274 tests passed**, zero failures/errors/skips, in 3,178.17 seconds (52m58s), including 35 new EDF tests (23 pure and 12 database/integration). One existing Starlette/AnyIO warning remains. `python scripts/check_contracts.py` passed; `python scripts/check_migration_heads.py` passed for all four chains (plat_0001, wf_0006, evc_0003, dl_0001). Contract regeneration passed without changing OpenAPI. The tested temporary checkout matches all 190 comparable source files in the working repository.
