# evc (Person 1)

Implemented storage:
- `evc_request`, `expert`, `availability`, `coi`, `slot`, `assignment`, `schedule_run` tables (schema `evc`), plus trigger-owned `assignment_expert` membership rows.
- Independent `evc_0001` Alembic chain, branch label `evc`; dependency on stable `wf_0001` application/institution IDs only.
- `assignment.expert_ids` is the requested UUID array. PostgreSQL mirrors all members, including proposals, to `assignment_expert`, validates expert references, and uniquely reserves `(expert_id, date, slot_part)` only while published. Inserts, publication, expert/slot changes and trigger-synchronized slot calendar edits all enforce the same constraint. Every FK references a stable UUID ID only; mutable dates/parts are synchronized under slot SHARE locks rather than FK targets. Direct membership INSERT/UPDATE/DELETE is rejected; application code writes assignment only.
- `schedule_run.parameters` and `metrics` are objects with recursively numeric/boolean/null values, arrays and coded keys. String values/free text are rejected in the database. Algorithm is a separate EDF/CPSAT column; run status and panel roles are uppercase coded tokens, without an invented approval lifecycle.
- No personal information: experts contain only opaque user_ref, region, coded expertise tags and active flag. No published P3 user table exists, so user_ref has no invented FK; EVC/wf links target stable IDs.

Demo bootstrap after applying migrations and the existing institution seed:

```powershell
python generator/cases/seed_demo.py
python -m generator.cases.seed_evc_demo --at 2026-07-01T04:30:00Z
```

The EVC seed writes only evc: 30 fictional DEMO expert references, 3600 AM/PM availability rows across 60 logical dates, and 3 DEMO COIs referencing the three existing fictional institutions. The supplied ClockPort is the only date source. UUID5 IDs and availability patterns are deterministic; repeat runs preserve identical rows and conflicting curated rows are refused. The CLI requires DEMO_MODE=true and the seed transaction rolls back on missing referenced institutions or conflicting rows. Seed data never belongs in migrations and no real user accounts are created. See docs/p1/ASSUMPTIONS.md and docs/p1/plans/3.1_evc_schema.md.

Implemented queue/lifecycle:
- `GET /api/evc/queue` filters region/status and inclusive due_by date bounds (`from`, `to`), with offset/limit pagination and stable ordering. Institutions see only their own cases; ROs only their region. Scope comes from CasePort/AuthzPort before totals and pagination.
- Actual workflow EVC entry (including generic advance and deficiency review) calls the public EvcPort, creates one request per source visit and one live clock, and emits evc.request_created.v1 inside the same unit of work. Duplicate/replayed commands cannot create a second clock. Later authorized re-entry gets a distinct historical request.
- complete_evc and normal EVC exits close MET and mark DONE with evc.request_completed.v1. Last-applicable EVC (SHC skipped) has a guarded completion self-transition; no route's stage list changes. Unscheduled reject/withdraw/revert exits cancel/close WAIVED with evc.request_cancelled.v1. Scheduled cancellation fails closed until an assignment-unpublication lifecycle exists.
- evc_0002 adds pinned rule/ruleset/deadline/visit references and closed_at, keeping legacy rows nullable rather than fabricating provenance. Legacy duplicates make the active uniqueness migration fail explicitly; existing cached ruleset checksums remain immutable. Use a fresh disposable demo database for the approved r1 source changes.
- EVC_PROCESSING is an INTERNAL/COMMITTEE clock with a configurable **7 calendar-day DEMO ASSUMPTION**, not an APH-confirmed duration. Queue rows expose source_status, assumption_code, duration_days and pinned metadata. Waiting days count elapsed 24-hour periods and stop at completion/cancellation. P2 alone owns overdue escalation; P1 only opens/closes through DeadlinePort.

Expert pool management:
- `POST /api/evc/experts` accepts opaque P3 user_ref, coded region/tags, active and optional personal_details. Contact fields go exclusively through PersonalDataPort; expert/event/response data retains only personal_ref. Identity is explicitly P3_USER_REF_UNVERIFIED until P3 supplies an authoritative lookup interface. Duplicate user_ref returns 409.
- `POST /api/evc/experts/{id}/availability` atomically sets `items: [{date, slot_part, available}]` (1–732 unique keys); identical repeats produce no new events. `POST /api/evc/coi` records matching INSTITUTION_LINK, PRIOR_ENGAGEMENT or RECUSAL source/reason codes; duplicates are no-ops.
- `GET /api/evc/experts?region=&available_on=` is a scoped directory, with optional slot_part and offset/limit. Date filtering excludes inactive, missing/false availability and reserved experts. RO users only manage/read their own region. It has no institution context; COI filtering belongs to request-specific eligibility.
- `eligibility.eligible_experts(request, date, slot_part)` consumes an immutable EligibilityRequest snapshot, returns UUID-sorted ExpertCandidates and performs no I/O/clock access. `pool.eligibility_snapshot(session, request_id)` loads own EVC tables and the pinned RulesetPort policy; a future scheduler must recheck before reserving/publishing. All COIs exclude; both proposed/published assignments reserve that date/part conservatively. YAML SAME_REGION/ANY_REGION/OTHER_REGION policy and AM/PM codes are labelled DEMO ASSUMPTION.
- Lifecycle audit events: evc.expert_registered.v1, evc.availability_set.v1, evc.coi_recorded.v1. evc_0003 adds nullable opaque personal_ref only; no user master copy or personal fields in evc.

SIMULATED authorised selector (stand-in):
- `selector.select_panel(request, date, slot_part)` is a pure deterministic selector over immutable eligibility, policy and assignment facts. It returns exactly the configured N experts or INSUFFICIENT_CANDIDATES with an empty panel. No appointment, database write or reservation occurs.
- Hard eligibility is reused before ranking. Minimum expertise matching and panel size come from the pinned `expert_pool.selector` YAML policy. Lexicographic ranking is distinct expertise matches descending, assignment workload ascending, oldest earlier assignment date (none first), then UUID ascending. Workload includes proposed/published and future commitments; rotation excludes same-day/future dates. All scored criteria and matched tags are machine-readable in the result.
- `selector_service.selector_request(session, request_id)` loads the request's pinned policy and all EVC assignment history; the future scheduler must authorize and recheck/reserve at publication. `GET /api/evc/requests/{id}/panel-preview?date=YYYY-MM-DD&slot_part=AM` exposes a read-only labelled preview to existing pool readers with case scope. RO readers require their own case and SAME_REGION policy; global readers can preview cross-region policy. Only QUEUED/PROPOSED requests are previewable.
- Code, API and documentation use the exact label **SIMULATED authorised selector (stand-in)**. Size 3, DEMO expertise tag, minimum 1 match and the ordered criteria are DEMO ASSUMPTION, not an official APH selection policy. P3 identity lookup is still absent; responses retain P3_USER_REF_UNVERIFIED. See docs/p1/selector_report.md for the controlled 100-request comparison and limitations.

Still planned:
- CP-SAT chooses **dates only**; EDF baseline for comparison; explanations for unavailable slots
- APIs: `POST /evc/schedule:propose`, `POST /evc/schedule:publish`

Capacity consumption, EDF/CPSAT integration and publication-time reservation/authorization/events remain future work. AM/PM and the availability pattern are DEMO assumptions, not an APH EVC duration or official calendar. The available extracts reference report section 23 but do not contain that section's full text.
