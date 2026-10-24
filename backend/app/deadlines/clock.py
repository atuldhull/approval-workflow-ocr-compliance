from datetime import datetime, timedelta, timezone

from app.platform.settings import settings
from contracts.errors import Forbidden


class SystemClock:
    """Real time plus a demo-only offset ("time travel"). Nothing else in the system reads the time."""

    def __init__(self):
        self.offset = timedelta(0)

    def now(self) -> datetime:
        return datetime.now(timezone.utc) + self.offset

    def advance(self, days: int) -> datetime:
        if not settings.demo_mode:
            raise Forbidden("time travel is only available in demo mode")
        self.offset += timedelta(days=days)
        return self.now()

    def reset(self) -> datetime:
        if not settings.demo_mode:
            raise Forbidden("time travel is only available in demo mode")
        self.offset = timedelta(0)
        return self.now()
