from app.compliance import validity
from app.compliance.service import Compliance
from app.documents.service import on_fact_confirmed
from app.platform.registry import provide
from contracts.ports import CompliancePort


def wire() -> None:
    provide(CompliancePort, Compliance())
    # a confirmed expiry date on a tracked document opens its validity record (APH cl. 6.17)
    on_fact_confirmed(validity.on_fact_confirmed)
