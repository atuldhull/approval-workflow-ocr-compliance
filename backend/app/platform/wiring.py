from app.platform.auth import Authz
from app.platform.ledger import Ledger
from app.platform.records import Notes, OutboxWriter, PersonalStore
from app.platform.registry import provide
from contracts.ports import AuthzPort, LedgerPort, NotesPort, OutboxPort, PersonalDataPort


def wire() -> None:
    provide(LedgerPort, Ledger())
    provide(NotesPort, Notes())
    provide(PersonalDataPort, PersonalStore())
    provide(OutboxPort, OutboxWriter())
    provide(AuthzPort, Authz())
