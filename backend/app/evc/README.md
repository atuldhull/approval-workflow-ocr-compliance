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

Still planned:
- Panels come from a labelled stand-in for the authorised selector (APH 1.8(a): automated, not random)
- CP-SAT chooses **dates only**; EDF baseline for comparison; explanations for unavailable slots
- APIs: `GET /evc/queue`, `POST /evc/schedule:propose`, `POST /evc/schedule:publish`
- Opens the EVC clock through `DeadlinePort`

This task adds storage/constraints and master-data bootstrap only. Capacity consumption, availability/COI/active-expert guards, selector integration, EDF/CPSAT optimization, publishing authorization/events and queue endpoints remain future work. AM/PM and the availability pattern are DEMO assumptions, not an APH EVC duration or official calendar. The available extracts reference report section 23 but do not contain that section's full text.
