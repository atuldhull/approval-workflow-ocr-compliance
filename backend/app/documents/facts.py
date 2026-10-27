"""Creation and explicit conflict marking for proposed OCR facts."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import inspect as sa_inspect

from app.documents.models import Fact
from app.documents.normalization import NormalizedValue
from app.documents.ocr import Script
from contracts.enums import FactState


def propose_fact(
    *,
    ocr_run_id: UUID,
    document_version_id: UUID,
    field_key: str,
    value: NormalizedValue,
    script: Script,
    confidence: float,
    page_number: int,
    source_span_start: int,
    source_span_end: int,
    created_at: datetime,
) -> Fact:
    """Build a proposed fact and retain source text and immutable page/span provenance."""
    if not field_key.strip():
        raise ValueError("fact field_key must not be blank")
    if not 0 <= confidence <= 1:
        raise ValueError("confidence must be from 0 to 1")
    if page_number <= 0 or source_span_start < 0 or source_span_end <= source_span_start:
        raise ValueError("fact needs a positive page and half-open source span")
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise ValueError("fact timestamps must be timezone-aware")
    # Confidence is recorded for review; no unapproved threshold is used.
    return Fact(
        fact_id=uuid4(),
        ocr_run_id=ocr_run_id,
        document_version_id=document_version_id,
        field_key=field_key,
        candidate_text=value.original_text,
        normalized_value=value.normalized_value,
        normalization_status=value.status.value,
        script_code=script.value,
        confidence=confidence,
        page_number=page_number,
        source_span_start=source_span_start,
        source_span_end=source_span_end,
        state=FactState.PROPOSED.value,
        created_at=created_at,
    )


def mark_conflicting_candidates(facts: list[Fact], *, conflict_group_id: UUID | None = None) -> UUID | None:
    """Mark distinct candidates for one caller-defined field group as conflicting.

    The caller supplies facts it has already determined refer to the same
    logical field. Assign the group before the facts are persisted, so the
    immutable database provenance guard sees it on the initial INSERT. This
    helper does not infer document semantics or resolve a conflict, and all
    members remain PROPOSED.
    """
    if not facts:
        return None
    states = [sa_inspect(fact) for fact in facts]
    if any(not (state.transient or state.pending) for state in states):
        raise ValueError("OCR conflict groups must be assigned before fact persistence")
    if any(fact.state != FactState.PROPOSED.value for fact in facts):
        raise ValueError("only proposed facts can be grouped as OCR conflicts")
    if len({fact.document_version_id for fact in facts}) != 1 or len({fact.field_key for fact in facts}) != 1:
        raise ValueError("conflicting facts must share a document version and field key")
    values = {
        fact.normalized_value if fact.normalized_value is not None else fact.candidate_text.strip()
        for fact in facts
    }
    if len(values) < 2:
        return None
    group_id = conflict_group_id or uuid4()
    for fact in facts:
        fact.conflict_group_id = group_id
        fact.state = FactState.PROPOSED.value
    return group_id
