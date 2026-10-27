# analytics (Person 3)

- `projections.py` - read models rebuilt from `plat.domain_event` (applications, deadlines). Registered for replay
  in `wiring.py`; replay compares them with the live tables (`POST /api/audit/replay`).
- `service.py` - `GET /api/analytics/dashboard`: totals, stages, regions, ageing, deadlines, alert delivery. A regional
  officer always gets their own region. Sections without data are `NOT_AVAILABLE` with the dependency named.
- `scorecard.py` - `GET /api/analytics/scorecard`. Every item has `kind` and `method` (how it was measured) apart
  from `result`, `outcome` (PASS / ATTENTION / FAIL, or none for a plain measurement) and `finding`:
  - verified now over every live record: ledger integrity, replay, document scanning (verdict counts; no version used
    by extraction, evidence or a letter before it was clean), four-eyes (no fact confirmed by its own reviewer or
    without a review; no evidence decided by an automated actor);
  - measured on demo traffic: alert delivery in the last 24 hours (notifier attempt ledger), alert timeliness (ladder
    levels that fell due vs alerts raised in `dl.alert`: missed, duplicate, early), OCR agreement (the officer's blind
    entry vs the OCR value; `ocr.json` in `ANSWER_KEYS_DIR` replaces it when present);
  - routing vs APH Table 2.3 stays NOT_EVALUATED until the workflow owner supplies `routing.json`.
  Document, compliance and deadline tables are only read, never written.

Dashboards keep the event projections in a per-process cache that is rebuilt when the event log changes (newest
event id, sequence and count, read in one REPEATABLE READ snapshot with the events). Regions are not cached: they
come from the workflow module and can change without an event, so each request resolves them through `CasePort`,
one lookup per institution. Ageing and due dates are
recomputed on every request from the cached projections. Events whose application has no case record are counted
nationally under "Unknown" and make the section PARTIAL; regional views exclude them. An event a projection cannot
read is skipped and reported (dashboard PARTIAL, replay MISMATCH) instead of failing the request.

A rebuild still replays the whole log, which is fine for demo volumes. If it becomes slow, persist the projections
in schema `an` and update them incrementally; the replay check keeps them honest.
