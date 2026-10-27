import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.platform.db import get_engine
from app.platform.errors import ServiceUnavailable
from app.platform.settings import settings
from contracts.errors import Forbidden

log = logging.getLogger("deadline-clock")

READ = text("SELECT offset_seconds FROM dl.sim_clock WHERE id = 1")
ADD = text("""
    INSERT INTO dl.sim_clock (id, offset_seconds, updated_at) VALUES (1, :seconds, now())
    ON CONFLICT (id) DO UPDATE
       SET offset_seconds = dl.sim_clock.offset_seconds + EXCLUDED.offset_seconds, updated_at = now()
    RETURNING offset_seconds
""")
RESET = text("""
    INSERT INTO dl.sim_clock (id, offset_seconds, updated_at) VALUES (1, 0, now())
    ON CONFLICT (id) DO UPDATE SET offset_seconds = 0, updated_at = now()
    RETURNING offset_seconds
""")


class SystemClock:
    """Real time plus a demo-only offset ("time travel"). Nothing else in the system reads the time.

    The offset is stored in dl.sim_clock, so every process (API, timer worker) sees the same demo time. It is
    re-read at most every `refresh_seconds`, and taken over at once after advance/reset in this process.
    Outside demo mode the stored offset is never read: the clock is always real time.
    """

    def __init__(self, refresh_seconds: float = 1.0):
        self.refresh_seconds = refresh_seconds
        self._offset = timedelta(0)
        self._read_at: float | None = None

    @property
    def offset(self) -> timedelta:
        if not settings.demo_mode:
            return timedelta(0)
        if self._read_at is None or time.monotonic() - self._read_at >= self.refresh_seconds:
            self._load()
        return self._offset

    def now(self) -> datetime:
        return datetime.now(timezone.utc) + self.offset

    def advance(self, days: int) -> datetime:
        if not settings.demo_mode:
            raise Forbidden("time travel is only available in demo mode")
        self._store(ADD, {"seconds": int(timedelta(days=days).total_seconds())})
        return self.now()

    def reset(self) -> datetime:
        if not settings.demo_mode:
            raise Forbidden("time travel is only available in demo mode")
        self._store(RESET, {})
        return self.now()

    def _load(self) -> None:
        try:
            with get_engine().connect() as conn:
                stored = conn.execute(READ).scalar()
            self._offset = timedelta(seconds=stored or 0)
        except SQLAlchemyError as e:
            # keep the last known offset; the next read tries again
            log.warning("demo clock offset could not be read: %s", type(e).__name__)
        self._read_at = time.monotonic()

    def _store(self, statement, params: dict) -> None:
        try:
            with get_engine().begin() as conn:
                stored = conn.execute(statement, params).scalar_one()
        except SQLAlchemyError as e:
            raise ServiceUnavailable("the demo clock could not be stored") from e
        self._offset = timedelta(seconds=stored)
        self._read_at = time.monotonic()
