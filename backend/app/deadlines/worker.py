"""Deadline timer worker: fires due ladder levels from persisted state.

    python -m app.deadlines.worker                     # run until stopped, polling every 5 s when idle
    python -m app.deadlines.worker --poll-seconds 10   # poll interval when nothing was due
    python -m app.deadlines.worker --once              # process what is due now, then exit

Guarantees:
- The schedule lives in dl.deadline.next_fire_at; nothing is held in memory, so a restart loses nothing and a
  worker that was down catches up on its next run.
- Claiming uses FOR UPDATE SKIP LOCKED plus a lease and a fence (timer_fence, bumped on every claim), mirroring
  the platform notifier. Overlapping runs never take the same deadline; a deadline held by a crashed worker is
  claimed again once its lease runs out.
- Processing one deadline is one transaction, fenced on the claim: its alerts, ledger events, outbox rows,
  the new next_fire_at and the timer outcome commit together or not at all. A crash leaves the work retryable.
- Alerts are unique on (deadline_id, level, due_version), so even a fencing failure cannot raise one twice.
- A running clock found past its due time is marked BREACHED (dl.deadline_breached, once per due_version) before
  alerts are fired. A breached clock keeps its alert ladder; pausing or closing it is up to the workflow.
- Time comes only from ClockPort, so demo time travel moves the schedule.
"""
import argparse
import logging
import os
import socket
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select, text, update

from app.deadlines.alerts import AlertEngine, ResolverUnavailable, alert_config
from app.deadlines.alerts import engine as default_engine
from app.deadlines.models import Deadline, TimerOutcome
from app.deadlines.service import DeadlineEngine
from app.platform.db import new_session, unit_of_work
from app.platform.registry import port
from contracts.enums import DeadlineStatus, Role
from contracts.ports import ClockPort
from contracts.types import Principal

log = logging.getLogger("deadline-timer")
SYSTEM = Principal(UUID(int=0), Role.SYSTEM)
DEFAULT_RETRY = timedelta(minutes=15)

CLAIM = text("""
    UPDATE dl.deadline d
       SET timer_claimed_by = :worker, timer_lease_until = :lease_until,
           timer_fence = d.timer_fence + 1, timer_attempts = d.timer_attempts + 1
     WHERE d.id IN (
           SELECT id FROM dl.deadline
            WHERE status IN ('RUNNING', 'BREACHED') AND next_fire_at <= :now
              AND (timer_lease_until IS NULL OR timer_lease_until < :now)
            ORDER BY next_fire_at
            LIMIT :limit
              FOR UPDATE SKIP LOCKED)
    RETURNING d.id, d.timer_fence, d.next_fire_at, d.timer_attempts
""")


@dataclass(frozen=True)
class Claim:
    deadline_id: UUID
    fence: int
    scheduled_at: datetime | None
    attempts: int


class TimerWorker:
    def __init__(self, worker_id: str | None = None, lease_seconds: int = 120, max_attempts: int = 10,
                 now: Callable[[], datetime] | None = None, engine: AlertEngine | None = None):
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}"
        self.lease = timedelta(seconds=lease_seconds)
        self.max_attempts = max_attempts
        self.now = now or (lambda: port(ClockPort).now())
        self.engine = engine or default_engine

    def claim(self, limit: int = 50) -> list[Claim]:
        now = self.now()
        with new_session() as s:
            rows = s.execute(CLAIM, {"worker": self.worker_id, "now": now, "lease_until": now + self.lease,
                                     "limit": limit}).all()
            s.commit()
        return [Claim(*r) for r in rows]

    def mark_breached(self, limit: int = 50) -> int:
        """Mark running clocks whose due time has passed BREACHED, in batches; each batch is one transaction.
        Rows another transaction holds are skipped and picked up on the next run. Returns how many were marked."""
        marked = 0
        while True:
            now = self.now()
            with unit_of_work(SYSTEM) as uow:
                rows = uow.session.scalars(select(Deadline).where(
                    Deadline.status == DeadlineStatus.RUNNING, Deadline.due_at < now)
                    .order_by(Deadline.due_at).limit(limit).with_for_update(skip_locked=True)).all()
                batch = sum(DeadlineEngine().breach(uow, d) for d in rows)
            marked += batch
            if len(rows) < limit:
                return marked

    def run_once(self, limit: int = 50) -> int:
        """Process what is due now. Returns the number of deadlines whose alert timers were processed by this
        worker (clocks it only marked BREACHED are not counted)."""
        try:
            breached = self.mark_breached(limit)
            if breached:
                log.info("marked %d deadline(s) breached", breached)
        except Exception as e:  # noqa: BLE001 - alerts still fire; the next run marks them
            log.error("marking breached deadlines failed: %s", type(e).__name__)
        done = 0
        for c in self.claim(limit):
            done += self.process(c)
        return done

    def process(self, c: Claim) -> int:
        now = self.now()
        try:
            with unit_of_work(SYSTEM) as uow:
                d = uow.session.scalar(select(Deadline).where(
                    Deadline.id == c.deadline_id, Deadline.timer_fence == c.fence,
                    Deadline.timer_claimed_by == self.worker_id).with_for_update())
                if d is None:
                    log.warning("claim on deadline %s was lost; another worker owns it now", c.deadline_id)
                    return 0
                if c.attempts > self.max_attempts:
                    self._finish(uow, d, c, now, "FAILED", 0, None, "ATTEMPTS_EXHAUSTED")
                    return 1
                result = self.engine.advance(uow, d, now)
                self._finish(uow, d, c, now, result.outcome, result.raised, result.next_fire_at, result.detail)
                if result.raised:
                    log.info("deadline %s: raised %d alert level(s)", d.id, result.raised)
                return 1
        except ResolverUnavailable as e:
            self._retry(c, now, "RESOLVER_UNAVAILABLE")
            log.warning("deadline %s: recipient directory unavailable (%s); will retry", c.deadline_id, e)
            return 1
        except Exception as e:  # noqa: BLE001 - keep going; the claim's lease makes this deadline retryable
            log.error("deadline %s: timer processing failed: %s", c.deadline_id, type(e).__name__)
            self._retry(c, now, "PROCESSING_ERROR")
            return 1

    def _finish(self, uow, d: Deadline, c: Claim, now: datetime, outcome: str, raised: int,
                next_fire_at: datetime | None, detail: str | None) -> None:
        d.next_fire_at = next_fire_at
        d.timer_claimed_by = None
        d.timer_lease_until = None
        d.timer_attempts = 0
        uow.session.add(TimerOutcome(deadline_id=d.id, fence=c.fence, due_version=d.due_version,
                                     scheduled_at=c.scheduled_at, processed_at=now, worker=self.worker_id,
                                     outcome=outcome, levels_raised=raised, next_fire_at=next_fire_at,
                                     detail=detail))

    def _retry(self, c: Claim, now: datetime, category: str) -> None:
        """Release the claim and try again later; nothing from the failed attempt was committed."""
        try:
            with new_session() as s:
                d = s.get(Deadline, c.deadline_id)
                retry_after = DEFAULT_RETRY
                if d is not None:
                    try:
                        config, _ = alert_config(d)
                        retry_after = config.retry_after if config else DEFAULT_RETRY
                    except Exception:  # noqa: BLE001 - the default is fine when the ruleset cannot be read
                        pass
                fenced = s.execute(update(Deadline).where(
                    Deadline.id == c.deadline_id, Deadline.timer_fence == c.fence,
                    Deadline.timer_claimed_by == self.worker_id).values(
                    next_fire_at=now + retry_after, timer_claimed_by=None, timer_lease_until=None))
                if fenced.rowcount:
                    s.add(TimerOutcome(deadline_id=c.deadline_id, fence=c.fence, due_version=d.due_version,
                                       scheduled_at=c.scheduled_at, processed_at=now, worker=self.worker_id,
                                       outcome="RETRY", levels_raised=0, next_fire_at=now + retry_after,
                                       detail=category))
                s.commit()
        except Exception as e:  # noqa: BLE001 - e.g. the database is down; the lease expiry retries it
            log.error("deadline %s: could not record retry: %s", c.deadline_id, type(e).__name__)

    def run_forever(self, stop: threading.Event, poll_seconds: float = 5.0) -> None:
        while not stop.is_set():
            try:
                busy = self.run_once()
            except Exception:  # noqa: BLE001 - keep the worker alive through database restarts
                log.exception("timer loop failed; retrying")
                busy = 0
            if not busy:
                stop.wait(poll_seconds)


def main() -> None:
    ap = argparse.ArgumentParser(description="Fire due deadline alerts and escalations.")
    ap.add_argument("--once", action="store_true", help="process what is due now and exit")
    ap.add_argument("--poll-seconds", type=float, default=5.0, help="wait this long when nothing was due")
    args = ap.parse_args()
    if args.poll_seconds <= 0:
        ap.error("--poll-seconds must be positive")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    from app.main import create_app
    create_app()  # wires every module's ports (clock, ledger, rulesets, ...)
    worker = TimerWorker()
    if args.once:
        total = 0
        while True:   # catch up on everything due, in batches
            n = worker.run_once(limit=500)
            total += n
            if n == 0:
                break
        log.info("processed %d deadline timers", total)
        return
    stop = threading.Event()
    log.info("deadline timer %s started", worker.worker_id)
    try:
        worker.run_forever(stop, poll_seconds=args.poll_seconds)
    except KeyboardInterrupt:
        stop.set()


if __name__ == "__main__":
    main()
