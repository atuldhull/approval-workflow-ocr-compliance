# What Person 3's platform needs from Persons 1 and 2

Everything below is built and tested on Person 3's side; each item names the exact change on the other side.

## Person 1 (workflow, intake, EVC)

| # | Change | Where | Unlocks |
|---|---|---|---|
| P1-1 | Use the idempotency helper on create and submit (patch in `docs/IDEMPOTENCY.md`) | `backend/app/intake/api.py` | Safe retries end to end (the UI already sends `Idempotency-Key`) |
| P1-2 | For regional officers, filter `GET /applications` by `principal.region` and pass `ResourceRef("application", region=principal.region)` | `intake/api.py` `list_applications` | Regional officers get a case list (refused today, by design) |
| P1-3 | Pass `region=` (from `CasePort.lookup`) in `ResourceRef` for `GET /applications/{id}` | `intake/api.py` `get_application` | Regional officers can open single cases |
| P1-4 | Emit events for stage transitions, deficiencies and decisions; extend `ApplicationsProjection` or register a projector in `workflow/wiring.py` | `contracts/events/wf/`, `analytics/projections.py` | Dashboards and replay beyond the first stage |
| P1-5 | Assignment data and, after C3 is approved, `stage` / `assigned_to` in `ResourceRef` | workflow module | Committee members limited to their assigned cases |
| P1-6 | EVC request and slot events plus an API | `evc/` | EVC queue on the dashboard; the EVC screen leaves preview |

## Person 2 (documents, compliance, deadlines, alerts)

| # | Change | Where | Unlocks |
|---|---|---|---|
| P2-1 | Queue alerts with `port(OutboxPort).enqueue(uow, OutboundMessage(alert_id, channel, template, recipient_ref))` in the alert's transaction; templates from `platform/providers.py` `TEMPLATES` (ask to add more) | alerts code | Delivery, retries, inbox, delivery metrics - already working for any queued row |
| P2-2 | Use `group_ref(role, region, institution)` (or `RecipientPort` after C2) for `recipient_ref`; check `has_members` to escalate vacancies | alerts code | Role-based delivery without contact details |
| P2-3 | Events for deadline closure, pause, resume and extension (e.g. `dl.deadline_closed`) | `contracts/events/dl/` | Overdue vs met on dashboards; replay can compare deadline status |
| P2-4 | For regional officers, filter `GET /deadlines` by region and pass `region=` | `deadlines/api.py` | Regional officers can list deadlines (refused today, by design) |
| P2-5 | Alert acknowledgement endpoint | alerts module | The disabled "Acknowledge" button in the inbox |
| P2-6 | Fact proposal / confirmation API with the type-then-reveal rule | documents module | The document review screen leaves preview (UI already enforces commit-before-reveal) |
| P2-7 | Obligation and evidence API and events | compliance module | Compliance screen and dashboard section |
| P2-8 | `generator/answer_keys/ocr.json` (expected vs predicted per field) and an expected-alerts key | `generator/` | OCR and alert rows of the scorecard |

## Time

The notifier and the idempotency expiry read time from `ClockPort`. In the API process that includes demo time
travel; the separate worker process has its own clock without the offset, so in a time-travel demo run the worker
with `--once` from the API container if delays must follow simulated time.
