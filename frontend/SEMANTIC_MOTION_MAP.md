# What each figure encodes

Every figure is drawn from fields the API returned. None of them moves with scroll, and selecting in a figure only
inspects. If the source is absent, the figure is absent and the panel says why.

| Screen | Figure | Source fields | Encoding | Not inferred |
|---|---|---|---|---|
| Overview | KPI row | `/applications`, `/deadlines?subject_id=`, `/compliance/obligations?status=OPEN` | Counts of returned rows; earliest running due date | No estimated totals |
| Overview, Cases | Route track / route stepper | `route[].stage`, `route[].when`, `current_stage`, `status` | One step per returned stage; current amber; conditional dashed; earlier stages "before current" | Stage completion, deficiency loops |
| Overview | Stage counts | `current_stage` of in-process applications | Dot size ∝ count; count printed | — |
| Case | Date axis | `submitted_at`, `deadlines[].due_date` | Spacing ∝ time between dates; event square vs due circle | Start dates, statutory durations |
| Case | Audit timeline | `/cases/:id/timeline` `seq`, `event_type`, `role`, `at` | One entry per recorded event | Unrecorded transitions |
| Dashboard | Pendency matrix | `/dashboards/pendency` `rows[region, stage, count]` | Cell tint ∝ count; one row per returned region | Absent regions, absent stages |
| Dashboard | Bars | `sections[].data` (`by_stage`, `by_region`, `buckets`, `by_rule`) | Bar length ∝ value; value printed | Per-region status, officer workload |
| Documents, Fact review | Reading surface | `/document-versions/:id/content` for an AVAILABLE image version | The stored page image itself | Nothing is fetched for quarantined/blocked versions; PDFs open in a tab |
| Fact review | Review progress | `review_status` counts | Counts per review state | Machine values (never on the surface before the reviewer's entry) |
| Compliance | Due-date axis | `obligations[].due_date`, `status` | One marker per date; obligations due that day stacked; outline amber open, blue unverified, green met | Overdue status (the server's status is shown as given) |
| Compliance | Who-does-what list | `status`, `evidence[]` | Institution submits → officer decides → met only on acceptance | Acceptance from submission |
| Alerts | Escalation ladder | `level`, `status` | One rung per level up to this alert; this rung coloured by status | Future escalations |
| Alerts, Inbox, Delivery | Lifecycle strip | — (fixed explanation) | The screen's own step marked | Any progress |
| Delivery | State counts | `/notifications/health` `by_status` | Count per state; dead letters dashed | Transitions between states |
| Delivery | Attempts | `/notifications/outbox/:id/attempts` | One entry per recorded attempt, in order | Elapsed time, simulated sends |
| Scorecard | Instrument rows | `items[]` `kind`, `method`, `result`, `finding`, `outcome` | Check → method → found → outcome; side rule coloured by outcome | A verdict for a measurement that has none |
| Case | Action list | `/cases/:id` `available_actions[]` (`enabled`, `reason_code`, `targets`), `version` | One row per listed action; blocked rows folded with their reason | Actions the server did not list; why a guard failed beyond its code |
| Case | Checklist | `/applications/:id/checklist` `items[]`, `dsc_required`, `dsc_present`; `/applications/:id/documents` | One row per item with its state; picker of AVAILABLE versions only | Completeness the server did not report |
| Case | Deficiency rounds | `/cases/:id/deficiencies` `rounds[].items[]`, `response_window` | One block per round, one row per item with its state and response document | Review outcomes before they are recorded |
| Case | Committee workspace | `wf.committee_formed` timeline events, then `/committees/:id` and `/committees/:id/reports` | One block per committee; tasks, observation counts, report versions with fingerprints | Note text (protected notes; only hashes are returned) |
| Case | Expert visit | `/evc/queue` row for the case | Status, window, waiting days, allowed days (demo assumption) | Visit date and panel (no per-case read) |
| EVC | Queue | `/evc/queue` | One row per request, ordered as returned (deadline first) | Requests outside the caller's scope |
| EVC | Proposal | `POST /evc/schedule:propose` `metrics`, `proposals[]`, `unscheduled[]`, `solver` | KPI row; one row per proposed visit; solver facts as given | Expert identities (opaque references only) |
| EVC | Comparison | Proposals made in this tab | One row per run with the shared metrics; input fingerprint shown | A fair comparison between runs with different fingerprints |
| Audit | Layer panels | `/ledger/verify`, `/audit/verify`, `POST /audit/replay` | One panel per independent layer with its own result | A combined assurance stronger than the weakest layer |
| Audit | Checkpoint history | `/audit/checkpoints` | One entry per signed checkpoint, newest first; filled mark = published | Ledger events (no ledger-wide listing exists) |
| Audit | Spatial figure | Layer states from `auditRecords()` | Chain (continuity), seal (witness; open ring when same-machine demo), loop (replay); teal/brass/amber/red/stone by recorded state | Link count is a fixed motif, not the number of entries |

## Audit layer states

| Layer | States |
|---|---|
| Continuity | checked (intact) · broken (first broken sequence shown) · unknown (not checked) |
| Witness | anchored (intact chain, checkpoint, configured witness) · recorded (same-machine demo witness) · unknown |
| Replay | checked (verified complete) · broken (mismatch) · unknown (not run, or covered only in part) |

The overall verdict (`headline()` in `AuditView.jsx`) is green only when the chain is intact, anchored through the
latest entry, and replay verified complete; any failure in any layer makes it red.
