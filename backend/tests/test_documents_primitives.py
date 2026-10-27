from __future__ import annotations

import asyncio
import hashlib
import io
import inspect
import os
import threading
from pathlib import Path, PurePosixPath
from uuid import uuid4

import pytest
from pypdf import PdfWriter
from PIL import Image

from app.documents import storage as storage_module
from app.documents.config import DocumentConfigurationError, DocumentLimits
from app.documents.ownership import resolve_document_owner
from app.documents.storage import (
    LocalQuarantineStorage,
    StorageConfigurationError,
    StorageError,
)
from app.documents.validation import (
    DEFAULT_MAX_UPLOAD_BYTES,
    MAX_READ_CHUNK_BYTES,
    UploadTooLarge,
    UploadValidationError,
    copy_and_hash,
    detect_media_type,
    safe_display_filename,
    validate_document_structure,
)


def make_pdf(page_count: int = 1) -> bytes:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=72, height=72)
    result = io.BytesIO()
    writer.write(result)
    return result.getvalue()


def make_image(fmt: str = "PNG", size: tuple[int, int] = (2, 2)) -> bytes:
    result = io.BytesIO()
    Image.new("RGB", size, color="white").save(result, format=fmt)
    return result.getvalue()


PDF = make_pdf()
PNG = make_image("PNG")
JPEG = make_image("JPEG")


def limits(*, max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES, pages: int = 5, pixels: int = 100) -> DocumentLimits:
    return DocumentLimits(max_upload_bytes, pages, pixels)


def make_storage(root: Path, *, approved: DocumentLimits | None = None, served_roots=()):
    return LocalQuarantineStorage(
        root, limits=approved or limits(), served_roots=tuple(served_roots)
    )


def stored_path(storage: LocalQuarantineStorage, storage_ref: str) -> Path:
    return storage.root.joinpath(*PurePosixPath(storage_ref).parts)


@pytest.mark.parametrize(
    ("content", "expected"),
    [(PDF, "application/pdf"), (PNG, "image/png"), (JPEG, "image/jpeg")],
)
def test_detects_approved_signatures_from_bytes(content, expected):
    assert detect_media_type(content) == expected


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("../../private/approval.pdf", "approval.pdf"),
        (r"C:\secret\approval.pdf", "approval.pdf"),
        ("../..", "upload"),
        ("report\u0000.pdf", "report.pdf"),
    ],
)
def test_display_filename_cannot_be_used_for_path_traversal(filename, expected):
    assert safe_display_filename(filename) == expected


def test_unsupported_signature_is_rejected():
    with pytest.raises(UploadValidationError, match="unsupported"):
        detect_media_type(b"GIF89a")


def test_unsupported_container_is_rejected_before_copying_the_full_stream():
    class UnsupportedStream:
        calls = 0

        def read(self, size):
            self.calls += 1
            assert size == 8
            if self.calls == 1:
                return b"GIF89a00"
            raise AssertionError("validator continued reading an unsupported container")

    source = UnsupportedStream()
    destination = io.BytesIO()
    with pytest.raises(UploadValidationError, match="unsupported"):
        copy_and_hash(source, destination, max_bytes=100, chunk_size=8)
    assert source.calls == 1
    assert destination.getvalue() == b""


def test_empty_upload_is_rejected():
    with pytest.raises(UploadValidationError, match="empty"):
        copy_and_hash(io.BytesIO(b""), io.BytesIO(), max_bytes=8)


def test_none_read_is_rejected_instead_of_being_treated_as_eof():
    class NoneAfterPdf:
        def __init__(self):
            self.calls = 0

        def read(self, size):
            self.calls += 1
            return PDF if self.calls == 1 else None

    source = NoneAfterPdf()
    with pytest.raises(UploadValidationError, match="not None"):
        copy_and_hash(source, io.BytesIO(), max_bytes=DEFAULT_MAX_UPLOAD_BYTES)
    assert source.calls == 2


def test_empty_bytes_terminates_a_valid_stream_normally():
    result = copy_and_hash(io.BytesIO(PDF), io.BytesIO(), max_bytes=len(PDF))

    assert result.media_type == "application/pdf"
    assert result.size_bytes == len(PDF)
    assert result.sha256 == hashlib.sha256(PDF).hexdigest()


@pytest.mark.parametrize("unexpected", [bytearray(PDF), memoryview(PDF), "not bytes"])
def test_non_bytes_read_values_are_rejected(unexpected):
    class UnexpectedStream:
        def read(self, size):
            return unexpected

    with pytest.raises(UploadValidationError, match="yield bytes"):
        copy_and_hash(UnexpectedStream(), io.BytesIO(), max_bytes=DEFAULT_MAX_UPLOAD_BYTES)


def test_exact_size_boundary_and_sha256_are_calculated_over_written_bytes():
    class ShortWriter:
        def __init__(self):
            self.data = bytearray()

        def write(self, value):
            accepted = bytes(value[:2])
            self.data.extend(accepted)
            return len(accepted)

    destination = ShortWriter()
    result = copy_and_hash(io.BytesIO(PDF), destination, max_bytes=len(PDF), chunk_size=7)

    assert bytes(destination.data) == PDF
    assert result.media_type == "application/pdf"
    assert result.size_bytes == len(PDF)
    assert result.sha256 == hashlib.sha256(PDF).hexdigest()


def test_streaming_limit_rejects_first_chunk_that_would_exceed_limit():
    destination = io.BytesIO()
    with pytest.raises(UploadTooLarge):
        copy_and_hash(io.BytesIO(PDF), destination, max_bytes=len(PDF) - 1, chunk_size=4)
    assert len(destination.getvalue()) <= len(PDF) - 1


def test_oversized_source_chunk_and_unbounded_read_request_are_rejected():
    class OversizedChunk:
        def read(self, size):
            assert size == 8
            return b"%PDF-123456"

    with pytest.raises(UploadValidationError, match="oversized chunk"):
        copy_and_hash(OversizedChunk(), io.BytesIO(), max_bytes=100, chunk_size=8)
    with pytest.raises(ValueError, match="chunk_size"):
        copy_and_hash(io.BytesIO(PDF), io.BytesIO(), max_bytes=100, chunk_size=MAX_READ_CHUNK_BYTES + 1)
    with pytest.raises(ValueError, match="max_bytes"):
        copy_and_hash(io.BytesIO(PDF), io.BytesIO(), max_bytes=DEFAULT_MAX_UPLOAD_BYTES + 1)


def test_document_limits_reject_unsafe_upload_cap_and_require_parser_limits(monkeypatch):
    with pytest.raises(DocumentConfigurationError, match="DOCUMENT_MAX_UPLOAD_BYTES"):
        limits(max_upload_bytes=DEFAULT_MAX_UPLOAD_BYTES + 1)
    monkeypatch.setenv("DOCUMENT_MAX_UPLOAD_BYTES", str(DEFAULT_MAX_UPLOAD_BYTES + 1))
    monkeypatch.setenv("DOCUMENT_MAX_PDF_PAGES", "5")
    monkeypatch.setenv("DOCUMENT_MAX_IMAGE_PIXELS", "100")
    with pytest.raises(DocumentConfigurationError, match="cannot exceed"):
        DocumentLimits.from_environment()

    monkeypatch.setenv("DOCUMENT_MAX_UPLOAD_BYTES", str(DEFAULT_MAX_UPLOAD_BYTES))
    monkeypatch.delenv("DOCUMENT_MAX_PDF_PAGES", raising=False)
    monkeypatch.delenv("DOCUMENT_MAX_IMAGE_PIXELS", raising=False)
    with pytest.raises(DocumentConfigurationError, match="DOCUMENT_MAX_PDF_PAGES"):
        DocumentLimits.from_environment()


@pytest.mark.parametrize(
    ("data", "media_type"),
    [
        (b"%PDF-1.7\nnot a real PDF", "application/pdf"),
        (PDF[:-30], "application/pdf"),
        (b"\x89PNG\r\n\x1a\ntruncated", "image/png"),
        (PNG[:-10], "image/png"),
    ],
)
def test_structural_parser_rejects_malformed_or_truncated_documents(tmp_path, data, media_type):
    path = tmp_path / "candidate.bin"
    path.write_bytes(data)
    with pytest.raises(UploadValidationError):
        validate_document_structure(path, media_type=media_type, max_pdf_pages=5, max_image_pixels=100)


def test_pdf_page_limit_is_enforced(tmp_path):
    path = tmp_path / "many-pages.pdf"
    path.write_bytes(make_pdf(3))
    with pytest.raises(UploadValidationError, match="page limit"):
        validate_document_structure(path, media_type="application/pdf", max_pdf_pages=2, max_image_pixels=100)


def test_image_pixel_limit_is_checked_before_decode(tmp_path, monkeypatch):
    path = tmp_path / "large.png"
    path.write_bytes(make_image(size=(11, 10)))

    def must_not_decode(self):
        raise AssertionError("image decode happened before pixel limit")

    monkeypatch.setattr(Image.Image, "load", must_not_decode)
    with pytest.raises(UploadValidationError, match="pixel limit"):
        validate_document_structure(path, media_type="image/png", max_pdf_pages=5, max_image_pixels=100)


@pytest.mark.parametrize("size", [(11, 10), (16, 16)], ids=("bomb-warning", "bomb-error"))
def test_pillow_bomb_threshold_uses_configured_limit_before_open_and_is_restored(
    tmp_path, monkeypatch, size
):
    path = tmp_path / "bomb.png"
    path.write_bytes(make_image(size=size))

    initial_limit = 1_000_000
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", initial_limit)
    real_open = Image.open
    limits_seen_by_pillow = []

    def inspect_limit_before_open(*args, **kwargs):
        limits_seen_by_pillow.append(Image.MAX_IMAGE_PIXELS)
        return real_open(*args, **kwargs)

    monkeypatch.setattr(Image, "open", inspect_limit_before_open)

    with pytest.raises(UploadValidationError, match="pixel limit"):
        validate_document_structure(path, media_type="image/png", max_pdf_pages=5, max_image_pixels=100)

    assert limits_seen_by_pillow == [100]
    assert Image.MAX_IMAGE_PIXELS == initial_limit


def test_pillow_bomb_threshold_is_active_during_decode_and_then_restored(tmp_path, monkeypatch):
    path = tmp_path / "small.png"
    path.write_bytes(PNG)

    initial_limit = 1_000_000
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", initial_limit)
    real_open = Image.open
    real_load = Image.Image.load
    limits_seen_by_open = []
    limits_seen_by_load = []

    def inspect_limit_before_open(*args, **kwargs):
        limits_seen_by_open.append(Image.MAX_IMAGE_PIXELS)
        return real_open(*args, **kwargs)

    def inspect_limit_during_load(image, *args, **kwargs):
        limits_seen_by_load.append(Image.MAX_IMAGE_PIXELS)
        return real_load(image, *args, **kwargs)

    monkeypatch.setattr(Image, "open", inspect_limit_before_open)
    monkeypatch.setattr(Image.Image, "load", inspect_limit_during_load)

    validate_document_structure(path, media_type="image/png", max_pdf_pages=5, max_image_pixels=100)

    assert limits_seen_by_open == [100, 100]
    assert limits_seen_by_load
    assert set(limits_seen_by_load) == {100}
    assert Image.MAX_IMAGE_PIXELS == initial_limit


@pytest.mark.parametrize(("data", "media_type"), [(PDF, "application/pdf"), (PNG, "image/png"), (JPEG, "image/jpeg")])
def test_valid_structure_is_parsed(data, media_type, tmp_path):
    path = tmp_path / "document.bin"
    path.write_bytes(data)
    validate_document_structure(path, media_type=media_type, max_pdf_pages=5, max_image_pixels=100)


def test_signature_not_filename_or_client_mime_controls_format(tmp_path):
    path = tmp_path / "report.png"
    path.write_bytes(PDF)
    assert detect_media_type(path.read_bytes()[:16]) == "application/pdf"
    validate_document_structure(path, media_type="application/pdf", max_pdf_pages=5, max_image_pixels=100)
    parameters = inspect.signature(LocalQuarantineStorage.stage).parameters
    assert not {"filename", "media_type", "content_type"}.intersection(parameters)


def test_private_storage_requires_explicit_location(monkeypatch):
    monkeypatch.delenv("DOCUMENT_STORAGE_DIR", raising=False)
    with pytest.raises(StorageConfigurationError, match="DOCUMENT_STORAGE_DIR is required"):
        LocalQuarantineStorage.from_environment()


def test_private_storage_root_must_be_outside_repository(tmp_path):
    from app.documents.storage import REPO_ROOT

    with pytest.raises(StorageConfigurationError, match="repository"):
        make_storage(REPO_ROOT / "frontend")


def test_private_storage_must_not_overlap_configured_served_roots(tmp_path):
    served = tmp_path / "served"
    with pytest.raises(StorageConfigurationError, match="served/static"):
        make_storage(served / "private", served_roots=(served,))
    root = tmp_path / "combined"
    with pytest.raises(StorageConfigurationError, match="served/static"):
        make_storage(root, served_roots=(root / "static",))


def test_storage_key_is_scoped_and_each_operation_has_unique_ownership(tmp_path):
    storage = make_storage(tmp_path / "private-store")
    institution_id, application_id = uuid4(), uuid4()
    first = storage.stage(io.BytesIO(PDF), institution_id=institution_id, application_id=application_id)
    retry = storage.stage(io.BytesIO(PDF), institution_id=institution_id, application_id=application_id)
    other_application = storage.stage(
        io.BytesIO(PDF), institution_id=institution_id, application_id=uuid4()
    )

    assert first.sha256 == hashlib.sha256(PDF).hexdigest()
    assert first.storage_ref.endswith(str(first.operation_id))
    assert first.operation_id != retry.operation_id
    assert retry.storage_ref != first.storage_ref
    assert first.storage_ref != other_application.storage_ref
    assert "filename" not in first.storage_ref
    assert stored_path(storage, first.storage_ref).read_bytes() == PDF
    with storage.open_private(first.storage_ref) as stored:  # in-process reader for scanner and text engine
        assert stored.read() == PDF
    assert storage.reconcile_abandoned_staging() == 0
    assert stored_path(storage, first.storage_ref).read_bytes() == PDF


def test_abort_only_removes_the_unique_staged_object(tmp_path):
    storage = make_storage(tmp_path / "private-store")
    institution_id, application_id = uuid4(), uuid4()
    first = storage.stage(io.BytesIO(PDF), institution_id=institution_id, application_id=application_id)
    second = storage.stage(io.BytesIO(PDF), institution_id=institution_id, application_id=application_id)

    storage.abort(first)
    assert not stored_path(storage, first.storage_ref).exists()
    assert stored_path(storage, second.storage_ref).read_bytes() == PDF


def test_stage_does_not_accept_arbitrary_per_call_size_limit(tmp_path):
    storage = make_storage(tmp_path / "private-store")
    with pytest.raises(TypeError):
        storage.stage(io.BytesIO(PDF), institution_id=uuid4(), application_id=uuid4(), max_bytes=DEFAULT_MAX_UPLOAD_BYTES * 10)


def test_stream_failure_removes_partial_staging_file(tmp_path):
    class BrokenStream:
        def __init__(self):
            self.calls = 0

        def read(self, size):
            self.calls += 1
            if self.calls == 1:
                return PDF[:5]
            raise OSError("synthetic stream failure")

    storage = make_storage(tmp_path / "private-store")
    with pytest.raises(StorageError, match="staging operation failed"):
        storage.stage(BrokenStream(), institution_id=uuid4(), application_id=uuid4())
    assert list(storage.staging.rglob("upload.part")) == []


def test_cancellation_cleans_partial_file_and_preserves_cancellation(tmp_path):
    class CancelledStream:
        def __init__(self):
            self.calls = 0

        def read(self, size):
            self.calls += 1
            if self.calls == 1:
                return PDF[:8]
            raise asyncio.CancelledError()

    storage = make_storage(tmp_path / "private-store")
    with pytest.raises(asyncio.CancelledError):
        storage.stage(CancelledStream(), institution_id=uuid4(), application_id=uuid4())
    assert list(storage.staging.rglob("upload.part")) == []


@pytest.mark.parametrize("failure_point", ["publish", "sync", "directory_sync", "post_publish_cancel"])
def test_failed_publish_or_sync_leaves_no_partial_or_final_object(tmp_path, monkeypatch, failure_point):
    storage = make_storage(tmp_path / "private-store")
    if failure_point == "publish":
        monkeypatch.setattr(
            storage,
            "_atomic_publish",
            lambda source, destination: (_ for _ in ()).throw(OSError("publish failed")),
        )
    elif failure_point == "sync":
        monkeypatch.setattr(
            "app.documents.storage.os.fsync",
            lambda fd: (_ for _ in ()).throw(OSError("fsync failed")),
        )
    elif failure_point == "directory_sync":
        monkeypatch.setattr(
            storage,
            "_sync_directory",
            lambda directory: (_ for _ in ()).throw(OSError("directory fsync failed")),
        )
    else:
        monkeypatch.setattr(
            storage,
            "_verify_file",
            lambda path, metadata: (_ for _ in ()).throw(asyncio.CancelledError()),
        )

    expected = asyncio.CancelledError if failure_point == "post_publish_cancel" else StorageError
    with pytest.raises(expected):
        storage.stage(io.BytesIO(PDF), institution_id=uuid4(), application_id=uuid4())
    assert list(storage.staging.rglob("upload.part")) == []
    quarantine = storage.root / "quarantine"
    assert not quarantine.exists() or not any(path.is_file() for path in quarantine.rglob("*"))


def test_final_object_is_invisible_until_complete_and_reconciler_skips_active_stage(tmp_path):
    entered_read = threading.Event()
    continue_read = threading.Event()
    result: list[object] = []
    errors: list[BaseException] = []

    class BlockingStream:
        def __init__(self):
            self.calls = 0

        def read(self, size):
            self.calls += 1
            if self.calls == 1:
                return PDF[:5]
            if self.calls == 2:
                entered_read.set()
                assert continue_read.wait(timeout=5)
                return PDF[5:]
            return b""

    storage = make_storage(tmp_path / "private-store")

    def stage():
        try:
            result.append(storage.stage(BlockingStream(), institution_id=uuid4(), application_id=uuid4()))
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=stage)
    thread.start()
    assert entered_read.wait(timeout=5)
    assert not (storage.root / "quarantine").exists()
    active_part = list(storage.staging.rglob("upload.part"))
    assert len(active_part) == 1
    assert storage.reconcile_abandoned_staging() == 0
    assert active_part[0].exists()

    continue_read.set()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert not errors
    staged = result[0]
    assert stored_path(storage, staged.storage_ref).read_bytes() == PDF
    assert list(storage.staging.rglob("upload.part")) == []


def test_reconciler_waits_for_stage_initialization_and_skips_active_upload(tmp_path, monkeypatch):
    initialization_paused = threading.Event()
    allow_operation_lease = threading.Event()
    read_paused = threading.Event()
    allow_read_to_finish = threading.Event()
    reconcile_waiting = threading.Event()
    reconcile_finished = threading.Event()
    stage_result: list[object] = []
    stage_errors: list[BaseException] = []
    reconcile_result: list[int] = []

    class BlockingStream:
        def __init__(self):
            self.calls = 0

        def read(self, size):
            self.calls += 1
            if self.calls == 1:
                return PDF[:5]
            if self.calls == 2:
                read_paused.set()
                assert allow_read_to_finish.wait(timeout=5)
                return PDF[5:]
            return b""

    storage = make_storage(tmp_path / "private-store")
    real_acquire = storage_module._acquire_file_lock

    def controlled_acquire(path, *, blocking):
        path = Path(path)
        thread_name = threading.current_thread().name
        if path.name == "owner.lock" and thread_name == "stage-initializer":
            initialization_paused.set()
            assert allow_operation_lease.wait(timeout=5)
        if path == storage.coordination_lock and thread_name == "reconciler":
            reconcile_waiting.set()
        return real_acquire(path, blocking=blocking)

    monkeypatch.setattr(storage_module, "_acquire_file_lock", controlled_acquire)

    def stage():
        try:
            stage_result.append(
                storage.stage(BlockingStream(), institution_id=uuid4(), application_id=uuid4())
            )
        except BaseException as exc:
            stage_errors.append(exc)

    def reconcile():
        try:
            reconcile_result.append(storage.reconcile_abandoned_staging())
        finally:
            reconcile_finished.set()

    stage_thread = threading.Thread(target=stage, name="stage-initializer")
    reconcile_thread = threading.Thread(target=reconcile, name="reconciler")
    stage_thread.start()
    try:
        assert initialization_paused.wait(timeout=5)
        operation_dirs = [entry for entry in storage.staging.iterdir() if entry.is_dir()]
        assert len(operation_dirs) == 1
        operation_dir = operation_dirs[0]
        assert (operation_dir / "owner.lock").is_file()
        assert not (operation_dir / "upload.part").exists()

        reconcile_thread.start()
        assert reconcile_waiting.wait(timeout=5)
        # Reconciliation has attempted the shared lock but cannot enter the
        # pre-lease state while stage initialization owns that lock.
        assert operation_dir.exists()
        assert not reconcile_finished.is_set()

        allow_operation_lease.set()
        assert read_paused.wait(timeout=5)
        assert reconcile_finished.wait(timeout=5)
        assert reconcile_result == [0]
        assert (operation_dir / "upload.part").exists()

        allow_read_to_finish.set()
        stage_thread.join(timeout=5)
        reconcile_thread.join(timeout=5)
        assert not stage_thread.is_alive()
        assert not reconcile_thread.is_alive()
        assert not stage_errors
        staged = stage_result[0]
        assert stored_path(storage, staged.storage_ref).read_bytes() == PDF
        assert not operation_dir.exists()
        assert storage.coordination_lock.is_file()
    finally:
        allow_operation_lease.set()
        allow_read_to_finish.set()
        stage_thread.join(timeout=5)
        if reconcile_thread.ident is not None:
            reconcile_thread.join(timeout=5)


@pytest.mark.parametrize(
    "artifacts",
    [(), ("owner.lock",), ("owner.lock", "upload.part")],
    ids=("empty-directory", "lock-only", "abandoned-partial-upload"),
)
def test_reconciler_removes_abandoned_staging_states(tmp_path, artifacts):
    storage = make_storage(tmp_path / "private-store")
    operation_dir = storage.staging / str(uuid4())
    operation_dir.mkdir()
    if "owner.lock" in artifacts:
        (operation_dir / "owner.lock").write_bytes(b"\0")
    if "upload.part" in artifacts:
        (operation_dir / "upload.part").write_bytes(b"partial")
    coordination_lock_contents = storage.coordination_lock.read_bytes()

    assert storage.reconcile_abandoned_staging() == 1
    assert not operation_dir.exists()
    assert storage.coordination_lock.read_bytes() == coordination_lock_contents


def test_reconciler_leaves_published_quarantine_objects_untouched(tmp_path):
    storage = make_storage(tmp_path / "private-store")
    staged = storage.stage(io.BytesIO(PDF), institution_id=uuid4(), application_id=uuid4())
    published_path = stored_path(storage, staged.storage_ref)
    operation_dir = storage.staging / str(uuid4())
    operation_dir.mkdir()
    (operation_dir / "owner.lock").write_bytes(b"\0")
    (operation_dir / "upload.part").write_bytes(b"partial")

    assert storage.reconcile_abandoned_staging() == 1
    assert not operation_dir.exists()
    assert published_path.read_bytes() == PDF


def test_case_owner_is_resolved_from_case_port_without_client_institution(monkeypatch):
    from app.documents import ownership
    from contracts.types import CaseRef

    session, application_id = object(), uuid4()
    expected = CaseRef(application_id, uuid4(), "NORTH")
    calls = []

    class FakeCasePort:
        def lookup(self, received_session, received_application_id):
            calls.append((received_session, received_application_id))
            return expected

    monkeypatch.setattr(ownership, "port", lambda port_type: FakeCasePort())
    assert resolve_document_owner(session, application_id) == expected
    assert calls == [(session, application_id)]


def test_case_owner_fails_closed_on_mismatched_caseport_result(monkeypatch):
    from app.documents import ownership
    from contracts.types import CaseRef

    application_id = uuid4()
    monkeypatch.setattr(
        ownership, "port", lambda port_type: type("Fake", (), {
            "lookup": lambda self, session, received_id: CaseRef(uuid4(), uuid4(), "NORTH")
        })(),
    )
    with pytest.raises(RuntimeError, match="different application"):
        resolve_document_owner(object(), application_id)


def test_no_document_download_route_is_exposed_yet():
    from app.main import create_app

    reads = {route.path for route in create_app().routes
             if "/document" in route.path and "GET" in getattr(route, "methods", set())}
    # listings and facts only; nothing returns stored file bytes
    assert reads == {"/api/applications/{application_id}/documents", "/api/documents",
                     "/api/document-versions/{version_id}/facts"}
