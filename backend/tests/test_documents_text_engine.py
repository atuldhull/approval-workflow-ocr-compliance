"""The local text engine: pypdf for PDF text layers, the Tesseract command line for scans and images.

Tesseract is not required on the test machine: its command line is replaced by a fake that answers like the
real binary (``--version``, ``--list-langs``, TSV on stdout), or by "not installed". All files are synthetic
and built in the tests.
"""
import io
import subprocess
from decimal import Decimal

import pytest
from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.documents import service
from app.documents.config import DocumentLimits
from app.documents.extraction import TextEngine, TextEngineError
from app.documents.ocr import Script
from app.documents.states import OcrErrorCode
from app.documents.storage import LocalQuarantineStorage
from app.documents.text_engine import (LocalTextEngine, TesseractCli, compose_page, parse_tsv,
                                       text_engine_from_environment)
from app.platform.errors import ServiceUnavailable
from test_documents_api import BUREAU, COMMITTEE, FakeScanner, new_application, upload

LETTER = ["letter_issue_date: 2025-03-12", "letter_file_number: F.No.42/2025"]
TSV_HEADER = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"


def text_pdf(*pages: list[str]) -> bytes:
    """A synthetic PDF whose pages carry a real text layer (Helvetica, one line per entry)."""
    writer = PdfWriter()
    for lines in pages:
        page = writer.add_blank_page(width=595, height=842)
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                                 NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
        shown = " ".join("(" + line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ") Tj T*"
                         for line in lines)
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 72 770 Td 14 TL {shown} ET".encode("latin-1"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def scanned_pdf() -> bytes:
    """A PDF page that is only an image, as a scanner produces: no text layer."""
    out = io.BytesIO()
    Image.new("L", (40, 20), 255).save(out, "PDF")
    return out.getvalue()


def png() -> bytes:
    out = io.BytesIO()
    Image.new("L", (40, 20), 255).save(out, "PNG")
    return out.getvalue()


def tsv(*lines: list[tuple[str, int]]) -> str:
    rows = [TSV_HEADER, "1\t1\t0\t0\t0\t0\t0\t0\t40\t20\t-1\t"]
    for n, line in enumerate(lines, start=1):
        rows.append(f"4\t1\t1\t1\t{n}\t0\t0\t0\t40\t5\t-1\t")
        for w, (word, conf) in enumerate(line, start=1):
            rows.append(f"5\t1\t1\t1\t{n}\t{w}\t0\t0\t5\t5\t{conf}\t{word}")
    return "\n".join(rows) + "\n"


class FakeTesseract:
    """Stands in for subprocess.run on the tesseract binary."""

    def __init__(self, output: str = "", languages=("eng", "hin", "osd"), returncode: int = 0):
        self.output, self.languages, self.returncode = output, languages, returncode
        self.calls: list[list[str]] = []
        self.timeout = False

    def __call__(self, args, *, input=None, capture_output, timeout, check):
        self.calls.append(list(args))
        assert capture_output and not check and timeout > 0
        if args[1] == "--version":
            return subprocess.CompletedProcess(args, 0, b"tesseract 5.3.4\n leptonica-1.84.1\n", b"")
        if args[1] == "--list-langs":
            listing = "List of available languages in \"/usr/share/tesseract-ocr/5/tessdata/\" (3):\n"
            return subprocess.CompletedProcess(args, 0, (listing + "\n".join(self.languages) + "\n").encode(), b"")
        if self.timeout:
            raise subprocess.TimeoutExpired(args, timeout)
        assert args[1:3] == ["stdin", "stdout"] and args[-1] == "tsv" and input
        return subprocess.CompletedProcess(args, self.returncode, self.output.encode("utf-8"), b"")


def engine_with(fake: FakeTesseract | None, languages=("eng", "hin")) -> LocalTextEngine:
    which = (lambda cmd: "/usr/bin/tesseract") if fake is not None else (lambda cmd: None)
    return LocalTextEngine(TesseractCli("tesseract", languages, 30, run=fake or FakeTesseract(), which=which))


# ---- PDF text layer ----

def test_a_text_layer_pdf_is_read_page_by_page_without_tesseract():
    engine = engine_with(None)            # Tesseract is not installed, and is not needed
    assert isinstance(engine, TextEngine)
    pages = engine.read(text_pdf(LETTER, ["page two"]), media_type="application/pdf")
    assert [p.page_number for p in pages] == [1, 2]
    assert pages[0].text.splitlines() == LETTER
    for page in pages:
        assert all(page.text[t.span_start:t.span_end] == t.text for t in page.tokens)
        assert all(t.confidence == Decimal(1) and t.page_number == page.page_number for t in page.tokens)
    assert [t.text for t in pages[1].tokens] == ["page", "two"]
    assert {t.script for t in pages[0].tokens if t.text.startswith("letter")} == {Script.LATIN}
    assert engine.model_version == "pypdf 6.19.0; tesseract absent; confidence uncalibrated"


def test_a_malformed_pdf_is_rejected_as_input():
    with pytest.raises(TextEngineError) as e:
        engine_with(None).read(b"%PDF-1.7\nnot really a pdf", media_type="application/pdf")
    assert e.value.code is OcrErrorCode.INPUT_REJECTED
    with pytest.raises(TextEngineError) as e:
        engine_with(None).read(b"GIF89a", media_type="image/gif")
    assert e.value.code is OcrErrorCode.INPUT_REJECTED


# ---- Tesseract path ----

def test_without_tesseract_a_scan_fails_as_unavailable_never_empty():
    for content, media_type in ((scanned_pdf(), "application/pdf"), (png(), "image/png"),
                                (text_pdf([]), "application/pdf")):   # a page without text needs OCR too
        with pytest.raises(TextEngineError) as e:
            engine_with(None).read(content, media_type=media_type)
        assert e.value.code is OcrErrorCode.ADAPTER_UNAVAILABLE


def test_tesseract_without_any_configured_language_is_unavailable():
    fake = FakeTesseract(tsv([("x", 90)]), languages=("osd",))
    with pytest.raises(TextEngineError) as e:
        engine_with(fake).read(png(), media_type="image/png")
    assert e.value.code is OcrErrorCode.ADAPTER_UNAVAILABLE


def test_an_image_is_recognised_with_installed_languages_only():
    fake = FakeTesseract(tsv([("letter_issue_date:", 96), ("२०२५-०३-१२", 71)]), languages=("eng", "osd"))
    engine = engine_with(fake)
    [page] = engine.read(png(), media_type="image/png")
    assert page.text == "letter_issue_date: २०२५-०३-१२"
    recognise = [c for c in fake.calls if "stdin" in c]
    assert recognise == [["/usr/bin/tesseract", "stdin", "stdout", "-l", "eng", "tsv"]]   # hin not installed
    label, value = page.tokens
    assert (label.script, label.confidence) == (Script.LATIN, Decimal("0.96"))
    assert (value.script, value.confidence) == (Script.DEVANAGARI, Decimal("0.71"))
    assert engine.model_version == "pypdf 6.19.0; tesseract 5.3.4; confidence uncalibrated"


def test_a_scanned_pdf_page_goes_to_tesseract_with_eng_and_hin():
    fake = FakeTesseract(tsv([("letter_file_number:", 88), ("F.No.42/2025", 64)]))
    [page] = engine_with(fake).read(scanned_pdf(), media_type="application/pdf")
    assert page.text == "letter_file_number: F.No.42/2025"
    assert [c for c in fake.calls if "stdin" in c][0][3:5] == ["-l", "eng+hin"]


def test_tesseract_failures_have_stable_codes():
    fake = FakeTesseract(returncode=1)
    with pytest.raises(TextEngineError) as e:
        engine_with(fake).read(png(), media_type="image/png")
    assert e.value.code is OcrErrorCode.PROCESSING_FAILED
    fake = FakeTesseract()
    fake.timeout = True
    with pytest.raises(TextEngineError) as e:
        engine_with(fake).read(png(), media_type="image/png")
    assert e.value.code is OcrErrorCode.TIMEOUT
    with pytest.raises(TextEngineError) as e:
        parse_tsv("not\ta tesseract tsv\n")
    assert e.value.code is OcrErrorCode.PROCESSING_FAILED


def test_tsv_words_are_grouped_into_lines_with_exact_spans():
    lines = parse_tsv(tsv([("a", 50), ("bb", -1)], [("ccc", 100)]))
    assert lines == [[("a", Decimal("0.5")), ("bb", Decimal(0))], [("ccc", Decimal(1))]]
    page = compose_page(lines, 3)
    assert page.text == "a bb\nccc"
    assert [(t.text, t.span_start, t.span_end, t.page_number) for t in page.tokens] == [
        ("a", 0, 1, 3), ("bb", 2, 4, 3), ("ccc", 5, 8, 3)]


# ---- selection ----

def test_the_engine_is_selected_from_the_environment(monkeypatch):
    monkeypatch.delenv("DOCUMENT_TEXT_ENGINE", raising=False)
    monkeypatch.setenv("DOCUMENT_OCR_LANGUAGES", "eng+hin+mar")
    monkeypatch.setenv("DOCUMENT_TESSERACT_CMD", "/opt/tesseract/bin/tesseract")
    engine = text_engine_from_environment()
    assert isinstance(engine, LocalTextEngine)
    assert engine.ocr.languages == ("eng", "hin", "mar") and engine.ocr.command == "/opt/tesseract/bin/tesseract"
    monkeypatch.setenv("DOCUMENT_TEXT_ENGINE", "none")
    assert text_engine_from_environment() is None
    service.configure(engine=None)
    try:
        with pytest.raises(ServiceUnavailable):
            service.engine()
        monkeypatch.setenv("DOCUMENT_TEXT_ENGINE", "cloud")
        with pytest.raises(ServiceUnavailable):
            service.engine()
        monkeypatch.setenv("DOCUMENT_TEXT_ENGINE", "local")
        assert isinstance(service.engine(), LocalTextEngine)
    finally:
        service.configure(engine=None)


# ---- end to end over HTTP ----

@pytest.fixture
def local_docs(client, tmp_path):
    service.configure(storage=LocalQuarantineStorage(tmp_path / "store", limits=DocumentLimits(10 * 1024 * 1024, 20,
                                                                                               4_000_000)),
                      scanner=FakeScanner(), engine=engine_with(None))
    yield client
    service.configure(storage=None, scanner=None, engine=None)


def test_a_text_pdf_is_extracted_into_proposed_facts(local_docs):
    client = local_docs
    app_id = new_application(client)
    r = upload(client, app_id, text_pdf(LETTER), key="text-pdf-0001", doc_type="APPROVAL_LETTER")
    assert r.status_code == 201, r.text
    version = r.json()["version"]
    r = client.post(f"/api/document-versions/{version['version_id']}/extract", headers=COMMITTEE)
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "SUCCEEDED" and len(r.json()["fact_ids"]) == 2
    body = client.get(f"/api/document-versions/{version['version_id']}/facts", headers=BUREAU).json()
    by_field = {f["field_key"]: f for f in body["facts"]}
    date = by_field["letter_issue_date"]
    assert (date["candidate_text"], date["normalized_value"], date["normalization_status"]) == (
        "2025-03-12", "2025-03-12", "NORMALIZED")
    assert by_field["letter_file_number"]["normalized_value"] == "F.No.42/2025"
    assert all(f["status"] == "proposed" and f["review_decision"] is None and f["page_number"] == 1
               for f in body["facts"])


def test_a_scan_without_tesseract_is_a_failed_retryable_run(local_docs):
    client = local_docs
    app_id = new_application(client)
    r = upload(client, app_id, scanned_pdf(), key="scan-pdf-0001", doc_type="APPROVAL_LETTER")
    assert r.status_code == 201, r.text
    version_id = r.json()["version"]["version_id"]
    r = client.post(f"/api/document-versions/{version_id}/extract", headers=COMMITTEE)
    assert r.status_code == 201
    assert (r.json()["status"], r.json()["error_code"], r.json()["fact_ids"]) == ("FAILED", "ADAPTER_UNAVAILABLE", [])
    service.configure(engine=engine_with(FakeTesseract(tsv([("letter_issue_date:", 90), ("31/12/2025", 80)]))))
    r = client.post(f"/api/document-versions/{version_id}/extract", headers=COMMITTEE)
    assert r.json()["status"] == "SUCCEEDED" and r.json()["attempt_number"] == 2 and len(r.json()["fact_ids"]) == 1
    facts = client.get(f"/api/document-versions/{version_id}/facts", headers=BUREAU).json()["facts"]
    assert [(f["field_key"], f["normalized_value"], f["confidence"], f["status"]) for f in facts] == [
        ("letter_issue_date", "2025-12-31", 0.8, "proposed")]
