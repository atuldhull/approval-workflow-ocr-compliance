from app.evc.service import EvcService
from app.platform.registry import provide
from contracts.ports import EvcPort


def wire() -> None:
    provide(EvcPort, EvcService())
