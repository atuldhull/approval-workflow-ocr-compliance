# Notification delivery

## Who does what

| | Person 2 | Person 3 |
|---|---|---|
| Decide an alert exists, when, for which role, escalation, acknowledgement | yes | |
| Queue it: `port(OutboxPort).enqueue(uow, OutboundMessage(alert_id, channel, template, recipient_ref))` inside the same unit of work | yes | |
| Resolve `recipient_ref` to people and addresses, send, retry, dead-letter, inbox, delivery metrics | | yes |
| Messages about recorded events (deficiency recorded, EVC visit published, evidence decided, letter registered, clock breached): read from the event log and queued by the worker per `rulesets/<ruleset>/<rev>/notifications.yaml` | | yes |

## Messages about recorded events (`backend/app/platform/event_notices.py`)

An outbox row is about exactly one thing: a deadline alert (`alert_id`) or a recorded domain event
(`source_event_id`), enforced by a check constraint. Each worker loop first reads the event log from its cursor
(`plat.notify_cursor`), looks each event type up in the ruleset's `notifications.yaml` (template, recipient roles,
channels and, optionally, the deadline rule whose live clock gives the due date) and queues one row per event,
recipient group and channel. The unique constraint `(source_event_id, recipient_ref, channel)` and the cursor moving
in the same transaction make re-reading harmless. Ledger appends are serialised until commit, so no event at or
below the newest visible one can still appear. Vacant groups are skipped: an event message has no ladder.

The map is part of the ruleset revision (it is in the source checksum). It is a demo assumption: the APH does not
say who is told about what. Adding an event (for example a document-expiry event) is one entry under `events:`;
a template can name a document (`{document}`), and alerts on document clocks already name it.

## How delivery works (`backend/app/platform/notifier.py`)

```
outbox row PENDING --claim (lease)--> SENDING --send ok--------------------> DELIVERED
                                         |--temporary / ambiguous failure--> PENDING (retry after backoff)
                                         |--permanent failure or attempts exhausted--> DEAD
     SENDING with an expired lease (worker crashed) --> claimed again by any worker
```

- **Claiming:** `UPDATE ... WHERE id IN (SELECT ... FOR UPDATE SKIP LOCKED)` with a lease (`NOTIFY_LEASE_SECONDS`, 120).
  Concurrent workers never take the same row. A row whose worker crashed is retried after the lease runs out, so
  nothing is lost on restart.
- **Fencing:** a worker records its result only if it still holds the claim. A late worker cannot overwrite a newer
  result; its attempt is logged as `<OUTCOME>_LEASE_LOST`.
- **Retries:** exponential backoff from `NOTIFY_BACKOFF_BASE_SECONDS` (30), capped at `NOTIFY_BACKOFF_CAP_SECONDS`
  (3600), with jitter (50-100 % of the step), up to `NOTIFY_MAX_ATTEMPTS` (6). Then the row is DEAD.
- **Every attempt** is a row in `plat.delivery_attempt` (worker, provider, start and end time, outcome,
  error category). Provider error text is never stored, only a category.
- **Dead letters** are listed at `GET /api/notifications/outbox?status=DEAD`; the bureau head can requeue one with
  `POST /api/notifications/outbox/{id}/retry`.
- **One message per recipient:** email and SMS go to each recipient separately, so nobody sees another recipient's
  address. Each recipient's result is stored in `plat.delivery_recipient` as a keyed digest
  (HMAC-SHA256 with `NOTIFY_RECIPIENT_KEY`, prefix `h1:`) of (message id, address), never the address. A retry only goes to recipients not yet reached; a recipient the
  provider refused is not retried. If some recipients are refused and the rest delivered, the message is DEAD with
  `SOME_RECIPIENTS_REFUSED` for a person to look at.
- **Metrics:** `GET /api/notifications/health` shows counts by status and channel, the age of the oldest undelivered
  message, attempt outcomes in the last 24 hours, `first_try_success_rate_24h` (share of messages whose very first
  attempt in the window delivered; a manual requeue does not create a new first try) and `delivered_after_retry_24h`.
- Provider errors are logged by type only; provider text can contain addresses.
- **Only a recipient-specific refusal marks a recipient.** A message- or provider-level failure (not configured,
  unknown template, SMTP 5xx after the data, outage) stops the run for the whole message and blames nobody.
- **Lease renewal:** before each recipient the worker extends its lease; if another worker has taken the message
  over, it stops instead of sending alongside it.
- **Requeue** (bureau head) gives refused recipients a fresh try and never resends to recipients already reached.
- **A send longer than the lease:** `smtplib`'s timeout applies per socket operation and one send makes about eight
  of them, so a slow server can hold a send for up to ~8 x `SMTP_TIMEOUT_SECONDS`. Startup refuses
  `NOTIFY_LEASE_SECONDS` below 10 x `SMTP_TIMEOUT_SECONDS` (defaults: 120 s and 10 s). If a send still outlives the
  lease (e.g. a stalled process), another worker reclaims the message and may send to that recipient again; the
  first worker records its result and then stops at its next lease check. That is the at-least-once case, not data loss.
- **Health** also reports `stalled_sending` (SENDING past its lease: a worker stopped), `lease_lost_24h` and whether
  email is configured, so a missing mail server is visible before messages pile up as dead letters.

### Recipient digest key

A plain hash of a known message id and a guessable address could be confirmed by anyone able to read the table,
even after the address was erased from `personal_data`. The digest is therefore keyed. `NOTIFY_RECIPIENT_KEY`
(32+ characters, from a secret store) is required when `APP_ENV=production`; development falls back to a fixed,
documented key. Compatibility: rows written before this change hold an unkeyed SHA-256; they are still read, so
in-flight retries do not resend to recipients already reached, but nothing new is written that way. No migration
is needed. Rotating the key makes earlier rows unmatchable, so rotate only when no message is mid-retry, or accept
that such messages may reach a recipient twice (at-least-once).
- The worker also purges expired idempotency keys once an hour.

## Delivery guarantees - what is and is not promised

| Guarantee | Holds? |
|---|---|
| One logical message per (alert, channel) | Yes - unique constraint when queued |
| One logical message per (event, recipient group, channel) | Yes - unique constraint when queued |
| In-app notification shown once | Yes - inbox row and DELIVERED status commit together |
| Email / SMS sent at least once to each recipient (until DEAD) | Yes |
| A recipient sees other recipients' addresses | No - one message per recipient |
| Email / SMS sent exactly once | **No.** If the worker crashes after the provider accepted the message but before recording it, or the provider times out after receiving it (`AMBIGUOUS`), the message is sent again. A crash between one recipient's send and its record repeats that one send. Emails reuse the same `Message-ID` per (message, recipient) on retries, which some mail systems use to drop duplicates. |

## Channels (`backend/app/platform/providers.py`)

| Channel | Provider | Notes |
|---|---|---|
| `in_app` | database | Inbox at `GET /api/notifications/inbox` |
| `email` | SMTP (`SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM`, `SMTP_STARTTLS`) | Local demo uses Mailpit (http://localhost:8025): nothing leaves the machine |
| `sms` | Mock: writes to `SMS_MOCK_FILE` (JSONL) or memory | No real gateway is called |
| tests | `FakeProvider` with scripted outcomes | |

Message texts are fixed per template (`TEMPLATES`). When delivered, a message is filled from what it is about - the
alert and its deadline, or the event - with the short case reference (first 8 characters of the case id), the rule in
words (`rule_names` in notifications.yaml), the due date in IST and what to do. Only ids, kinds and dates are used:
no names, addresses or free text. If the record cannot be read, the generic sentence of the template is sent.

## Recipients (`backend/app/platform/recipients.py`)

`recipient_ref` is an opaque id: one user, or a role group such as "regional officers, Southern". Group ids are
deterministic (`group_ref(role, region, institution)`), so they never change with staffing and replay is unaffected.
Addresses live in `plat.personal_data` (erasable) and are looked up only at delivery time. A group with no
members is a vacancy: delivery fails as `NO_RECIPIENT` (dead letter), and Person 2 can avoid it by checking first.

### Proposed contract addition (needs all three approvals)

```python
# contracts/ports.py, "provided by the platform module"
@runtime_checkable
class RecipientPort(Protocol):
    def resolve(self, role: Role, resource: ResourceRef) -> UUID: ...           # opaque role-group id
    def has_members(self, session: Session, recipient_ref: UUID) -> bool: ...   # False = vacant, escalate
```

Implemented today by `app.platform.recipients.RecipientDirectory`; a `FakeRecipients` would be added to
`contracts/fakes.py` in the same pull request. Until it is approved, Person 2 can queue alerts with any
`recipient_ref` and the worker will deliver to whatever the directory holds.

## Running it

```bash
docker compose --profile worker up                       # worker next to the default stack
python -m app.platform.notifier --once                   # from backend/, with PYTHONPATH=..;.
python -m app.platform.demo_seed --sample-alerts         # DEMO_MODE only: queue messages about events already recorded
```
