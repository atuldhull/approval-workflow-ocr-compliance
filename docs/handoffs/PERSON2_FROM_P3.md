# Requests to Person 2 from Person 3

These are requests, not changes: nothing in Person 2's folders has been edited. Items marked **contract** need all
three approvals.

## 1. Queue alerts through the outbox

- **Exists:** `port(OutboxPort).enqueue(uow, OutboundMessage(alert_id, channel, template, recipient_ref))`; the worker
  delivers, retries, dead-letters, keeps per-recipient privacy, and reports metrics (`docs/NOTIFICATIONS.md`).
- **Needed:** call it inside the same unit of work that creates the alert, once per channel (`in_app`, `email`, `sms`).
- **In:** `template` must be a key of `TEMPLATES` in `backend/app/platform/providers.py` (ask me to add more; texts
  never carry case details). `alert_id` is your alert's id; `(alert_id, channel)` is deduplicated.
- **Acceptance:** an alert created in a transaction that rolls back queues nothing; a committed one shows up in the
  recipient's inbox after `python -m app.platform.notifier --once`.
- **Delivery semantics you can rely on:** one message per recipient; a refused recipient does not block the others;
  an outage or misconfiguration dead-letters the message without blaming recipients, and a bureau-head requeue retries
  only recipients not yet reached. Email and SMS are at-least-once.
- **Contract:** no.

## 2. Address alerts to role groups, and escalate vacancies

- **Exists:** `app.platform.recipients.group_ref(role, region, institution)` and `directory.has_members(session, ref)`.
- **Needed:** use the group id as `recipient_ref`; if `has_members` is False, escalate within the same transaction.
- **Security:** never put addresses or names in alerts, events or outbox rows.
- **Acceptance:** an alert for a vacant group escalates instead of ending as a `NO_RECIPIENT` dead letter.
- **Contract:** yes, if you want it as `RecipientPort` (C2), which matches your interface-resolution note.

## 3. Deadline status events

- **Needed:** events for closure (met / breached / waived), pause, resume and extension, e.g. `dl.deadline_closed`
  with `deadline_id`, `outcome`, `closed_on`.
- **Then:** I extend `DeadlinesProjection` to compare status, and the dashboard's deadline section stops being PARTIAL.
- **Contract:** yes (event schemas).

## 4. Region filtering on the deadline list

- **Needed:** for `RO_OFFICER`, filter `GET /deadlines` by the subject's region and check
  `ResourceRef("deadline", region=principal.region)`. **Acceptance:** Southern officer sees Southern deadlines only.
  **Contract:** no.

## 5. Alert acknowledgement

- **Needed:** `POST` to acknowledge an alert (who, when), with your escalation logic. **Then:** I enable the disabled
  "Acknowledge" button in the inbox. **Contract:** yes (OpenAPI).

## 6. Document review and fact confirmation (commit-before-reveal at the API)

The UI already talks to `frontend/src/integrations/documentReview.js`. The API needs to provide:

| Call | Returns | Rule |
|---|---|---|
| `GET /documents/{id}/review` | title, `synthetic` flag, page images (`imageUrl`, `width`, `height`), fields (`key`, `label`, `format`) | **No suggestions, confidence, boxes or OCR text** |
| `POST /documents/{id}/fields/{key}/reading` with the officer's value | `value`, `confidence`, `box` (page, x, y, w, h in image pixels), `sourceText` | Records the officer's reading **first**, then returns the machine reading |
| `POST /documents/{id}/facts/confirm` with `[{fieldKey, value, source: OFFICER\|MACHINE}]` for every field | `{confirmed: [{fieldKey, factId}]}` listing **every** field | All-or-nothing; only fields the same user already committed a reading for; `MACHINE` only for a field whose suggestion was revealed to that user |

- **Security:** enforce the order on the server too; the UI hiding values is not enough. Page images must be the
  original document, not text re-rendered from OCR.
- **Acceptance:** a review request contains no machine output; a confirm before a reading is 409; a confirm that
  cannot save every field saves none. The UI shows success only if `confirmed` lists every submitted field
  (`confirmedAll` in `frontend/src/integrations/documentReview.js`), and sends one request per confirmation.
- **Contract:** yes (OpenAPI).

## 7. Obligations and evidence

- **Needed:** list obligations per institution (kind, title, due date, evidence, state) and a review action, plus events.
  **Then:** the compliance screen leaves preview and the dashboard section becomes available. **Contract:** yes.

## 7b. A read-only view for replay

- **Exists today (disclosed):** `DeadlinesProjection.live()` in `backend/app/analytics/projections.py` runs a
  read-only `SELECT id, subject_type, subject_id, rule_id, clock_kind, clock_owner, due_date FROM dl.deadline`.
- **Needed:** approve it as a stable read-only interface, or provide a view (e.g. `dl.v_deadline`) or a port method.
  **Contract:** yes, if it is a port.

## 8. Answer keys for the scorecard

- **Needed:** `generator/answer_keys/ocr.json` (`cases: [{id, field, expected, predicted}]`, with `predicted` from your
  real pipeline) and an expected-alerts key. The scorecard only reports accuracy when these exist.
- **Contract:** no.
