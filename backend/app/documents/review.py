"""Backend type-then-reveal review transitions for OCR fact candidates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.documents.models import Fact
from app.documents.states import NormalizationStatus
from contracts.enums import FactState


@dataclass(frozen=True)
class RevealedSuggestion:
    fact_id: UUID
    candidate_text: str
    normalized_value: str | None
    confidence: float
    normalization_status: str


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("review timestamps must be timezone-aware")


def enter_value_before_reveal(fact: Fact, *, reviewer_id: UUID, value: str, at: datetime) -> None:
    """Persist the reviewer's initial value without returning the OCR suggestion."""
    _require_aware(at)
    if fact.state != FactState.PROPOSED.value:
        raise ValueError("only proposed facts can enter review")
    if fact.review_typed_at is not None or fact.suggestion_revealed_at is not None:
        raise ValueError("the type-before-reveal step has already started")
    if not value.strip():
        raise ValueError("the reviewer's initial value must not be blank")
    if fact.created_at is not None and at < fact.created_at:
        raise ValueError("initial review entry cannot precede the fact")
    fact.review_typed_value = value.strip()
    fact.review_typed_by = reviewer_id
    fact.review_typed_at = at


def reveal_suggestion(fact: Fact, *, at: datetime) -> RevealedSuggestion:
    """Reveal a candidate only after the initial value has been recorded.

    Repeated calls after reveal return the same suggestion, making UI retries
    idempotent without changing the recorded review order.
    """
    _require_aware(at)
    if fact.state != FactState.PROPOSED.value:
        raise ValueError("fact review is already final")
    if fact.review_typed_at is None or fact.review_typed_value is None or fact.review_typed_by is None:
        raise ValueError("record the reviewer's own value before revealing OCR text")
    if fact.suggestion_revealed_at is None:
        if at < fact.review_typed_at:
            raise ValueError("suggestion reveal cannot precede initial entry")
        fact.suggestion_revealed_at = at
    return RevealedSuggestion(
        fact_id=fact.fact_id,
        candidate_text=fact.candidate_text,
        normalized_value=fact.normalized_value,
        confidence=float(fact.confidence),
        normalization_status=fact.normalization_status,
    )


def finalize_review(
    fact: Fact,
    *,
    reviewer_id: UUID,
    decision: FactState,
    at: datetime,
    reviewed_value: str | None = None,
) -> None:
    """Apply a human decision after reveal; ambiguous candidates need correction."""
    _require_aware(at)
    if fact.state != FactState.PROPOSED.value:
        raise ValueError("fact review is already final")
    if fact.review_typed_at is None or fact.suggestion_revealed_at is None:
        raise ValueError("type-before-reveal review must complete before a decision")
    if fact.review_typed_by != reviewer_id:
        raise ValueError("the reviewer who entered first must complete this review")
    if at < fact.suggestion_revealed_at:
        raise ValueError("review decision cannot precede suggestion reveal")

    if decision is FactState.CONFIRMED:
        if fact.normalization_status != NormalizationStatus.NORMALIZED.value or fact.normalized_value is None:
            raise ValueError("ambiguous or unnormalized candidates must be corrected or rejected")
        final_value = fact.normalized_value
        if reviewed_value is not None and reviewed_value != final_value:
            raise ValueError("a confirmed fact must retain its normalized OCR value")
    elif decision is FactState.CORRECTED:
        if reviewed_value is None or not reviewed_value.strip():
            raise ValueError("a corrected fact requires the human-reviewed value")
        final_value = reviewed_value.strip()
        if fact.normalized_value is not None and final_value == fact.normalized_value:
            raise ValueError("an unchanged candidate should be confirmed instead")
    elif decision is FactState.REJECTED:
        if reviewed_value is not None:
            raise ValueError("a rejected fact cannot have a reviewed value")
        final_value = None
    else:
        raise ValueError("review decision must be CONFIRMED, CORRECTED, or REJECTED")

    fact.state = decision.value
    fact.reviewed_value = final_value
    fact.reviewed_at = at
