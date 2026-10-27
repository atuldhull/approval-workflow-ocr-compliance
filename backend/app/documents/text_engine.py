"""Local text engine: the PDF text layer through pypdf, otherwise Tesseract through its command line.

Selection (DOCUMENT_TEXT_ENGINE):
- ``local`` (default): this engine. Nothing leaves the machine; no model is downloaded at run time.
- ``none``: no engine, so extraction answers 503 as before.

How a version is read:
- A PDF page with a text layer is read with pypdf. Its tokens get confidence 1: the text was read, not
  recognised, so there is nothing to be unsure about apart from what the PDF itself says.
- An image, and a PDF page without a text layer (its embedded images), go to Tesseract (``eng``, plus
  ``hin`` where that language pack is installed). Tesseract's word confidences are scaled to 0..1 and are
  **uncalibrated**: they are recorded for the reviewer, never used as a threshold.
- If Tesseract is needed but its binary or every configured language is missing, the read fails with
  ADAPTER_UNAVAILABLE, so the OCR run is FAILED and can be retried once Tesseract is installed. It never
  returns an empty result in that case.

Token scripts come from ``ocr.detect_script``; numerals and dates are normalised later by the candidate
extractor, unchanged. Every value found here is only a PROPOSED fact until a person reviews it.
"""

from __future__ import annotations

import csv
import io
import os
import re
import shutil
import subprocess
from decimal import Decimal, InvalidOperation
from typing import Callable, Sequence

import pypdf
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from app.documents.config import DocumentConfigurationError
from app.documents.extraction import PageText, TextEngineError
from app.documents.ocr import OcrToken, detect_script
from app.documents.states import OcrErrorCode

ENGINE_ENV = "DOCUMENT_TEXT_ENGINE"
TESSERACT_CMD_ENV = "DOCUMENT_TESSERACT_CMD"
OCR_LANGUAGES_ENV = "DOCUMENT_OCR_LANGUAGES"
OCR_TIMEOUT_ENV = "DOCUMENT_OCR_TIMEOUT_SECONDS"
DEFAULT_LANGUAGES = ("eng", "hin")
DEFAULT_TIMEOUT_SECONDS = 60.0
IMAGE_TYPES = frozenset({"image/png", "image/jpeg"})
TEXT_LAYER_CONFIDENCE = Decimal(1)
_WORD = re.compile(r"\S+")
_LANGUAGE = re.compile(r"^[A-Za-z0-9_]{1,32}$")

Runner = Callable[..., subprocess.CompletedProcess]


def _unavailable() -> TextEngineError:
    return TextEngineError(OcrErrorCode.ADAPTER_UNAVAILABLE)


def text_layer_tokens(text: str, page_number: int) -> tuple[OcrToken, ...]:
    """One token per whitespace-separated word, with spans into the page text exactly as given."""
    return tuple(OcrToken(m.group(), page_number, m.start(), m.end(), TEXT_LAYER_CONFIDENCE, detect_script(m.group()))
                 for m in _WORD.finditer(text))


def compose_page(lines: Sequence[Sequence[tuple[str, Decimal]]], page_number: int) -> PageText:
    """Join recognised words with single spaces and lines with newlines, keeping each word's span."""
    parts: list[str] = []
    tokens: list[OcrToken] = []
    offset = 0
    for line in lines:
        words = [(w, c) for w, c in line if w.strip()]
        if not words:
            continue
        if parts:
            parts.append("\n")
            offset += 1
        for index, (word, confidence) in enumerate(words):
            if index:
                parts.append(" ")
                offset += 1
            parts.append(word)
            tokens.append(OcrToken(word, page_number, offset, offset + len(word), confidence, detect_script(word)))
            offset += len(word)
    return PageText(page_number, "".join(parts), tuple(tokens))


def _confidence(raw: str) -> Decimal:
    try:
        value = Decimal(raw) / 100
    except (InvalidOperation, ValueError):
        return Decimal(0)
    if not value.is_finite():
        return Decimal(0)
    return min(Decimal(1), max(Decimal(0), value)).quantize(Decimal("0.00001"))


def parse_tsv(output: str) -> list[list[tuple[str, Decimal]]]:
    """Words (level 5 rows) of Tesseract's TSV output, grouped into lines in reading order."""
    reader = csv.DictReader(io.StringIO(output), delimiter="\t", quoting=csv.QUOTE_NONE)
    required = {"level", "block_num", "par_num", "line_num", "conf", "text"}
    if reader.fieldnames is None or not required <= set(reader.fieldnames):
        raise TextEngineError(OcrErrorCode.PROCESSING_FAILED)
    lines: dict[tuple[str, str, str, str], list[tuple[str, Decimal]]] = {}
    for row in reader:
        if row.get("level") != "5":
            continue
        word = (row.get("text") or "").strip()
        if not word or any(ch.isspace() for ch in word):
            continue
        key = (row.get("page_num", ""), row["block_num"], row["par_num"], row["line_num"])
        lines.setdefault(key, []).append((word, _confidence(row["conf"])))
    return list(lines.values())


class TesseractCli:
    """Runs the ``tesseract`` binary on one image at a time (bytes on stdin, TSV on stdout)."""

    def __init__(self, command: str = "tesseract", languages: Sequence[str] = DEFAULT_LANGUAGES,
                 timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS, run: Runner = subprocess.run,
                 which: Callable[[str], str | None] = shutil.which):
        if not command.strip():
            raise DocumentConfigurationError(f"{TESSERACT_CMD_ENV} must not be blank")
        if not languages or any(not _LANGUAGE.fullmatch(lang) for lang in languages):
            raise DocumentConfigurationError(f"{OCR_LANGUAGES_ENV} must list Tesseract language codes, e.g. eng+hin")
        if timeout_seconds <= 0:
            raise DocumentConfigurationError(f"{OCR_TIMEOUT_ENV} must be a positive number")
        self.command = command
        self.languages = tuple(languages)
        self.timeout = timeout_seconds
        self._run = run
        self._which = which
        self._installed: tuple[str, ...] | None = None
        self._version: str | None = None

    def binary(self) -> str | None:
        return self._which(self.command)

    def _call(self, args: Sequence[str], data: bytes | None = None) -> subprocess.CompletedProcess:
        binary = self.binary()
        if binary is None:
            raise _unavailable()
        try:
            return self._run([binary, *args], input=data, capture_output=True, timeout=self.timeout, check=False)
        except subprocess.TimeoutExpired:
            raise TextEngineError(OcrErrorCode.TIMEOUT) from None
        except OSError:
            raise _unavailable() from None

    def version(self) -> str | None:
        """The installed Tesseract version, or None when the binary is missing or does not answer."""
        if self._version is None and self.binary() is not None:
            try:
                done = self._call(["--version"])
            except TextEngineError:
                return None
            first = (done.stdout or b"").decode("utf-8", "replace").strip().splitlines()
            match = re.search(r"(\d+(?:\.\d+)*)", first[0]) if first else None
            self._version = match.group(1) if match else None
        return self._version

    def languages_in_use(self) -> tuple[str, ...]:
        """The configured languages that are installed; ADAPTER_UNAVAILABLE when none of them are."""
        if self._installed is None:
            done = self._call(["--list-langs"])
            if done.returncode != 0:
                raise _unavailable()
            # The first line is a heading ("List of available languages ..."); the rest are codes.
            listed = (done.stdout or b"").decode("utf-8", "replace").splitlines()[1:]
            installed = {line.strip() for line in listed if line.strip()}
            self._installed = tuple(lang for lang in self.languages if lang in installed)
        if not self._installed:
            raise _unavailable()
        return self._installed

    def recognize(self, image: bytes) -> list[list[tuple[str, Decimal]]]:
        languages = "+".join(self.languages_in_use())
        done = self._call(["stdin", "stdout", "-l", languages, "tsv"], data=image)
        if done.returncode != 0:
            raise TextEngineError(OcrErrorCode.PROCESSING_FAILED)
        return parse_tsv((done.stdout or b"").decode("utf-8", "replace"))


class LocalTextEngine:
    """TextEngine: pypdf for PDF text layers, Tesseract for images and pages without one."""

    adapter_key = "local.pypdf-tesseract"

    def __init__(self, ocr: TesseractCli | None = None):
        self.ocr = ocr or TesseractCli()

    @property
    def model_version(self) -> str:
        tesseract = self.ocr.version() or "absent"
        return f"pypdf {pypdf.__version__}; tesseract {tesseract}; confidence uncalibrated"[:100]

    @classmethod
    def from_environment(cls) -> LocalTextEngine:
        raw_timeout = os.environ.get(OCR_TIMEOUT_ENV, str(DEFAULT_TIMEOUT_SECONDS))
        try:
            timeout = float(raw_timeout)
        except ValueError:
            raise DocumentConfigurationError(f"{OCR_TIMEOUT_ENV} must be a positive number") from None
        languages = tuple(lang.strip() for lang in os.environ.get(OCR_LANGUAGES_ENV, "+".join(DEFAULT_LANGUAGES))
                          .split("+") if lang.strip())
        return cls(TesseractCli(os.environ.get(TESSERACT_CMD_ENV, "tesseract"), languages, timeout))

    def read(self, content: bytes, *, media_type: str) -> Sequence[PageText]:
        if media_type in IMAGE_TYPES:
            return [compose_page(self.ocr.recognize(content), 1)]
        if media_type != "application/pdf":
            raise TextEngineError(OcrErrorCode.INPUT_REJECTED)
        try:
            reader = PdfReader(io.BytesIO(content), strict=True)
            pages = list(reader.pages)
        except (PyPdfError, ValueError, KeyError, TypeError, OSError):
            raise TextEngineError(OcrErrorCode.INPUT_REJECTED) from None
        result: list[PageText] = []
        for number, page in enumerate(pages, start=1):
            try:
                text = page.extract_text() or ""
            except (PyPdfError, ValueError, KeyError, TypeError):
                raise TextEngineError(OcrErrorCode.INPUT_REJECTED) from None
            if text.strip():
                result.append(PageText(number, text, text_layer_tokens(text, number)))
            else:
                result.append(self._ocr_page(page, number))
        return result

    def _ocr_page(self, page, number: int) -> PageText:
        """A page without a text layer: recognise its embedded images (a scanned page is one image)."""
        self.ocr.languages_in_use()   # fail as unavailable before touching the page, even if it has no images
        try:
            images = [image.data for image in page.images]
        except Exception:  # noqa: BLE001 - pypdf/Pillow raise many types for undecodable images
            raise TextEngineError(OcrErrorCode.PROCESSING_FAILED) from None
        lines: list[list[tuple[str, Decimal]]] = []
        for data in images:
            lines.extend(self.ocr.recognize(data))
        return compose_page(lines, number)


def text_engine_from_environment() -> LocalTextEngine | None:
    """The engine DOCUMENT_TEXT_ENGINE selects; None for ``none`` (extraction then answers 503)."""
    choice = os.environ.get(ENGINE_ENV, "local").strip().lower()
    if choice == "none":
        return None
    if choice != "local":
        raise DocumentConfigurationError(f"{ENGINE_ENV} must be local or none, not {choice!r}")
    return LocalTextEngine.from_environment()
