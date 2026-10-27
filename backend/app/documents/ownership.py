"""Server-side resolution of the authoritative owner for a document case."""

from uuid import UUID

from sqlalchemy.orm import Session

from app.platform.registry import port
from contracts.ports import CasePort
from contracts.types import CaseRef


def resolve_document_owner(session: Session, application_id: UUID) -> CaseRef:
    """Resolve institution and region through CasePort; accept no client owner.

    The document schema also checks ownership in PostgreSQL at write time. This
    helper supplies the authoritative owner to a future ingestion service; it
    does not perform authorization or enable an upload API.
    """
    case = port(CasePort).lookup(session, application_id)
    if case.application_id != application_id:
        raise RuntimeError("CasePort returned a different application")
    return case
