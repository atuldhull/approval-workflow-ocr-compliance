"""Pure field-candidate extraction from supplied OCR text and tokens.

This module does not read documents, run OCR, persist facts, or authorize access.
Only reviewed labels in the versioned data file are recognized. Callers retain
the canonical page text; offsets refer to it before any normalization.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
from uuid import UUID

from app.documents.normalization import (
    NormalizedValue,
    normalize_date_candidate,
    normalize_numerals,
    normalize_reference_value,
)
from app.documents.ocr import OcrToken


_ALIAS_FILE = Path(__file__).with_name("data") / "field_aliases.v1.json"
_NORMALIZERS = {
    "normalize_date_candidate": normalize_date_candidate,
    "normalize_reference_value": normalize_reference_value,
}


@dataclass(frozen=True)
class FieldRule:
    field_key: str
    normalizer: str
    labels: tuple[str, ...]


@dataclass(frozen=True)
class FieldCandidate:
    """Validated extractor output, not a persisted or reviewed fact.

    Source tokens retain their original text, spans, scripts and confidence.
    No candidate confidence is inferred from them. The page text is deliberately
    not duplicated in every candidate. Use extract_field_candidates to establish
    the relationship between tokens, candidate text and page offsets.
    """

    field_key: str
    value: NormalizedValue
    ocr_run_id: UUID
    document_version_id: UUID
    page_number: int
    source_span_start: int
    source_span_end: int
    source_tokens: tuple[OcrToken, ...]
    alias_version: int

    def __post_init__(self) -> None:
        """Keep directly constructed values within the extractor's typed contract."""
        rules = load_field_rules()
        if not isinstance(self.field_key, str) or self.field_key not in {rule.field_key for rule in rules}:
            raise ValueError("candidate field_key is not in the approved field catalog")
        if not isinstance(self.value, NormalizedValue):
            raise ValueError("candidate value must be a NormalizedValue")
        if (not isinstance(self.value.original_text, str)
                or not self.value.original_text.strip()):
            raise ValueError("candidate original text must not be blank")
        if not isinstance(self.ocr_run_id, UUID) or not isinstance(self.document_version_id, UUID):
            raise ValueError("candidate provenance identities must be UUIDs")
        for name, value in (
            ("page_number", self.page_number),
            ("source_span_start", self.source_span_start),
            ("source_span_end", self.source_span_end),
            ("alias_version", self.alias_version),
        ):
            if type(value) is not int:
                raise ValueError(f"candidate {name} must be an integer")
        if (self.page_number <= 0 or self.source_span_start < 0
                or self.source_span_end <= self.source_span_start
                or self.alias_version != 1):
            raise ValueError("candidate page, span, or alias version is invalid")
        if self.source_span_end - self.source_span_start != len(self.value.original_text):
            raise ValueError("candidate source span length must match its original text")
        if not isinstance(self.source_tokens, tuple) or not self.source_tokens:
            raise ValueError("candidate source_tokens must be a nonempty tuple")
        previous_end = -1
        for token in self.source_tokens:
            if not isinstance(token, OcrToken):
                raise ValueError("candidate source_tokens must contain OcrToken instances")
            if (token.page_number != self.page_number or token.span_start < previous_end
                    or token.span_end <= self.source_span_start
                    or token.span_start >= self.source_span_end):
                raise ValueError("candidate source tokens must overlap its page span in order")
            previous_end = token.span_end


def load_field_rules() -> tuple[FieldRule, ...]:
    """Load v1 rules without evaluating code or accepting unreviewed overrides."""
    try:
        data = json.loads(_ALIAS_FILE.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise ValueError("field alias data could not be loaded") from None
    if (not isinstance(data, dict) or set(data) != {"version", "fields"}
            or type(data["version"]) is not int or data["version"] != 1
            or not isinstance(data["fields"], list) or not data["fields"]):
        raise ValueError("invalid v1 field alias data")
    rules = []
    known_labels: set[str] = set()
    for entry in data["fields"]:
        if not isinstance(entry, dict) or set(entry) != {"field_key", "normalizer", "aliases"}:
            raise ValueError("invalid field rule")
        key, normalizer, aliases = entry["field_key"], entry["normalizer"], entry["aliases"]
        if not isinstance(key, str) or len(key) > 100 or not re.fullmatch(r"[a-z][a-z0-9_]*", key):
            raise ValueError("invalid field key")
        if not isinstance(normalizer, str) or normalizer not in _NORMALIZERS:
            raise ValueError("unsupported field normalizer")
        if not isinstance(aliases, list):
            raise ValueError("field aliases must be a list")
        labels = (key, *aliases)
        for label in labels:
            if (not isinstance(label, str) or not label or label != label.strip()
                    or any(char in label for char in "\r\n:\v\f\x1c\x1d\x1e\x85\u2028\u2029")
                    or label in known_labels):
                raise ValueError("field labels must be unique, nonblank, single-line literals")
            known_labels.add(label)
        rules.append(FieldRule(key, normalizer, labels))
    return tuple(rules)


def _validate_page_tokens(
    page_text: str, tokens: Sequence[OcrToken], page_number: int,
) -> tuple[OcrToken, ...]:
    if not isinstance(page_text, str):
        raise ValueError("page_text must be a string")
    if type(page_number) is not int or page_number <= 0:
        raise ValueError("page_number must be a positive integer")
    if not isinstance(tokens, (list, tuple)) or any(not isinstance(t, OcrToken) for t in tokens):
        raise ValueError("tokens must be a list or tuple of OcrToken instances")
    ordered = tuple(sorted(tokens, key=lambda token: token.span_start))
    previous_end = 0
    for token in ordered:
        if (token.page_number != page_number or token.span_end > len(page_text)
                or token.span_start < previous_end
                or page_text[token.span_start:token.span_end] != token.text
                or len(token.text.splitlines()) != 1
                or token.text.splitlines()[0] != token.text):
            raise ValueError("OCR token provenance must match nonoverlapping spans on the supplied page")
        previous_end = token.span_end
    return ordered


def _require_coverage(text: str, start: int, end: int, tokens: tuple[OcrToken, ...]) -> None:
    """Every non-whitespace source character needs an actual OCR token."""
    cursor = start
    for token in tokens:
        if token.span_end <= start or token.span_start >= end:
            continue
        if text[cursor:max(cursor, token.span_start)].strip():
            raise ValueError("field label or value is missing OCR token provenance")
        cursor = max(cursor, min(end, token.span_end))
    if text[cursor:end].strip():
        raise ValueError("field label or value is missing OCR token provenance")


def extract_field_candidates(
    *, page_text: str, tokens: Sequence[OcrToken], page_number: int,
    ocr_run_id: UUID, document_version_id: UUID,
) -> tuple[FieldCandidate, ...]:
    """Extract exact labels and same-line values, preserving raw page offsets.

    Labels start at a whitespace boundary and end before whitespace, a colon,
    or line end. A single colon after a label is a delimiter, not an alias.
    Values stop at line end or the next known label; surrounding whitespace is
    excluded, internal text is retained verbatim. No next-line guessing occurs.
    Empty values produce no candidate. Malformed provenance raises ValueError
    without returning a partial batch. Repeated labels remain separate.
    """
    if not isinstance(ocr_run_id, UUID) or not isinstance(document_version_id, UUID):
        raise ValueError("candidate run and document-version identities must be UUIDs")
    ordered = _validate_page_tokens(page_text, tokens, page_number)
    rules = load_field_rules()
    by_label = {label: rule for rule in rules for label in rule.labels}
    labels = "|".join(re.escape(label) for label in sorted(by_label, key=len, reverse=True))
    pattern = re.compile(r"(?<!\S)(?:" + labels + r")(?=\s|:|$)")
    candidates = []
    line_offset = 0
    for raw_line in page_text.splitlines(keepends=True):
        # splitlines recognizes CRLF and Unicode line separators without changing
        # their lengths in page-level coordinates.
        line = raw_line.splitlines()[0] if raw_line.splitlines() else ""
        matches = list(pattern.finditer(line))
        for index, match in enumerate(matches):
            # A recognized label without OCR provenance is not evidence for a
            # field occurrence, even when that label has no value after it.
            _require_coverage(page_text, line_offset + match.start(), line_offset + match.end(), ordered)
            end = matches[index + 1].start() if index + 1 < len(matches) else len(line)
            start = match.end()
            while start < end and line[start].isspace():
                start += 1
            if start < end and line[start] == ":":
                start += 1
            while start < end and line[start].isspace():
                start += 1
            while end > start and line[end - 1].isspace():
                end -= 1
            if start == end:
                continue
            source_start, source_end = line_offset + start, line_offset + end
            _require_coverage(page_text, line_offset + match.start(), source_end, ordered)
            source_tokens = tuple(t for t in ordered if t.span_end > source_start and t.span_start < source_end)
            original = page_text[source_start:source_end]
            rule = by_label[match.group()]
            normalized = _NORMALIZERS[rule.normalizer](normalize_numerals(original))
            candidates.append(FieldCandidate(
                field_key=rule.field_key,
                value=NormalizedValue(original, normalized.normalized_value, normalized.status),
                ocr_run_id=ocr_run_id,
                document_version_id=document_version_id,
                page_number=page_number,
                source_span_start=source_start,
                source_span_end=source_end,
                source_tokens=source_tokens,
                alias_version=1,
            ))
        line_offset += len(raw_line)
    return tuple(candidates)
