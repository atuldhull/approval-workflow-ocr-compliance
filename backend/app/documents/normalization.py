"""Lossless numeral and conservative date-candidate normalization."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date

from app.documents.states import NormalizationStatus


@dataclass(frozen=True)
class NormalizedValue:
    original_text: str
    normalized_value: str | None
    status: NormalizationStatus


def normalize_numerals(text: str) -> str:
    """Convert Unicode decimal digits to ASCII while preserving every other codepoint."""
    output: list[str] = []
    for char in text:
        try:
            output.append(str(unicodedata.decimal(char)))
        except (TypeError, ValueError):
            output.append(char)
    return "".join(output)


def normalize_reference_value(text: str) -> NormalizedValue:
    normalized = normalize_numerals(text)
    return NormalizedValue(text, normalized, NormalizationStatus.NORMALIZED)


_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_NUMERIC_DATE = re.compile(r"^(\d{1,4})([/.-])(\d{1,2})\2(\d{1,4})$")


def normalize_date_candidate(text: str) -> NormalizedValue:
    """Normalize ISO dates; resolve other numeric forms only when one date is possible.

    This parses candidates, not legal deadlines. It uses calendar validity to
    detect ambiguity, never an assumed institution or handbook date convention.
    """
    normalized = normalize_numerals(text.strip())
    iso = _ISO_DATE.fullmatch(normalized)
    if iso:
        try:
            parsed = date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        except ValueError:
            return NormalizedValue(text, None, NormalizationStatus.INVALID)
        return NormalizedValue(text, parsed.isoformat(), NormalizationStatus.NORMALIZED)

    match = _NUMERIC_DATE.fullmatch(normalized)
    if not match:
        return NormalizedValue(text, None, NormalizationStatus.UNSUPPORTED)
    first, _, second, third = match.groups()

    candidates: set[date] = set()
    # Year-first is unambiguous and accepted only with a four-digit year.
    if len(first) == 4:
        if len(third) > 2:
            return NormalizedValue(text, None, NormalizationStatus.INVALID)
        try:
            candidates.add(date(int(first), int(second), int(third)))
        except ValueError:
            pass
    else:
        if len(third) != 4:
            return NormalizedValue(text, None, NormalizationStatus.AMBIGUOUS)
        # Consider both common orders; normalize only if one valid calendar
        # date remains. If both are possible, keep the source as a proposal.
        year = int(third)
        for day, month in ((int(first), int(second)), (int(second), int(first))):
            try:
                candidates.add(date(year, month, day))
            except ValueError:
                continue

    if not candidates:
        return NormalizedValue(text, None, NormalizationStatus.INVALID)
    if len(candidates) > 1:
        return NormalizedValue(text, None, NormalizationStatus.AMBIGUOUS)
    return NormalizedValue(text, next(iter(candidates)).isoformat(), NormalizationStatus.NORMALIZED)
