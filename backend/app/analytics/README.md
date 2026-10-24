# analytics (Person 3)

- `projections.py` - read models rebuilt from `plat.domain_event` (applications, deadlines). Registered for replay
  in `wiring.py`; replay compares them with the live tables (`POST /api/audit/replay`).
- `service.py` - `GET /api/analytics/dashboard`: totals, stages, regions, ageing, deadlines, alert delivery. A regional
  officer always gets their own region. Sections without data are `NOT_AVAILABLE` with the dependency named.
- `scorecard.py` - `GET /api/analytics/scorecard`: ledger integrity and replay (verified now), delivery (measured on
  demo traffic), routing and OCR (only when an answer key exists in `ANSWER_KEYS_DIR`).

Dashboards keep the event projections in a per-process cache that is rebuilt when the event log changes (newest
event id, sequence and count, read in one REPEATABLE READ snapshot with the events). Regions are not cached: they
come from the workflow module and can change without an event, so each request resolves them through `CasePort`,
one lookup per institution. Ageing and due dates are
recomputed on every request from the cached projections. Events whose application has no case record are counted
nationally under "Unknown" and make the section PARTIAL; regional views exclude them. An event a projection cannot
read is skipped and reported (dashboard PARTIAL, replay MISMATCH) instead of failing the request.

A rebuild still replays the whole log, which is fine for demo volumes. If it becomes slow, persist the projections
in schema `an` and update them incrementally; the replay check keeps them honest.
