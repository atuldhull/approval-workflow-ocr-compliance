"""Replaceable OCR boundary, explicit script routing, and auditable run lifecycle.

This module defines contracts only. It deliberately contains no model runtime,
HTTP endpoint, file reader, or default adapter. It does not authorize sending
document bytes to a remote service; any future adapter needs an approved
deployment and privacy review.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Protocol, Sequence
from uuid import UUID, uuid4, uuid5
import unicodedata

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.documents.models import OcrRun
from app.documents.states import OcrErrorCode, OcrRunStatus


class Script(StrEnum):
    LATIN = "LATIN"
    DEVANAGARI = "DEVANAGARI"
    BENGALI = "BENGALI"
    GUJARATI = "GUJARATI"
    GURMUKHI = "GURMUKHI"
    KANNADA = "KANNADA"
    MALAYALAM = "MALAYALAM"
    ODIA = "ODIA"
    TAMIL = "TAMIL"
    TELUGU = "TELUGU"
    MIXED = "MIXED"
    UNKNOWN = "UNKNOWN"
    UNSUPPORTED = "UNSUPPORTED"


SUPPORTED_SCRIPTS = frozenset(
    {
        Script.LATIN,
        Script.DEVANAGARI,
        Script.BENGALI,
        Script.GUJARATI,
        Script.GURMUKHI,
        Script.KANNADA,
        Script.MALAYALAM,
        Script.ODIA,
        Script.TAMIL,
        Script.TELUGU,
    }
)

# Script aliases only; language aliases are intentionally excluded because a
# language may be written in more than one script.
_SCRIPT_ALIASES = {
    "latn": Script.LATIN,
    "latin": Script.LATIN,
    "deva": Script.DEVANAGARI,
    "devanagari": Script.DEVANAGARI,
    "beng": Script.BENGALI,
    "bengali": Script.BENGALI,
    "gujr": Script.GUJARATI,
    "gujarati": Script.GUJARATI,
    "guru": Script.GURMUKHI,
    "gurmukhi": Script.GURMUKHI,
    "knda": Script.KANNADA,
    "kannada": Script.KANNADA,
    "mlym": Script.MALAYALAM,
    "malayalam": Script.MALAYALAM,
    "orya": Script.ODIA,
    "odia": Script.ODIA,
    "oriya": Script.ODIA,
    "taml": Script.TAMIL,
    "tamil": Script.TAMIL,
    "telu": Script.TELUGU,
    "telugu": Script.TELUGU,
}
_UNICODE_SCRIPT_PREFIXES = {
    "DEVANAGARI": Script.DEVANAGARI,
    "BENGALI": Script.BENGALI,
    "GUJARATI": Script.GUJARATI,
    "GURMUKHI": Script.GURMUKHI,
    "KANNADA": Script.KANNADA,
    "MALAYALAM": Script.MALAYALAM,
    "ORIYA": Script.ODIA,
    "TAMIL": Script.TAMIL,
    "TELUGU": Script.TELUGU,
}


class ScriptRoutingError(ValueError):
    """The script hint cannot be routed without guessing."""


class OcrAdapter(Protocol):
    """Adapter contract. Implementations own model loading and resource limits."""

    adapter_key: str
    model_version: str | None
    supported_scripts: frozenset[Script]

    def recognize_page(
        self, page_bytes: bytes, *, page_number: int, script: Script
    ) -> Sequence["OcrToken"]:
        """Recognize one already-authorized, scanner-approved page."""
        ...


@dataclass(frozen=True)
class OcrToken:
    text: str
    page_number: int
    span_start: int
    span_end: int
    confidence: Decimal
    script: Script

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("OCR token text must not be blank")
        if self.page_number <= 0 or self.span_start < 0 or self.span_end <= self.span_start:
            raise ValueError("OCR token needs a positive page and half-open source span")
        try:
            confidence = Decimal(str(self.confidence))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("OCR confidence must be a finite number from 0 to 1") from exc
        if not confidence.is_finite() or not Decimal(0) <= confidence <= Decimal(1):
            raise ValueError("OCR confidence must be a finite number from 0 to 1")
        object.__setattr__(self, "confidence", confidence)


def normalize_script_hint(hint: Script | str) -> Script:
    if isinstance(hint, Script):
        return hint
    if not isinstance(hint, str):
        raise ScriptRoutingError("a script hint is required")
    try:
        return _SCRIPT_ALIASES[hint.strip().casefold()]
    except KeyError:
        raise ScriptRoutingError("unknown script hint; use an explicit supported script") from None


def _script_for_character(char: str) -> Script | None:
    category = unicodedata.category(char)
    if category[0] not in {"L", "M", "N"}:
        return None
    name = unicodedata.name(char, "")
    for prefix, script in _UNICODE_SCRIPT_PREFIXES.items():
        if name.startswith(prefix + " "):
            return script
    if category.startswith("L") and "LATIN" in name:
        return Script.LATIN
    if category.startswith("L"):
        return Script.UNSUPPORTED
    return None


def detect_script(text: str) -> Script:
    """Classify observed Unicode script; never select a dominant script."""
    observed = {_script_for_character(char) for char in text}
    observed.discard(None)
    if not observed:
        return Script.UNKNOWN
    if len(observed) > 1:
        return Script.MIXED
    return next(iter(observed))


class AdapterRouter:
    """Route only exact script matches; duplicate claims are rejected at setup."""

    def __init__(self, adapters: Sequence[OcrAdapter]):
        by_script: dict[Script, OcrAdapter] = {}
        for adapter in adapters:
            if not adapter.adapter_key.strip():
                raise ValueError("OCR adapter key must not be blank")
            for script in adapter.supported_scripts:
                if script not in SUPPORTED_SCRIPTS:
                    raise ValueError(f"adapter declares unsupported script code: {script}")
                if script in by_script:
                    raise ValueError(f"more than one OCR adapter claims {script.value}")
                by_script[script] = adapter
        self._by_script = by_script

    def for_hint(self, hint: Script | str) -> OcrAdapter:
        script = normalize_script_hint(hint)
        if script not in SUPPORTED_SCRIPTS:
            raise ScriptRoutingError(f"{script.value} is not an enabled OCR script")
        try:
            return self._by_script[script]
        except KeyError:
            raise ScriptRoutingError(f"no OCR adapter is configured for {script.value}") from None

    def for_text(self, text: str) -> OcrAdapter:
        script = detect_script(text)
        if script in {Script.MIXED, Script.UNKNOWN, Script.UNSUPPORTED}:
            raise ScriptRoutingError(f"text script is {script.value}; explicit review or routing is required")
        return self.for_hint(script)

    def recognize_page(
        self, page_bytes: bytes, *, page_number: int, script_hint: Script | str
    ) -> tuple[OcrToken, ...]:
        """Call the uniquely routed adapter and validate returned provenance."""
        if not isinstance(page_bytes, bytes) or not page_bytes:
            raise ValueError("OCR adapter input must be nonempty page bytes")
        if page_number <= 0:
            raise ValueError("page_number must be positive")
        script = normalize_script_hint(script_hint)
        adapter = self.for_hint(script)
        tokens = tuple(adapter.recognize_page(page_bytes, page_number=page_number, script=script))
        if any(token.page_number != page_number or token.script is not script for token in tokens):
            raise ValueError("OCR adapter returned inconsistent page or script provenance")
        return tokens


_RETRY_NAMESPACE = UUID("4263f47e-f8bb-4958-9903-7f44f3c95f20")


def make_ocr_run(
    *, document_version_id: UUID, adapter_key: str, model_version: str | None, created_at: datetime
) -> OcrRun:
    if not adapter_key.strip():
        raise ValueError("adapter_key must not be blank")
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise ValueError("OCR run timestamps must be timezone-aware")
    return OcrRun(
        ocr_run_id=uuid4(),
        document_version_id=document_version_id,
        adapter_key=adapter_key,
        model_version=model_version,
        status=OcrRunStatus.QUEUED.value,
        attempt_number=1,
        created_at=created_at,
    )


def retry_failed_run(previous: OcrRun, *, created_at: datetime) -> OcrRun:
    """Create a deterministic child attempt; repeat calls produce the same ID."""
    if previous.status != OcrRunStatus.FAILED.value:
        raise ValueError("only a failed OCR run can be retried")
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise ValueError("OCR run timestamps must be timezone-aware")
    if previous.ocr_run_id is None or previous.document_version_id is None:
        raise ValueError("the failed OCR run must have persisted identity and provenance")
    if previous.finished_at is None:
        raise ValueError("the failed OCR run must have a completion timestamp before retry")
    if previous.error_code is None:
        raise ValueError("the failed OCR run must have a stable error code before retry")
    if created_at < previous.finished_at:
        raise ValueError("OCR retry cannot precede the failed attempt's completion")
    return OcrRun(
        ocr_run_id=uuid5(_RETRY_NAMESPACE, str(previous.ocr_run_id)),
        document_version_id=previous.document_version_id,
        adapter_key=previous.adapter_key,
        model_version=previous.model_version,
        status=OcrRunStatus.QUEUED.value,
        attempt_number=previous.attempt_number + 1,
        retry_of_ocr_run_id=previous.ocr_run_id,
        created_at=created_at,
    )


def enqueue_retry(session: Session, previous: OcrRun, *, created_at: datetime) -> OcrRun:
    """Idempotently persist one retry row per failed attempt in the caller's transaction."""
    retry = retry_failed_run(previous, created_at=created_at)
    existing = session.scalar(
        select(OcrRun).where(OcrRun.retry_of_ocr_run_id == previous.ocr_run_id)
    )
    if existing is not None:
        return existing
    session.execute(
        pg_insert(OcrRun)
        .values(
            ocr_run_id=retry.ocr_run_id,
            document_version_id=retry.document_version_id,
            adapter_key=retry.adapter_key,
            model_version=retry.model_version,
            status=retry.status,
            attempt_number=retry.attempt_number,
            retry_of_ocr_run_id=retry.retry_of_ocr_run_id,
            created_at=retry.created_at,
        )
        .on_conflict_do_nothing(index_elements=[OcrRun.retry_of_ocr_run_id])
    )
    persisted = session.scalar(
        select(OcrRun).where(OcrRun.retry_of_ocr_run_id == previous.ocr_run_id)
    )
    if persisted is None:
        raise RuntimeError("OCR retry was not persisted")
    return persisted


def transition_ocr_run(
    run: OcrRun,
    target: OcrRunStatus,
    *,
    at: datetime,
    error_code: OcrErrorCode | None = None,
) -> None:
    """Apply one legal attempt transition; retries use a new linked row."""
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("OCR run timestamps must be timezone-aware")
    current = OcrRunStatus(run.status)
    target = OcrRunStatus(target)
    if error_code is not None:
        error_code = OcrErrorCode(error_code)
    allowed = {
        OcrRunStatus.QUEUED: {OcrRunStatus.RUNNING, OcrRunStatus.FAILED},
        OcrRunStatus.RUNNING: {OcrRunStatus.SUCCEEDED, OcrRunStatus.FAILED},
        OcrRunStatus.SUCCEEDED: set(),
        OcrRunStatus.FAILED: set(),
    }
    if target not in allowed[current]:
        raise ValueError(f"invalid OCR run transition: {current.value} -> {target.value}")
    if target is OcrRunStatus.FAILED and error_code is None:
        raise ValueError("failed OCR runs need a stable error code")
    if target is not OcrRunStatus.FAILED and error_code is not None:
        raise ValueError("error codes are only valid on failed OCR runs")
    if run.created_at is not None and at < run.created_at:
        raise ValueError("OCR run transition time cannot precede creation")
    if target is OcrRunStatus.RUNNING:
        run.started_at = at
    if target in {OcrRunStatus.SUCCEEDED, OcrRunStatus.FAILED}:
        if run.started_at is not None and at < run.started_at:
            raise ValueError("OCR run transition time cannot precede its start")
        run.finished_at = at
    run.status = target.value
    run.error_code = error_code.value if error_code else None
