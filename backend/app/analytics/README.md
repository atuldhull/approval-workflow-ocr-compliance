# analytics (Person 3)

- `projections.py` - read models rebuilt from `plat.domain_event` (applications, deadlines). Registered for replay
  in `wiring.py`; replay compares them with the live tables (`POST /api/audit/replay`).
- `service.py` - `GET /api/analytics/dashboard`: totals, stages, regions, ageing, deadlines, alert delivery. A regional
  officer always gets their own region. Sections without data are `NOT_AVAILABLE` with the dependency named.
- `scorecard.py` - `GET /api/analytics/scorecard`: ledger integrity and replay (verified now), delivery (measured on
  demo traffic), routing and OCR (only when an answer key exists in `ANSWER_KEYS_DIR`).

Dashboards replay the event log on each request. That is fine for demo volumes. If it becomes slow, persist the
projections in schema `an` and update them incrementally; the replay check keeps them honest.
