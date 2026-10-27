"""Bounded upload validation primitives for approved document formats.

Signature detection is an initial allowlist filter only. PDF/image parsers are
then used to reject malformed structures and enforce resource limits. Neither
step detects malware or establishes that content is safe to expose.
"""

from __future__ import annotations

import hashlib
import unicodedata
import warnings
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import BinaryIO

DEFAULT_MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_READ_CHUNK_BYTES = 64 * 1024
_IMAGE_VALIDATION_LOCK = RLock()


class UploadValidationError(ValueError):
    """An upload is empty, too large, malformed, or unsupported."""


class UploadTooLarge(UploadValidationError):
    """The stream exceeded its configured byte limit."""


@dataclass(frozen=True)
class StreamedUpload:
    media_type: str
    size_bytes: int
    sha256: str


_SIGNATURES = (
    (b"%PDF-", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
)


def detect_media_type(prefix: bytes) -> str:
    """Identify an approved container from bytes, never filename or client MIME."""
    for signature, media_type in _SIGNATURES:
        if prefix.startswith(signature):
            return media_type
    raise UploadValidationError("unsupported document format")


def safe_display_filename(filename: str | None, *, max_length: int = 255) -> str:
    """Return display-only basename metadata; never use it in a storage key."""
    if max_length <= 0:
        raise ValueError("max_length must be positive")
    if not isinstance(filename, str):
        return "upload"
    basename = filename.replace("\\", "/").split("/")[-1].strip().rstrip(" .")
    safe = "".join(char for char in basename if not unicodedata.category(char).startswith("C"))
    safe = safe.strip().rstrip(" .")
    if safe in {"", ".", ".."}:
        return "upload"
    return safe[:max_length]


def _write_all(destination: BinaryIO, chunk: bytes) -> None:
    view = memoryview(chunk)
    offset = 0
    while offset < len(view):
        written = destination.write(view[offset:])
        if not isinstance(written, int) or written <= 0:
            raise OSError("upload destination did not accept all bytes")
        offset += written


def copy_and_hash(
    source: BinaryIO,
    destination: BinaryIO,
    *,
    max_bytes: int,
    chunk_size: int = MAX_READ_CHUNK_BYTES,
) -> StreamedUpload:
    """Copy, bound, and hash exactly the bytes accepted by the destination.

    A broken source that returns more than the requested chunk is rejected
    before any bytes from that chunk are written. Arbitrary larger per-call
    limits are disallowed; configuration can lower the approved 10 MiB cap.
    """
    if not 0 < max_bytes <= DEFAULT_MAX_UPLOAD_BYTES:
        raise ValueError(f"max_bytes must be between 1 and {DEFAULT_MAX_UPLOAD_BYTES}")
    if not 0 < chunk_size <= MAX_READ_CHUNK_BYTES:
        raise ValueError(f"chunk_size must be between 1 and {MAX_READ_CHUNK_BYTES}")

    digest = hashlib.sha256()
    prefix = bytearray()
    size = 0

    while True:
        chunk = source.read(chunk_size)
        if chunk is None:
            raise UploadValidationError("upload stream must yield bytes, not None")
        if not isinstance(chunk, bytes):
            raise UploadValidationError("upload stream must yield bytes")
        if chunk == b"":
            break
        if len(chunk) > chunk_size:
            raise UploadValidationError("upload stream returned an oversized chunk")
        if size + len(chunk) > max_bytes:
            raise UploadTooLarge("document exceeds the configured size limit")
        if len(prefix) < 16:
            prefix.extend(chunk[: 16 - len(prefix)])
        if len(prefix) >= 8:
            # Every approved signature is fully distinguishable by byte 8;
            # reject unsupported containers before copying their full stream.
            detect_media_type(bytes(prefix))
        _write_all(destination, chunk)
        digest.update(chunk)
        size += len(chunk)

    if size == 0:
        raise UploadValidationError("empty documents are not accepted")

    media_type = detect_media_type(bytes(prefix))
    return StreamedUpload(media_type=media_type, size_bytes=size, sha256=digest.hexdigest())


def validate_document_structure(
    path: str | Path,
    *,
    media_type: str,
    max_pdf_pages: int,
    max_image_pixels: int,
) -> None:
    """Parse and enforce limits for an already signature-filtered private file."""
    if max_pdf_pages <= 0 or max_image_pixels <= 0:
        raise ValueError("PDF page and image pixel limits must be positive")

    if media_type == "application/pdf":
        _validate_pdf(Path(path), max_pdf_pages=max_pdf_pages)
    elif media_type in {"image/png", "image/jpeg"}:
        _validate_image(
            Path(path), media_type=media_type, max_image_pixels=max_image_pixels
        )
    else:
        raise UploadValidationError("unsupported document format")


def _validate_pdf(path: Path, *, max_pdf_pages: int) -> None:
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path), strict=True)
        if reader.is_encrypted:
            raise UploadValidationError("encrypted PDFs are not accepted")
        page_count = len(reader.pages)
        if page_count == 0:
            raise UploadValidationError("PDF must contain at least one page")
        if page_count > max_pdf_pages:
            raise UploadValidationError("PDF exceeds the configured page limit")
    except UploadValidationError:
        raise
    except Exception as exc:
        raise UploadValidationError("malformed or truncated PDF document") from exc


def _validate_image(path: Path, *, media_type: str, max_image_pixels: int) -> None:
    try:
        from PIL import Image, ImageFile
    except Exception as exc:
        raise UploadValidationError("image validation is unavailable") from exc

    if ImageFile.LOAD_TRUNCATED_IMAGES:
        raise UploadValidationError("truncated image decoding is enabled in this process")

    expected_format = {"image/png": "PNG", "image/jpeg": "JPEG"}[media_type]
    try:
        # Pillow's bomb threshold is process-global. Serialize this bounded
        # section and restore the prior value after this configured check.
        with _IMAGE_VALIDATION_LOCK:
            previous_pixel_limit = Image.MAX_IMAGE_PIXELS
            Image.MAX_IMAGE_PIXELS = max_image_pixels
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("error", Image.DecompressionBombWarning)
                    with Image.open(path, formats=("PNG", "JPEG")) as image:
                        if image.format != expected_format:
                            raise UploadValidationError("image bytes do not match the detected format")
                        width, height = image.size
                        if width <= 0 or height <= 0:
                            raise UploadValidationError("image dimensions are invalid")
                        if width * height > max_image_pixels:
                            raise UploadValidationError("image exceeds the configured pixel limit")
                        image.verify()

                    # verify() checks container integrity without decoding.
                    # Reopen and decode only after the configured pixel limit.
                    with Image.open(path, formats=("PNG", "JPEG")) as image:
                        if image.format != expected_format or image.size[0] * image.size[1] > max_image_pixels:
                            raise UploadValidationError("image structure changed during validation")
                        image.load()
            finally:
                Image.MAX_IMAGE_PIXELS = previous_pixel_limit
    except UploadValidationError:
        raise
    except (Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        raise UploadValidationError("image exceeds the configured pixel limit") from exc
    except Exception as exc:
        raise UploadValidationError("malformed, truncated, or corrupt image") from exc
