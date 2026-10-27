"""Synthetic, database-free tests of approved v1 field extraction boundaries."""

import json
import re
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import inspect as sa_inspect

from app.documents import candidates as module
from app.documents.candidates import FieldCandidate, extract_field_candidates, load_field_rules
from app.documents.facts import mark_conflicting_candidates, propose_fact
from app.documents.normalization import NormalizedValue
from app.documents.ocr import OcrToken, Script
from app.documents.states import NormalizationStatus


def tokens_for(text, *, page=1, script=Script.LATIN):
    return tuple(OcrToken(m.group(), page, m.start(), m.end(), Decimal("0.6"), script)
                 for m in re.finditer(r"\S+", text))


def extract(text, **overrides):
    args = dict(page_text=text, tokens=tokens_for(text), page_number=1,
                ocr_run_id=uuid4(), document_version_id=uuid4())
    args.update(overrides)
    return extract_field_candidates(**args)


def test_v1_catalog_contains_only_approved_canonical_keys_and_assignments():
    rules = load_field_rules()
    assert {r.field_key: r.normalizer for r in rules} == {
        "lease_end_date": "normalize_date_candidate",
        "letter_issue_date": "normalize_date_candidate",
        "letter_file_number": "normalize_reference_value",
    }
    assert all(r.labels == (r.field_key,) for r in rules)


def test_field_candidate_contract_accepts_extractor_result():
    candidate, = extract("letter_file_number: X/12", tokens=tokens_for("letter_file_number: X/12"))

    assert isinstance(candidate, FieldCandidate)
    assert candidate.source_span_end - candidate.source_span_start == len(candidate.value.original_text)
    assert candidate.source_tokens


@pytest.mark.parametrize("change", [
    {"field_key": "unapproved_field"},
    {"value": "not-normalized"},
    {"ocr_run_id": None},
    {"page_number": True},
    {"source_span_end": 999},
    {"source_tokens": ()},
    {"source_tokens": (object(),)},
    {"alias_version": True},
    {"alias_version": 2},
])
def test_field_candidate_rejects_invalid_direct_construction(change):
    candidate, = extract("letter_file_number: X/12", tokens=tokens_for("letter_file_number: X/12"))
    fields = {
        "field_key": candidate.field_key,
        "value": candidate.value,
        "ocr_run_id": candidate.ocr_run_id,
        "document_version_id": candidate.document_version_id,
        "page_number": candidate.page_number,
        "source_span_start": candidate.source_span_start,
        "source_span_end": candidate.source_span_end,
        "source_tokens": candidate.source_tokens,
        "alias_version": candidate.alias_version,
    }
    fields.update(change)

    with pytest.raises(ValueError):
        FieldCandidate(**fields)


@pytest.mark.parametrize("field,value,expected,status", [
    ("lease_end_date", "2024-12-31", "2024-12-31", NormalizationStatus.NORMALIZED),
    ("letter_issue_date", "31/12/2024", "2024-12-31", NormalizationStatus.NORMALIZED),
    ("letter_issue_date", "03-04-2024", None, NormalizationStatus.AMBIGUOUS),
    ("lease_end_date", "31/02/2024", None, NormalizationStatus.INVALID),
    ("lease_end_date", "next April", None, NormalizationStatus.UNSUPPORTED),
    ("letter_file_number", "AB/१२३/२०२४", "AB/123/2024", NormalizationStatus.NORMALIZED),
    ("lease_end_date", "२०२४-१२-३१", "2024-12-31", NormalizationStatus.NORMALIZED),
    ("letter_issue_date", "০৩-০৪-২০২৪", None, NormalizationStatus.AMBIGUOUS),
])
def test_approved_normalizers_preserve_raw_text_and_unresolved_values(field, value, expected, status):
    text = f"{field}: {value}"
    run_id, version_id = uuid4(), uuid4()
    candidate, = extract(text, ocr_run_id=run_id, document_version_id=version_id)
    assert candidate.field_key == field
    assert candidate.value.original_text == value
    assert candidate.value.normalized_value == expected
    assert candidate.value.status is status
    assert candidate.ocr_run_id == run_id
    assert candidate.document_version_id == version_id
    assert candidate.alias_version == 1
    assert text[candidate.source_span_start:candidate.source_span_end] == value


def test_grouping_stops_at_next_known_label_and_line_end_without_joining_values():
    text = "lease_end_date: 2024-12-31 letter_issue_date: 03-04-2024\nletter_file_number: X/12\nignored"
    found = extract(text)
    assert [(c.field_key, c.value.original_text) for c in found] == [
        ("lease_end_date", "2024-12-31"),
        ("letter_issue_date", "03-04-2024"),
        ("letter_file_number", "X/12"),
    ]


@pytest.mark.parametrize("separator", ["\n", "\r\n", "\r", "\u2028"])
def test_page_character_offsets_include_original_line_breaks_and_unicode(separator):
    text = f"😀 header{separator}letter_file_number:  १२  /  ३  {separator}tail"
    tokens = tokens_for(text, page=3, script=Script.DEVANAGARI)
    candidate, = extract(text, tokens=tuple(reversed(tokens)), page_number=3)
    assert candidate.page_number == 3
    assert candidate.source_span_start == text.index("१२")
    assert candidate.source_span_end == text.index("३") + 1
    assert candidate.value.original_text == "१२  /  ३"
    assert candidate.value.normalized_value == "12  /  3"
    assert candidate.source_tokens == tokens[3:6]
    assert all(t.confidence == Decimal("0.6") for t in candidate.source_tokens)


@pytest.mark.parametrize("text", [
    "", " \t\n", "letter_issue_date:", "letter_issue_date:\n2024-12-31",
    "letter_issue_date: lease_end_date:", "issue_date: 2024-12-31",
    "Letter Issue Date: 2024-12-31", "LETTER_ISSUE_DATE: 2024-12-31",
    "xletter_issue_date: 2024-12-31", "letter_issue_date_extra: 2024-12-31",
])
def test_empty_values_and_unknown_labels_do_not_invent_fields(text):
    assert extract(text) == ()


@pytest.mark.parametrize("separator", [": ", ":", " ", "\t", " : "])
def test_label_delimiters_do_not_change_original_candidate_text(separator):
    candidate, = extract(f"letter_file_number{separator}AB/12")
    assert candidate.value.original_text == "AB/12"


@pytest.mark.parametrize("change", [
    {"page_number": True}, {"page_number": 1.5}, {"page_number": 0},
    {"ocr_run_id": None}, {"document_version_id": "not-a-uuid"},
    {"page_text": None}, {"tokens": None}, {"tokens": [object()]},
])
def test_invalid_runtime_input_is_rejected(change):
    with pytest.raises(ValueError):
        extract("letter_file_number: X/12", **change)


@pytest.mark.parametrize("failure", ["missing-label", "missing-value", "wrong-page", "wrong-text", "out-of-bounds", "overlap"])
def test_malformed_provenance_is_rejected_without_partial_results(failure):
    text = "letter_issue_date: 2024-12-31\nletter_file_number: X/12"
    tokens = list(tokens_for(text))
    if failure == "missing-label":
        del tokens[2]
    elif failure == "missing-value":
        tokens.pop()
    elif failure == "wrong-page":
        tokens[-1] = replace(tokens[-1], page_number=2)
    elif failure == "wrong-text":
        tokens[-1] = replace(tokens[-1], text="Y/12")
    elif failure == "out-of-bounds":
        tokens[-1] = replace(tokens[-1], span_end=len(text) + 1)
    else:
        tokens.append(tokens[-1])
    with pytest.raises(ValueError, match="provenance"):
        extract(text, tokens=tokens)


def test_multiline_token_is_rejected_and_exact_single_line_token_is_supported():
    text = "letter_file_number: X/12\nletter_issue_date: 2024-12-31"
    token = OcrToken(text, 1, 0, len(text), Decimal("0.6"), Script.LATIN)
    with pytest.raises(ValueError, match="provenance"):
        extract(text, tokens=(token,))
    line = text.splitlines()[0]
    token = replace(token, text=line, span_end=len(line))
    candidate, = extract(line, tokens=(token,))
    assert candidate.value.original_text == "X/12"
    assert candidate.source_tokens == (token,)


def test_missing_all_tokens_cannot_yield_candidate_from_unattributed_page_text():
    with pytest.raises(ValueError, match="provenance"):
        extract("letter_file_number: X/12", tokens=())


def proposed_facts(candidates):
    # Synthetic explicit confidence; no runtime token aggregation or threshold.
    return [propose_fact(
        ocr_run_id=c.ocr_run_id, document_version_id=c.document_version_id,
        field_key=c.field_key, value=c.value, script=Script.LATIN,
        confidence=Decimal("0.6"), page_number=c.page_number,
        source_span_start=c.source_span_start, source_span_end=c.source_span_end,
        created_at=datetime(2026, 10, 26, tzinfo=timezone.utc),
    ) for c in candidates]


def test_competing_unresolved_candidates_remain_separate_proposed_facts_with_shared_group():
    candidates = extract("letter_issue_date: 03-04-2024\nletter_issue_date: 04-05-2024")
    facts = proposed_facts(candidates)
    group_id = mark_conflicting_candidates(facts)
    assert len(facts) == 2
    assert group_id is not None
    assert all(f.state == "PROPOSED" and f.normalized_value is None for f in facts)
    assert all(f.conflict_group_id == group_id and sa_inspect(f).transient for f in facts)
    assert all(f.normalization_status == "AMBIGUOUS" for f in facts)
    assert len({f.fact_id for f in facts}) == 2
    assert len({f.source_span_start for f in facts}) == 2


def test_repeated_processing_is_pure_and_does_not_invent_conflicting_interpretations():
    text = "letter_issue_date: 03-04-2024"
    identities = dict(ocr_run_id=uuid4(), document_version_id=uuid4())
    candidates = extract(text, **identities)
    assert candidates == extract(text, **identities)
    assert len(candidates) == 1  # No guessed day/month interpretations.
    facts = proposed_facts(candidates)
    assert mark_conflicting_candidates(facts) is None
    assert facts[0].state == "PROPOSED"


def test_equal_repeated_values_are_preserved_without_inventing_a_conflict():
    candidates = extract("lease_end_date: 2024-12-31\nlease_end_date: 31/12/2024")
    facts = proposed_facts(candidates)
    assert len(facts) == 2
    assert mark_conflicting_candidates(facts) is None
    assert all(f.state == "PROPOSED" for f in facts)


@pytest.mark.parametrize("corruption", ["version", "fields", "normalizer", "duplicate", "aliases", "newline"])
def test_malformed_catalog_fails_closed(tmp_path, monkeypatch, corruption):
    data = json.loads(module._ALIAS_FILE.read_text(encoding="utf-8"))
    if corruption == "version":
        data["version"] = True
    elif corruption == "fields":
        data["fields"] = []
    elif corruption == "normalizer":
        data["fields"][0]["normalizer"] = "eval"
    elif corruption == "duplicate":
        data["fields"][0]["aliases"] = ["letter_file_number"]
    elif corruption == "aliases":
        data["fields"][0]["aliases"] = "lease"
    else:
        data["fields"][0]["aliases"] = ["lease\nend"]
    path = tmp_path / "field_aliases.v1.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(module, "_ALIAS_FILE", path)
    with pytest.raises(ValueError):
        extract("lease_end_date: 2024-12-31")
