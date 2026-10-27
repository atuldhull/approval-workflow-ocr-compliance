"""Text-engine boundary used by fact extraction.

A TextEngine turns the bytes of one scanner-approved version into page text and
OCR tokens whose spans index that text. The candidate extractor then finds
fields in it. The default engine (text_engine.py, selected by DOCUMENT_TEXT_ENGINE)
reads PDF text layers with pypdf and runs a local Tesseract for scans; tests and
deployments can install another one with service.configure(engine=...).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, Sequence, runtime_checkable

from app.documents.ocr import OcrToken, Script
from app.documents.states import OcrErrorCode


@dataclass(frozen=True)
class PageText:
    page_number: int
    text: str
    tokens: tuple[OcrToken, ...]


class TextEngineError(RuntimeError):
    """Recognition failed; the OCR run is recorded as FAILED with this stable code."""

    def __init__(self, code: OcrErrorCode):
        super().__init__(code.value)
        self.code = OcrErrorCode(code)


@runtime_checkable
class TextEngine(Protocol):
    adapter_key: str
    model_version: str | None

    def read(self, content: bytes, *, media_type: str) -> Sequence[PageText]: ...


def candidate_script(tokens: Sequence[OcrToken]) -> Script:
    """One script when every source token agrees, otherwise MIXED."""
    scripts = {token.script for token in tokens}
    return next(iter(scripts)) if len(scripts) == 1 else Script.MIXED


def candidate_confidence(tokens: Sequence[OcrToken]) -> Decimal:
    """The weakest source token: a value is only as certain as its least certain part."""
    return min(token.confidence for token in tokens)
