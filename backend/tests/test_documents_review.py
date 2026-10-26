"""Database-free backend acceptance checks for type-then-reveal review."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.documents.facts import propose_fact
from app.documents.normalization import normalize_date_candidate
from app.documents.review import enter_value_before_reveal, finalize_review, reveal_suggestion
from app.documents.ocr import Script
from contracts.enums import FactState


NOW = datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc)


def make_fact(text="2025-03-12"):
    return propose_fact(
        ocr_run_id=uuid4(),
        document_version_id=uuid4(),
        field_key="issue_date",
        value=normalize_date_candidate(text),
        script=Script.LATIN,
        confidence=0.25,
        page_number=1,
        source_span_start=0,
        source_span_end=len(text),
        created_at=NOW,
    )


def test_suggestion_cannot_be_revealed_before_initial_value_is_recorded():
    fact = make_fact()
    with pytest.raises(ValueError, match="before revealing"):
        reveal_suggestion(fact, at=NOW + timedelta(seconds=1))
    reviewer_id = uuid4()
    enter_value_before_reveal(fact, reviewer_id=reviewer_id, value="2025-03-12", at=NOW)
    with pytest.raises(ValueError, match="type-before-reveal"):
        finalize_review(
            fact,
            reviewer_id=reviewer_id,
            decision=FactState.CONFIRMED,
            at=NOW + timedelta(seconds=1),
        )
    assert fact.state == FactState.PROPOSED.value
    assert fact.suggestion_revealed_at is None
    suggestion = reveal_suggestion(fact, at=NOW + timedelta(seconds=1))
    assert suggestion.candidate_text == "2025-03-12"
    assert suggestion.normalized_value == "2025-03-12"


def test_type_then_reveal_is_retryable_but_review_is_single_use():
    fact = make_fact()
    reviewer_id = uuid4()
    enter_value_before_reveal(fact, reviewer_id=reviewer_id, value="2025-03-12", at=NOW)
    revealed_at = NOW + timedelta(seconds=1)
    first = reveal_suggestion(fact, at=revealed_at)
    second = reveal_suggestion(fact, at=NOW + timedelta(seconds=2))
    assert first == second
    assert fact.suggestion_revealed_at == revealed_at
    finalize_review(
        fact,
        reviewer_id=reviewer_id,
        decision=FactState.CONFIRMED,
        at=NOW + timedelta(seconds=3),
    )
    assert fact.state == FactState.CONFIRMED.value
    assert fact.reviewed_value == "2025-03-12"
    with pytest.raises(ValueError, match="already final"):
        reveal_suggestion(fact, at=NOW + timedelta(seconds=4))


def test_ambiguous_date_stays_proposed_until_human_correction_after_reveal():
    fact = make_fact("04/05/2025")
    reviewer_id = uuid4()
    enter_value_before_reveal(fact, reviewer_id=reviewer_id, value="4 May 2025", at=NOW)
    reveal_suggestion(fact, at=NOW + timedelta(seconds=1))
    with pytest.raises(ValueError, match="must be corrected or rejected"):
        finalize_review(
            fact,
            reviewer_id=reviewer_id,
            decision=FactState.CONFIRMED,
            at=NOW + timedelta(seconds=2),
        )
    assert fact.state == FactState.PROPOSED.value
    finalize_review(
        fact,
        reviewer_id=reviewer_id,
        decision=FactState.CORRECTED,
        at=NOW + timedelta(seconds=2),
        reviewed_value="2025-05-04",
    )
    assert fact.state == FactState.CORRECTED.value
    assert fact.reviewed_value == "2025-05-04"


def test_finalized_review_cannot_be_changed_or_reentered():
    fact = make_fact()
    reviewer_id = uuid4()
    enter_value_before_reveal(fact, reviewer_id=reviewer_id, value="2025-03-12", at=NOW)
    reveal_suggestion(fact, at=NOW + timedelta(seconds=1))
    finalize_review(
        fact,
        reviewer_id=reviewer_id,
        decision=FactState.CONFIRMED,
        at=NOW + timedelta(seconds=2),
    )
    final_decision = (fact.state, fact.reviewed_value, fact.reviewed_at)

    with pytest.raises(ValueError, match="already final"):
        finalize_review(
            fact,
            reviewer_id=reviewer_id,
            decision=FactState.REJECTED,
            at=NOW + timedelta(seconds=3),
        )
    with pytest.raises(ValueError, match="only proposed facts"):
        enter_value_before_reveal(fact, reviewer_id=reviewer_id, value="changed", at=NOW + timedelta(seconds=3))
    with pytest.raises(ValueError, match="already final"):
        reveal_suggestion(fact, at=NOW + timedelta(seconds=3))

    assert (fact.state, fact.reviewed_value, fact.reviewed_at) == final_decision


def test_review_requires_same_reviewer_and_rejects_empty_initial_entry():
    fact = make_fact()
    with pytest.raises(ValueError, match="must not be blank"):
        enter_value_before_reveal(fact, reviewer_id=uuid4(), value="  ", at=NOW)
    reviewer = uuid4()
    enter_value_before_reveal(fact, reviewer_id=reviewer, value="first", at=NOW)
    reveal_suggestion(fact, at=NOW + timedelta(seconds=1))
    decision_before_rejected_attempt = (fact.state, fact.reviewed_value, fact.reviewed_at)
    with pytest.raises(ValueError, match="must complete this review"):
        finalize_review(
            fact,
            reviewer_id=uuid4(),
            decision=FactState.CORRECTED,
            at=NOW + timedelta(seconds=2),
            reviewed_value="corrected",
        )
    assert (fact.state, fact.reviewed_value, fact.reviewed_at) == decision_before_rejected_attempt


@pytest.mark.parametrize("reviewer_id", [None, "not-a-uuid"], ids=["none", "invalid-string"])
def test_invalid_reviewer_identity_is_rejected_without_mutating_fact(reviewer_id):
    fact = make_fact()
    initial_state = (
        fact.state,
        fact.review_typed_value,
        fact.review_typed_by,
        fact.review_typed_at,
        fact.suggestion_revealed_at,
        fact.reviewed_value,
        fact.reviewed_at,
    )

    with pytest.raises(ValueError, match="reviewer_id must be a UUID"):
        enter_value_before_reveal(
            fact,
            reviewer_id=reviewer_id,
            value="2025-03-12",
            at=NOW,
        )

    assert (
        fact.state,
        fact.review_typed_value,
        fact.review_typed_by,
        fact.review_typed_at,
        fact.suggestion_revealed_at,
        fact.reviewed_value,
        fact.reviewed_at,
    ) == initial_state
