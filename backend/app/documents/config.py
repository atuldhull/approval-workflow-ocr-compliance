"""Document prototype limits. Format-aware limits are mandatory before enabling uploads."""

from __future__ import annotations

import os
from dataclasses import dataclass

from app.documents.validation import DEFAULT_MAX_UPLOAD_BYTES


class DocumentConfigurationError(RuntimeError):
    """An upload cannot be safely enabled with the current configuration."""


def _positive_int(env_name: str, default: int | None = None) -> int:
    raw = os.environ.get(env_name)
    if raw is None and default is not None:
        return default
    try:
        value = int(raw) if raw is not None else 0
    except ValueError as exc:
        raise DocumentConfigurationError(f"{env_name} must be a positive integer") from exc
    if value <= 0:
        raise DocumentConfigurationError(f"{env_name} must be a positive integer")
    return value


@dataclass(frozen=True)
class DocumentLimits:
    max_upload_bytes: int
    max_pdf_pages: int
    max_image_pixels: int

    def __post_init__(self) -> None:
        if not 0 < self.max_upload_bytes <= DEFAULT_MAX_UPLOAD_BYTES:
            raise DocumentConfigurationError(
                f"DOCUMENT_MAX_UPLOAD_BYTES must be between 1 and {DEFAULT_MAX_UPLOAD_BYTES}"
            )
        if self.max_pdf_pages <= 0:
            raise DocumentConfigurationError("DOCUMENT_MAX_PDF_PAGES must be a positive integer")
        if self.max_image_pixels <= 0:
            raise DocumentConfigurationError("DOCUMENT_MAX_IMAGE_PIXELS must be a positive integer")

    @classmethod
    def from_environment(cls) -> DocumentLimits:
        """Read upload/resource limits; page and pixel limits have no approved defaults."""
        max_upload = _positive_int("DOCUMENT_MAX_UPLOAD_BYTES", DEFAULT_MAX_UPLOAD_BYTES)
        if max_upload > DEFAULT_MAX_UPLOAD_BYTES:
            raise DocumentConfigurationError(
                f"DOCUMENT_MAX_UPLOAD_BYTES cannot exceed {DEFAULT_MAX_UPLOAD_BYTES} bytes"
            )
        return cls(
            max_upload_bytes=max_upload,
            max_pdf_pages=_positive_int("DOCUMENT_MAX_PDF_PAGES"),
            max_image_pixels=_positive_int("DOCUMENT_MAX_IMAGE_PIXELS"),
        )
