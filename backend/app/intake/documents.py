"""Checks that a checklist item's document_ref names a usable document version of the same application.

Reads the documents module's version rows read-only; it never writes them. A version qualifies only when it belongs
to the application and passed the malware scan (status AVAILABLE). An unknown version and a version of another
application are both DOCUMENT_REF_UNKNOWN, so the answer never reveals other applications' documents.

DEMO_MODE only: a UUID version 5 reference that names no stored version is accepted as a deterministic DEMO fixture
reference (the seeds and older fixtures use them; real uploads get random version 4 IDs). Outside DEMO_MODE every
reference must be a stored AVAILABLE version.
"""
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.documents.models import DocumentVersion
from app.platform import settings as configuration
from contracts.errors import ValidationFailed


def demo_fixture_ref(ref: UUID) -> bool:
    return configuration.settings.demo_mode and ref.version == 5


def check_document_refs(session: Session, application_id: UUID, refs: list[UUID]) -> None:
    if not refs:
        return
    rows = {row.document_version_id: row for row in session.scalars(
        select(DocumentVersion).where(DocumentVersion.document_version_id.in_(set(refs))))}
    for ref in refs:
        row = rows.get(ref)
        if row is None:
            if demo_fixture_ref(ref):
                continue
            raise ValidationFailed("DOCUMENT_REF_UNKNOWN")
        if row.application_id != application_id:
            raise ValidationFailed("DOCUMENT_REF_UNKNOWN")
        if row.status != "AVAILABLE" or row.scan_status != "clean":
            raise ValidationFailed("DOCUMENT_REF_NOT_AVAILABLE")
