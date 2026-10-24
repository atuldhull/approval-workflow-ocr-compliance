from app.intake.service import Cases
from app.platform.registry import provide
from contracts.ports import CasePort


def wire() -> None:
    provide(CasePort, Cases())
