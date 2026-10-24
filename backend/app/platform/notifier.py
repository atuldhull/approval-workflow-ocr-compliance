"""Notification worker: delivers outbox rows written by other modules, with retries and a dead-letter state.

    python -m app.platform.notifier            # run until stopped
    python -m app.platform.notifier --once     # process what is due now, then exit

Guarantees:
- One outbox row per (alert, channel) - enforced by a unique constraint when the alert is queued.
- Claiming uses FOR UPDATE SKIP LOCKED plus a lease, so concurrent workers never take the same row, and a row
  held by a crashed worker is picked up again once its lease runs out. Nothing is lost on restart.
- Every outcome update is fenced on the claiming worker, so a worker that lost its lease cannot overwrite
  the newer result.
- In-app delivery writes the inbox row and marks the outbox row delivered in one transaction: exactly once.
- Email and SMS are at-least-once. A crash between sending and recording, or an ambiguous provider failure,
  leads to a retry, and the recipient may get the message twice.
"""
import argparse
import logging
import os
import random
import socket
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert

from app.platform.db import new_session
from app.platform.idempotency import purge_expired
from app.platform.models import DeliveryAttempt, Notification, Outbox
from app.platform.providers import (AMBIGUOUS, PERMANENT, TRANSIENT, DeliveryError, Message, MockSmsProvider,
                                    Provider, SmtpProvider, render)
from app.platform.recipients import directory
from app.platform.registry import port
from app.platform.settings import settings
from contracts.ports import ClockPort

log = logging.getLogger("notifier")
DELIVERED = "DELIVERED"

CLAIM = text("""
    UPDATE plat.outbox o
       SET status = 'SENDING', claimed_by = :worker, lease_until = :lease_until, attempts = o.attempts + 1
     WHERE o.id IN (
           SELECT id FROM plat.outbox
            WHERE (status = 'PENDING' AND (next_attempt_at IS NULL OR next_attempt_at <= :now))
               OR (status = 'SENDING' AND lease_until < :now)
            ORDER BY created_at
            LIMIT :limit
              FOR UPDATE SKIP LOCKED)
    RETURNING o.id, o.alert_id, o.channel, o.template, o.recipient_ref, o.attempts
""")


@dataclass(frozen=True)
class Claimed:
    id: UUID
    alert_id: UUID
    channel: str
    template: str
    recipient_ref: UUID
    attempts: int


class Notifier:
    def __init__(self, providers: dict[str, Provider], worker_id: str | None = None,
                 max_attempts: int | None = None, backoff_base: int | None = None, backoff_cap: int | None = None,
                 lease_seconds: int | None = None, now: Callable[[], datetime] | None = None,
                 rng: Callable[[], float] = random.random):
        self.providers = providers
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}"
        self.max_attempts = max_attempts or settings.notify_max_attempts
        self.backoff_base = backoff_base or settings.notify_backoff_base_seconds
        self.backoff_cap = backoff_cap or settings.notify_backoff_cap_seconds
        self.lease = timedelta(seconds=lease_seconds or settings.notify_lease_seconds)
        self.now = now or (lambda: port(ClockPort).now())
        self.rng = rng

    def backoff(self, attempt: int) -> timedelta:
        """Exponential, capped, with jitter in [50%, 100%] of the step so retries spread out."""
        step = min(self.backoff_cap, self.backoff_base * 2 ** max(0, attempt - 1))
        return timedelta(seconds=step * (0.5 + self.rng() / 2))

    def claim(self, limit: int = 20) -> list[Claimed]:
        now = self.now()
        with new_session() as s:
            rows = s.execute(CLAIM, {"worker": self.worker_id, "now": now, "lease_until": now + self.lease,
                                     "limit": limit}).all()
            s.commit()
        return [Claimed(*r) for r in rows]

    def run_once(self, limit: int = 20) -> int:
        claimed = self.claim(limit)
        for c in claimed:
            self.deliver(c)
        return len(claimed)

    def deliver(self, c: Claimed) -> None:
        started = self.now()
        if c.attempts > self.max_attempts:   # e.g. a message that crashed its worker every time
            self._finish(c, started, "none", PERMANENT, "ATTEMPTS_EXHAUSTED", None)
            return
        if c.channel == "in_app":
            self._deliver_in_app(c, started)
            return
        provider = self.providers.get(c.channel)
        try:
            if provider is None:
                raise DeliveryError(PERMANENT, "NO_PROVIDER_FOR_CHANNEL")
            render(c.template, c.alert_id)
            with new_session() as s:
                addresses = directory.addresses(s, c.recipient_ref, c.channel)
            if not addresses:
                raise DeliveryError(PERMANENT, "NO_RECIPIENT")
            ref = provider.send(Message(c.id, c.alert_id, c.channel, c.template, tuple(addresses), c.attempts))
        except DeliveryError as e:
            self._finish(c, started, getattr(provider, "name", "none"), e.category, e.reason, None)
        except Exception:  # noqa: BLE001 - an unexpected provider bug must not lose the message
            log.exception("provider error for outbox %s", c.id)
            self._finish(c, started, getattr(provider, "name", "none"), AMBIGUOUS, "PROVIDER_ERROR", None)
        else:
            self._finish(c, started, provider.name, DELIVERED, None, ref)

    def _deliver_in_app(self, c: Claimed, started: datetime) -> None:
        try:
            render(c.template, c.alert_id)
        except DeliveryError as e:
            self._finish(c, started, "in_app", e.category, e.reason, None)
            return
        self._finish(c, started, "in_app", DELIVERED, None, None, in_app=True)

    def _finish(self, c: Claimed, started: datetime, provider: str, outcome: str, category: str | None,
                ref: str | None, in_app: bool = False) -> None:
        now = self.now()
        if outcome == DELIVERED:
            values = {"status": DELIVERED, "delivered_at": now, "last_error": None}
        elif outcome == PERMANENT or c.attempts >= self.max_attempts:
            values = {"status": "DEAD", "dead_at": now, "last_error": category}
        else:  # TRANSIENT or AMBIGUOUS: try again later
            values = {"status": "PENDING", "next_attempt_at": now + self.backoff(c.attempts), "last_error": category}
        values |= {"claimed_by": None, "lease_until": None}

        with new_session() as s:
            fenced = s.execute(update(Outbox).where(Outbox.id == c.id, Outbox.claimed_by == self.worker_id,
                                                    Outbox.status == "SENDING").values(**values))
            if fenced.rowcount and in_app:
                s.execute(insert(Notification).values(
                    outbox_id=c.id, alert_id=c.alert_id, recipient_ref=c.recipient_ref, template=c.template,
                    created_at=now).on_conflict_do_nothing(index_elements=["outbox_id"]))
            s.add(DeliveryAttempt(outbox_id=c.id, attempt_no=c.attempts, worker=self.worker_id, provider=provider,
                                  started_at=started, finished_at=now,
                                  outcome=outcome if fenced.rowcount else f"{outcome}_LEASE_LOST",
                                  error_category=category, provider_ref=ref))
            s.commit()
        if not fenced.rowcount:
            log.warning("lease on outbox %s was lost; another worker owns it now", c.id)

    def run_forever(self, stop: threading.Event, poll_seconds: float = 2.0) -> None:
        last_purge = None
        while not stop.is_set():
            try:
                busy = self.run_once()
                if last_purge is None or self.now() - last_purge > timedelta(hours=1):
                    with new_session() as s:
                        purged = purge_expired(s)
                        s.commit()
                    last_purge = self.now()
                    if purged:
                        log.info("purged %d expired idempotency keys", purged)
            except Exception:  # noqa: BLE001 - keep the worker alive through database restarts
                log.exception("delivery loop failed; retrying")
                busy = 0
            if not busy:
                stop.wait(poll_seconds)


def requeue(outbox_id: UUID, now: datetime) -> bool:
    """Operator action: give a dead message a fresh set of attempts."""
    with new_session() as s:
        r = s.execute(update(Outbox).where(Outbox.id == outbox_id, Outbox.status == "DEAD").values(
            status="PENDING", attempts=0, next_attempt_at=now, dead_at=None, last_error=None))
        s.commit()
        return bool(r.rowcount)


def health(now: datetime) -> dict:
    with new_session() as s:
        by_status = dict(s.execute(select(Outbox.status, func.count()).group_by(Outbox.status)).all())
        oldest = s.scalar(select(func.min(Outbox.created_at)).where(Outbox.status.in_(["PENDING", "SENDING"])))
        since = now - timedelta(hours=24)
        outcomes = dict(s.execute(select(DeliveryAttempt.outcome, func.count())
                                  .where(DeliveryAttempt.finished_at >= since).group_by(DeliveryAttempt.outcome)).all())
        by_channel = [{"channel": ch, "status": st, "count": n} for ch, st, n in s.execute(
            select(Outbox.channel, Outbox.status, func.count()).group_by(Outbox.channel, Outbox.status)
            .order_by(Outbox.channel, Outbox.status)).all()]
    attempts = sum(outcomes.values())
    return {
        "by_status": {k: by_status.get(k, 0) for k in ("PENDING", "SENDING", "DELIVERED", "DEAD")},
        "by_channel": by_channel,
        "oldest_undelivered_age_seconds": int((now - oldest).total_seconds()) if oldest else None,
        "attempts_24h": outcomes,
        "first_try_success_rate_24h": None if not attempts else round(outcomes.get(DELIVERED, 0) / attempts, 3),
    }


def default_providers() -> dict[str, Provider]:
    return {
        "email": SmtpProvider(settings.smtp_host, settings.smtp_port, settings.smtp_from, settings.smtp_starttls),
        "sms": MockSmsProvider(os.environ.get("SMS_MOCK_FILE") or None),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Deliver queued notifications.")
    ap.add_argument("--once", action="store_true", help="process what is due now and exit")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    from app.main import create_app
    create_app()  # wires every module's ports (clock, ledger, ...)
    worker = Notifier(default_providers())
    if args.once:
        log.info("processed %d messages", worker.run_once(limit=1000))
        return
    stop = threading.Event()
    log.info("notifier %s started", worker.worker_id)
    try:
        worker.run_forever(stop)
    except KeyboardInterrupt:
        stop.set()


if __name__ == "__main__":
    main()
