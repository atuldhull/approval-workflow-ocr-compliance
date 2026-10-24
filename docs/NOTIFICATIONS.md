# Notification delivery

## Who does what

| | Person 2 | Person 3 |
|---|---|---|
| Decide an alert exists, when, for which role, escalation, acknowledgement | yes | |
| Queue it: `port(OutboxPort).enqueue(uow, OutboundMessage(alert_id, channel, template, recipient_ref))` inside the same unit of work | yes | |
| Resolve `recipient_ref` to people and addresses, send, retry, dead-letter, inbox, delivery metrics | | yes |

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
  address. Each recipient's result is stored as a salted SHA-256 of (message id, address) in
  `plat.delivery_recipient`, never the address. A retry only goes to recipients not yet reached; a recipient the
  provider refused is not retried. If some recipients are refused and the rest delivered, the message is DEAD with
  `SOME_RECIPIENTS_REFUSED` for a person to look at.
- **Metrics:** `GET /api/notifications/health` shows counts by status and channel, the age of the oldest undelivered
  message, attempt outcomes in the last 24 hours, `first_try_success_rate_24h` (share of messages whose very first
  attempt in the window delivered; a manual requeue does not create a new first try) and `delivered_after_retry_24h`.
- Provider errors are logged by type only; provider text can contain addresses.
- The worker also purges expired idempotency keys once an hour.

## Delivery guarantees - what is and is not promised

| Guarantee | Holds? |
|---|---|
| One logical message per (alert, channel) | Yes - unique constraint when queued |
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

Message texts are fixed per template (`TEMPLATES`). They contain only a reference id and ask the user to sign in;
no names, case details or free text, so nothing from an event payload can reach a message.

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
python -m app.platform.demo_seed --sample-alerts         # DEMO_MODE only: queue 3 synthetic alerts on 3 channels
```
