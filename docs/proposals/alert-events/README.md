# Deadline alert events (v1) - needs three-way approval

Copies of `contracts/events/dl/alert_raised.v1.json`, `alert_escalated.v1.json` and `alert_acknowledged.v1.json`,
kept here for review by Persons 1, 2 and 3.

- Payloads hold ids, the ladder level, the addressed role, the deadline's `due_version` and closed enums only.
  No names, addresses, phone numbers or free text. The acknowledging user is the ledger event's actor.
- `dl.alert_raised.status = VACANT` records that the role group had no members at the time; nothing was queued.
- `dl.alert_escalated.reason`: `VACANCY` (explicit, from the recipient directory) or `WINDOW_ELAPSED` (the level's
  window passed without an acknowledgement). A resolver outage is never recorded as a vacancy; the timer retries.
- Delivery attempts and retries stay in the notifier's own tables and never produce a domain event.
