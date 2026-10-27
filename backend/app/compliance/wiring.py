from app.compliance.service import Compliance
from app.platform.registry import provide
from contracts.ports import CompliancePort


def wire() -> None:
    provide(CompliancePort, Compliance())
