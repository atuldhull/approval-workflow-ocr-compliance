"""Database-free OCR adapter, normalization, run, and proposed-fact tests."""

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session, make_transient_to_detached

from app.documents.facts import mark_conflicting_candidates, propose_fact
from app.documents.normalization import normalize_date_candidate, normalize_numerals, normalize_reference_value
from app.documents.ocr import (
    AdapterRouter,
    OcrToken,
    Script,
    ScriptRoutingError,
    detect_script,
    enqueue_retry,
    make_ocr_run,
    retry_failed_run,
    transition_ocr_run,
)
from app.documents.states import NormalizationStatus, OcrErrorCode, OcrRunStatus


NOW = datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)
FIXTURE = Path(__file__).resolve().parents[2] / "generator" / "documents" / "normalization_cases.json"


class FakeAdapter:
    adapter_key = "test.fake"
    model_version = "fixture-1"
    supported_scripts = frozenset({Script.DEVANAGARI, Script.LATIN})

    def recognize_page(self, page_bytes, *, page_number, script):
        if script not in self.supported_scripts:
            raise ValueError("script is not supported by this fake adapter")
        return (OcrToken("123", page_number, 0, 3, Decimal("0.75"), script),)


@pytest.mark.parametrize("case", json.loads(FIXTURE.read_text(encoding="utf-8")), ids=lambda c: c["case"])
def test_synthetic_ocr_normalization_fixtures(case):
    assert detect_script(case["text"]).value == case["script"]
    assert normalize_numerals(case["text"]) == case["normalized_digits"]
    normalized_date = normalize_date_candidate(case["text"])
    assert normalized_date.normalized_value == case["date_value"]
    assert normalized_date.status.value == case["date_status"]
    assert normalized_date.original_text == case["text"]


def test_script_router_uses_explicit_aliases_and_fails_closed_on_mixed_or_unsupported_text():
    adapter = FakeAdapter()
    router = AdapterRouter([adapter])

    assert router.for_hint("Deva") is adapter
    assert router.for_text("पत्र १२३") is adapter
    tokens = router.recognize_page(b"fixture-page", page_number=2, script_hint="Deva")
    assert tokens[0].page_number == 2
    assert tokens[0].script is Script.DEVANAGARI
    with pytest.raises(ScriptRoutingError, match="MIXED"):
        router.for_text("पत्र abc")
    with pytest.raises(ScriptRoutingError, match="UNSUPPORTED"):
        router.for_text("العربية")
    with pytest.raises(ScriptRoutingError, match="no OCR adapter"):
        router.for_hint("Beng")
    with pytest.raises(ScriptRoutingError, match="unknown script hint"):
        router.for_hint("hi")
    with pytest.raises(ValueError, match="inconsistent page"):
        class WrongPage(FakeAdapter):
            def recognize_page(self, page_bytes, *, page_number, script):
                return (OcrToken("123", 1, 0, 3, Decimal("0.75"), script),)
        AdapterRouter([WrongPage()]).recognize_page(b"fixture-page", page_number=2, script_hint="Deva")


def test_router_rejects_overlapping_adapter_claims():
    class SecondAdapter(FakeAdapter):
        adapter_key = "test.second"

    with pytest.raises(ValueError, match="more than one"):
        AdapterRouter([FakeAdapter(), SecondAdapter()])


def test_ocr_token_requires_bounded_confidence_and_valid_provenance():
    token = OcrToken("fact", 2, 10, 14, Decimal("0.125"), Script.LATIN)
    assert token.page_number == 2
    assert token.confidence == Decimal("0.125")
    with pytest.raises(ValueError, match="confidence"):
        OcrToken("fact", 2, 10, 14, Decimal("1.1"), Script.LATIN)
    with pytest.raises(ValueError, match="source span"):
        OcrToken("fact", 2, 10, 10, Decimal("0.5"), Script.LATIN)


def test_numerals_are_normalized_without_losing_source_and_dates_are_not_guessed():
    source = "०४/०५/२०२५"
    candidate = normalize_date_candidate(source)
    assert candidate.original_text == source
    assert candidate.normalized_value is None
    assert candidate.status is NormalizationStatus.AMBIGUOUS
    assert normalize_reference_value("सं. १२३/२०२५").normalized_value == "सं. 123/2025"
    assert normalize_date_candidate("२०२५-०२-३०").status is NormalizationStatus.INVALID
    assert normalize_date_candidate("12 March 2025").status is NormalizationStatus.UNSUPPORTED


def test_run_statuses_and_deterministic_failed_retry():
    version_id = uuid4()
    run = make_ocr_run(document_version_id=version_id, adapter_key="test.fake", model_version="1", created_at=NOW)
    assert run.status == OcrRunStatus.QUEUED.value
    transition_ocr_run(run, OcrRunStatus.RUNNING, at=NOW + timedelta(seconds=1))
    transition_ocr_run(
        run,
        OcrRunStatus.FAILED,
        at=NOW + timedelta(seconds=2),
        error_code=OcrErrorCode.TIMEOUT,
    )
    assert run.status == OcrRunStatus.FAILED.value
    retry_a = retry_failed_run(run, created_at=NOW + timedelta(seconds=3))
    retry_b = retry_failed_run(run, created_at=NOW + timedelta(seconds=3))
    assert retry_a.ocr_run_id == retry_b.ocr_run_id
    assert retry_a.retry_of_ocr_run_id == run.ocr_run_id
    assert retry_a.attempt_number == 2
    with pytest.raises(ValueError, match="failed OCR run"):
        retry_failed_run(retry_a, created_at=NOW + timedelta(seconds=3))


def test_retry_requires_a_completed_failed_attempt_and_cannot_precede_completion():
    incomplete = make_ocr_run(
        document_version_id=uuid4(), adapter_key="test.fake", model_version="1", created_at=NOW
    )
    incomplete.status = OcrRunStatus.FAILED.value
    incomplete.error_code = OcrErrorCode.TIMEOUT.value
    with pytest.raises(ValueError, match="completion timestamp"):
        retry_failed_run(incomplete, created_at=NOW + timedelta(seconds=2))

    missing_error = make_ocr_run(
        document_version_id=uuid4(), adapter_key="test.fake", model_version="1", created_at=NOW
    )
    missing_error.status = OcrRunStatus.FAILED.value
    missing_error.finished_at = NOW + timedelta(seconds=1)
    with pytest.raises(ValueError, match="stable error code"):
        retry_failed_run(missing_error, created_at=NOW + timedelta(seconds=2))

    completed = make_ocr_run(
        document_version_id=uuid4(), adapter_key="test.fake", model_version="1", created_at=NOW
    )
    transition_ocr_run(
        completed,
        OcrRunStatus.FAILED,
        at=NOW + timedelta(seconds=2),
        error_code=OcrErrorCode.TIMEOUT,
    )
    with pytest.raises(ValueError, match="cannot precede"):
        retry_failed_run(completed, created_at=NOW + timedelta(seconds=1))


def test_invalid_run_transitions_and_unstable_errors_are_rejected():
    run = make_ocr_run(document_version_id=uuid4(), adapter_key="test.fake", model_version=None, created_at=NOW)
    with pytest.raises(ValueError, match="stable error code"):
        transition_ocr_run(run, OcrRunStatus.FAILED, at=NOW + timedelta(seconds=1))
    transition_ocr_run(
        run, OcrRunStatus.FAILED, at=NOW + timedelta(seconds=1), error_code=OcrErrorCode.PROCESSING_FAILED
    )
    with pytest.raises(ValueError, match="invalid OCR run transition"):
        transition_ocr_run(run, OcrRunStatus.RUNNING, at=NOW + timedelta(seconds=2))


def test_terminal_ocr_run_cannot_transition_again():
    run = make_ocr_run(document_version_id=uuid4(), adapter_key="test.fake", model_version=None, created_at=NOW)
    transition_ocr_run(run, OcrRunStatus.RUNNING, at=NOW + timedelta(seconds=1))
    transition_ocr_run(run, OcrRunStatus.SUCCEEDED, at=NOW + timedelta(seconds=2))

    with pytest.raises(ValueError, match="invalid OCR run transition"):
        transition_ocr_run(
            run,
            OcrRunStatus.FAILED,
            at=NOW + timedelta(seconds=3),
            error_code=OcrErrorCode.TIMEOUT,
        )

    assert run.status == OcrRunStatus.SUCCEEDED.value
    assert run.error_code is None
    assert run.finished_at == NOW + timedelta(seconds=2)


def test_retry_enqueue_returns_the_same_persisted_attempt_on_replay():
    previous = make_ocr_run(document_version_id=uuid4(), adapter_key="test.fake", model_version="1", created_at=NOW)
    transition_ocr_run(previous, OcrRunStatus.FAILED, at=NOW + timedelta(seconds=1), error_code=OcrErrorCode.TIMEOUT)

    class FakeSession:
        stored = None
        insert_count = 0

        def scalar(self, statement):
            return self.stored

        def execute(self, statement):
            self.insert_count += 1
            self.stored = retry_failed_run(previous, created_at=NOW + timedelta(seconds=2))

    session = FakeSession()
    first = enqueue_retry(session, previous, created_at=NOW + timedelta(seconds=2))
    replay = enqueue_retry(session, previous, created_at=NOW + timedelta(seconds=3))
    assert first is replay
    assert session.insert_count == 1


def test_proposed_facts_keep_low_confidence_ambiguous_values_and_conflicts_proposed():
    version_id, run_id = uuid4(), uuid4()
    first = propose_fact(
        ocr_run_id=run_id,
        document_version_id=version_id,
        field_key="issue_date",
        value=normalize_date_candidate("04/05/2025"),
        script=Script.LATIN,
        confidence=0.01,
        page_number=1,
        source_span_start=0,
        source_span_end=10,
        created_at=NOW,
    )
    second = propose_fact(
        ocr_run_id=run_id,
        document_version_id=version_id,
        field_key="issue_date",
        value=normalize_date_candidate("2025-05-04"),
        script=Script.LATIN,
        confidence=0.99,
        page_number=1,
        source_span_start=12,
        source_span_end=22,
        created_at=NOW,
    )
    group_id = mark_conflicting_candidates([first, second])
    assert group_id is not None
    assert first.conflict_group_id == second.conflict_group_id == group_id
    assert first.state == second.state == "PROPOSED"
    assert first.candidate_text == "04/05/2025"
    assert first.normalization_status == NormalizationStatus.AMBIGUOUS.value


def test_conflict_groups_are_assigned_before_fact_persistence():
    version_id, run_id = uuid4(), uuid4()

    def candidate(text, start):
        return propose_fact(
            ocr_run_id=run_id,
            document_version_id=version_id,
            field_key="issue_date",
            value=normalize_date_candidate(text),
            script=Script.LATIN,
            confidence=0.5,
            page_number=1,
            source_span_start=start,
            source_span_end=start + len(text),
            created_at=NOW,
        )

    pending_fact = candidate("2025-03-12", 0)
    other_pending_fact = candidate("2025-05-04", 12)
    session = Session()
    try:
        session.add(pending_fact)
        assert sa_inspect(pending_fact).pending

        group_id = mark_conflicting_candidates([pending_fact, other_pending_fact])

        assert group_id is not None
        assert pending_fact.conflict_group_id == other_pending_fact.conflict_group_id == group_id
        assert sa_inspect(pending_fact).pending
    finally:
        session.close()

    detached_fact = candidate("2025-03-12", 0)
    make_transient_to_detached(detached_fact)
    assert sa_inspect(detached_fact).detached
    with pytest.raises(ValueError, match="before fact persistence"):
        mark_conflicting_candidates([detached_fact, candidate("2025-05-04", 12)])
