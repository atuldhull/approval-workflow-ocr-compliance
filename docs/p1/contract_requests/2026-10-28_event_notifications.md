# Messages about recorded events, not only alerts — three-way approval request

Date: 28 October 2026. P3. Status: **approved by Person 1, Person 2 and Person 3 on 2026-10-28**. The shared type, the migration and the regenerated OpenAPI are committed on their own so they can be reviewed, approved or reverted independently of the notifier code.

## Why this is needed

Only deadline alerts produced messages, every outbox row needed an `alert_id`, and every text was generic ("A deadline on a case you handle is approaching."). The problem statement asks for contextual notifications when something happens on a case (F1): a deficiency recorded, an EVC schedule published, evidence decided, a letter issued, a deadline missed. `demo_seed --sample-alerts` also queued messages with random alert ids that led nowhere.

## Shared type (`contracts/types.py`)

```text
OutboundMessage(alert_id: UUID | None, channel, template, recipient_ref, source_event_id: UUID | None = None)
```

Exactly one of `alert_id` and `source_event_id` is set; the constructor refuses both or neither. Existing callers (`OutboundMessage(alert_id, channel, template, ref)`) are unchanged: alert messages work exactly as before. `OutboxPort` and `FakeOutbox` keep their signatures.

## Migration `plat_0007_event_notifications`

- `plat.outbox.alert_id` becomes nullable; new `source_event_id uuid`; unique `uq_plat_outbox_event_recipient_channel (source_event_id, recipient_ref, channel)`; check `ck_plat_outbox_one_subject`: exactly one of `alert_id`, `source_event_id`. The existing unique `(alert_id, channel)` stays.
- `plat.notification.alert_id` becomes nullable; new `source_event_id uuid` and `context jsonb` (case reference, rule, due date and links, worked out once at in-app delivery; ids, kinds and dates only).
- New table `plat.notify_cursor (name text primary key, seq bigint, updated_at timestamptz)`: how far the notifier has read the event log.
- No existing row is rewritten. Downgrade deletes event messages first, then restores `NOT NULL`.

## Ruleset file `rulesets/aph-2024-27/r1/notifications.yaml`

Event type → template, recipient roles (`owner` = the role that owns the clock in the event), optional channels and the deadline rule whose live clock gives the due date; plus `rule_names`, the rules in words. Shipped map (demo assumption — the APH does not say who is told what): `wf.deficiency_recorded` → institution; `evc.assignment_published` → institution and scrutiny committee; `cmp.evidence_verified` → institution (accepted or rejected wording by `decision`); `cmp.letter_registered` → institution; `dl.deadline_breached` → owner role. The file is added to the ruleset source manifest (`workflow/loader.py`), so the r1 checksum changes; accepted for this sprint.

## Generated OpenAPI

Refreshed with `python scripts/check_contracts.py --write` (Python 3.12), no hand edits:

- `InboxItem`: `alert_id` nullable; new `source_event_id`, `text` (what happened: case, rule in words, due date in IST), `action` (what to do), `case_ref`, `links {application_id, obligation_id, evc_request_id}`.
- `OutboxItem`: `alert_id` nullable; new `source_event_id`.

## Behaviour

- The notifier loop reads new events from its cursor, queues one row per event, recipient group and channel, and moves the cursor in the same transaction; re-reading queues nothing twice. Vacant groups are skipped. Delivery, retries, dead letters and the per-recipient digests are unchanged.
- Every template has a contextual form and keeps its generic sentence as the fallback when the record cannot be read. Alert messages now name the case, the rule and the due date too. A template can name a document (`{document}`), read from the deadline's subject when it is a document.
- `demo_seed --sample-alerts` no longer invents alert ids: it queues the mapped messages for events already in the log and a "case updated" message for the latest submitted applications. With an empty log it queues nothing.
- Regional alert-delivery figures on the dashboard still count alert messages only (they are joined to the alert's region).

## Impact if refused

Reverting the type and migration means reverting the notifier change with them; alert delivery would return to generic texts and the inbox to alerts only.
