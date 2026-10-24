import logging

from app.platform.auth import build_authz
from app.platform.ledger import Ledger
from app.platform.records import Notes, OutboxWriter, PersonalStore
from app.platform.registry import provide
from app.platform.settings import ensure_safe, settings
from contracts.ports import AuthzPort, LedgerPort, NotesPort, OutboxPort, PersonalDataPort

log = logging.getLogger("platform")
_warned = False


def wire() -> None:
    ensure_safe(settings)  # refuse to start with demo security in production or half-configured real security
    global _warned
    if settings.demo_auth and not _warned:
        _warned = True
        log.warning("DEMO_AUTH is on: anyone who can reach this API can act as any role. Local demos only.")
    provide(LedgerPort, Ledger())
    provide(NotesPort, Notes())
    provide(PersonalDataPort, PersonalStore())
    provide(OutboxPort, OutboxWriter())
    provide(AuthzPort, build_authz(settings))
