"""Fakes for tests that drive the document endpoints: a scanner, a text engine and synthetic PDFs."""
import io
from decimal import Decimal

from pypdf import PdfWriter

from app.documents import service as documents
from app.documents.config import DocumentLimits
from app.documents.extraction import PageText
from app.documents.ocr import OcrToken, Script
from app.documents.scanning import ScannerUnavailable, ScanResult, ScanVerdict
from app.documents.storage import LocalQuarantineStorage

PAGE = "lease_end_date: 2030-03-31\nletter_issue_date: 2025-03-12\nletter_file_number: F.No.42/2025"


class CleanScanner:
    scanner_key = "clamav"

    def __init__(self):
        self.down = False

    def scan(self, source):
        if self.down:
            raise ScannerUnavailable("scanner offline")
        return ScanResult(ScanVerdict.CLEAN)


class PageEngine:
    """Reads every file as PAGE: one candidate each for the three catalogued fields."""
    adapter_key = "test.matrix"
    model_version = "matrix-1"

    def read(self, content, *, media_type):
        tokens, offset = [], 0
        for word in PAGE.replace("\n", " ").split(" "):
            start = PAGE.index(word, offset)
            tokens.append(OcrToken(word, 1, start, start + len(word), Decimal("0.9"), Script.LATIN))
            offset = start + len(word)
        return [PageText(1, PAGE, tuple(tokens))]


def pdf(marker: str) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.add_metadata({"/Title": marker})
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def configure_documents(tmp_path, scanner=None):
    """Points the documents module at a temp store and the fakes; returns the function that undoes it."""
    documents.configure(storage=LocalQuarantineStorage(tmp_path / "store", limits=DocumentLimits(
        10 * 1024 * 1024, 20, 4_000_000)), scanner=scanner or CleanScanner(), engine=PageEngine())
    return lambda: documents.configure(storage=None, scanner=None, engine=None)
