"""Atomic private quarantine storage for document-ingestion primitives.

This adapter exposes no reader/download API. A transaction owner must call
abort() if the database transaction fails after staging and before commit.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Protocol, runtime_checkable
from uuid import UUID, uuid4

from app.documents.config import DocumentLimits
from app.documents.validation import (
    MAX_READ_CHUNK_BYTES,
    StreamedUpload,
    UploadValidationError,
    copy_and_hash,
    validate_document_structure,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class StorageConfigurationError(RuntimeError):
    """Storage is missing or overlaps the repository or a known served root."""


class StorageError(RuntimeError):
    """A private storage operation failed safely."""


@dataclass(frozen=True)
class StagedObject:
    storage_ref: str
    media_type: str
    size_bytes: int
    sha256: str
    operation_id: UUID


@runtime_checkable
class DocumentStorage(Protocol):
    """Replaceable private object-storage boundary for document services."""

    def stage(
        self,
        source: BinaryIO,
        *,
        institution_id: UUID,
        application_id: UUID,
    ) -> StagedObject: ...

    def abort(self, staged: StagedObject) -> None: ...

    def reconcile_abandoned_staging(self) -> int: ...


def _is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction and is_junction())


def _overlaps(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _acquire_file_lock(path: Path, *, blocking: bool) -> BinaryIO | None:
    """Acquire an OS-backed lease; return None when a nonblocking lock is busy."""
    handle = path.open("r+b")
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt

            mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
            msvcrt.locking(handle.fileno(), mode, 1)
        else:
            import fcntl

            flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
            fcntl.flock(handle.fileno(), flags)
        return handle
    except (OSError, BlockingIOError):
        handle.close()
        if blocking:
            raise
        return None


def _release_file_lock(handle: BinaryIO) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    handle.close()


class LocalQuarantineStorage:
    """Store validated uploads under an explicitly configured private directory."""

    def __init__(
        self,
        root: str | Path,
        *,
        limits: DocumentLimits,
        served_roots: tuple[str | Path, ...] = (),
    ):
        requested = Path(root).expanduser()
        if not requested.is_absolute():
            raise StorageConfigurationError("DOCUMENT_STORAGE_DIR must be an absolute path")
        if _is_link_or_junction(requested):
            raise StorageConfigurationError("DOCUMENT_STORAGE_DIR may not be a symbolic link or junction")

        resolved = requested.resolve(strict=False)
        forbidden_roots = [REPO_ROOT.resolve()]
        for value in served_roots:
            served = Path(value).expanduser()
            if not served.is_absolute():
                raise StorageConfigurationError("DOCUMENT_SERVED_ROOTS entries must be absolute paths")
            forbidden_roots.append(served.resolve(strict=False))
        if any(_overlaps(resolved, forbidden) for forbidden in forbidden_roots):
            raise StorageConfigurationError(
                "DOCUMENT_STORAGE_DIR must not contain or be inside the repository or served/static roots"
            )

        self.limits = limits
        try:
            resolved.mkdir(parents=True, exist_ok=True, mode=0o700)
            if _is_link_or_junction(resolved) or not resolved.is_dir():
                raise StorageConfigurationError("DOCUMENT_STORAGE_DIR must be a real directory")
            self.root = resolved
            self.staging = self.root / ".staging"
            self.staging.mkdir(mode=0o700, exist_ok=True)
            if _is_link_or_junction(self.staging) or not self.staging.is_dir():
                raise StorageConfigurationError("staging directory must be a real directory")
            if os.name != "nt":
                os.chmod(self.root, 0o700)
                os.chmod(self.staging, 0o700)
        except StorageConfigurationError:
            raise
        except OSError as exc:
            raise StorageConfigurationError("private storage directory is unavailable") from exc

    @classmethod
    def from_environment(cls) -> LocalQuarantineStorage:
        value = os.environ.get("DOCUMENT_STORAGE_DIR")
        if not value:
            raise StorageConfigurationError("DOCUMENT_STORAGE_DIR is required; storage is disabled")
        raw_roots = os.environ.get("DOCUMENT_SERVED_ROOTS", "")
        served_roots = tuple(item.strip() for item in raw_roots.split(os.pathsep) if item.strip())
        limits = DocumentLimits.from_environment()
        return cls(value, limits=limits, served_roots=served_roots)

    @staticmethod
    def _key(
        institution_id: UUID, application_id: UUID, sha256: str, operation_id: UUID
    ) -> str:
        if not _SHA256.fullmatch(sha256):
            raise StorageError("invalid content digest")
        return PurePosixPath(
            "quarantine",
            str(institution_id),
            str(application_id),
            "sha256",
            sha256,
            str(operation_id),
        ).as_posix()

    def _path(self, storage_ref: str) -> Path:
        self._assert_root_safe()
        key = PurePosixPath(storage_ref)
        if key.is_absolute() or not key.parts or any(part in {"", ".", ".."} for part in key.parts):
            raise StorageError("invalid private storage reference")
        if len(key.parts) != 6 or key.parts[0] != "quarantine" or key.parts[3] != "sha256":
            raise StorageError("invalid private storage reference")
        try:
            UUID(key.parts[1])
            UUID(key.parts[2])
            UUID(key.parts[5])
        except ValueError as exc:
            raise StorageError("invalid private storage reference") from exc
        if not _SHA256.fullmatch(key.parts[4]):
            raise StorageError("invalid private storage reference")

        target = self.root.joinpath(*key.parts)
        resolved = target.resolve(strict=False)
        if self.root not in resolved.parents:
            raise StorageError("storage reference escaped private root")
        current = self.root
        for part in key.parts:
            current = current / part
            if _is_link_or_junction(current):
                raise StorageError("symbolic links are not allowed in private storage")
        return target

    def _assert_root_safe(self) -> None:
        if _is_link_or_junction(self.root) or not self.root.is_dir():
            raise StorageError("private storage root is unavailable")
        if _is_link_or_junction(self.staging) or not self.staging.is_dir():
            raise StorageError("private staging directory is unavailable")
        if self.staging.resolve(strict=False).parent != self.root:
            raise StorageError("private staging directory escaped storage root")

    def _mkdir_private(self, directory: Path) -> None:
        relative = directory.relative_to(self.root)
        current = self.root
        for part in relative.parts:
            current = current / part
            current.mkdir(mode=0o700, exist_ok=True)
            if _is_link_or_junction(current) or not current.is_dir():
                raise StorageError("private storage path contains a non-directory or link")
            if os.name != "nt":
                os.chmod(current, 0o700)

    @staticmethod
    def _atomic_publish(source: Path, destination: Path) -> None:
        """Atomically publish a complete file without replacing an existing key."""
        if os.name == "nt":
            # Windows rename fails when the target exists; source and target are
            # under the same configured root and therefore on the same volume.
            os.rename(source, destination)
        else:
            # POSIX hard-link creation is atomic and fails if destination exists.
            # The staged source is removed by operation cleanup after publication.
            os.link(source, destination)

    @staticmethod
    def _sync_directory(directory: Path) -> None:
        if os.name == "nt":
            return
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _verify_file(path: Path, metadata: StreamedUpload) -> None:
        import hashlib

        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(MAX_READ_CHUNK_BYTES), b""):
                digest.update(chunk)
                size += len(chunk)
        if size != metadata.size_bytes or digest.hexdigest() != metadata.sha256:
            raise StorageError("stored quarantine object failed byte-count or digest verification")

    @staticmethod
    def _cleanup_operation(
        operation_dir: Path,
        part_path: Path,
        lock_path: Path,
        lock_handle: BinaryIO | None,
    ) -> list[OSError]:
        errors: list[OSError] = []
        try:
            part_path.unlink(missing_ok=True)
        except OSError as exc:
            errors.append(exc)
        if lock_handle is not None:
            try:
                _release_file_lock(lock_handle)
            except OSError as exc:
                errors.append(exc)
        try:
            lock_path.unlink(missing_ok=True)
            operation_dir.rmdir()
        except OSError as exc:
            errors.append(exc)
        return errors

    @staticmethod
    def _add_cleanup_notes(error: BaseException, cleanup_errors: list[OSError]) -> None:
        for cleanup_error in cleanup_errors:
            add_note = getattr(error, "add_note", None)
            if add_note:
                add_note(f"staging cleanup also failed: {cleanup_error!r}")

    def stage(
        self,
        source: BinaryIO,
        *,
        institution_id: UUID,
        application_id: UUID,
    ) -> StagedObject:
        """Validate then atomically publish a unique quarantine object.

        The returned operation ID scopes compensation to this stage attempt.
        Call abort() if the owning database transaction fails before commit.
        """
        self._assert_root_safe()
        operation_id = uuid4()
        operation_dir = self.staging / str(operation_id)
        operation_dir.mkdir(mode=0o700)
        lock_path = operation_dir / "owner.lock"
        part_path = operation_dir / "upload.part"
        lock_handle: BinaryIO | None = None
        final_path: Path | None = None
        published = False
        try:
            with lock_path.open("xb") as lease:
                lease.write(b"\0")
                lease.flush()
            lock_handle = _acquire_file_lock(lock_path, blocking=True)
            if lock_handle is None:
                raise StorageError("failed to acquire staging lease")

            with part_path.open("xb") as destination:
                metadata = copy_and_hash(
                    source,
                    destination,
                    max_bytes=self.limits.max_upload_bytes,
                    chunk_size=MAX_READ_CHUNK_BYTES,
                )
                destination.flush()
                os.fsync(destination.fileno())

            if os.name != "nt":
                os.chmod(part_path, 0o600)
            validate_document_structure(
                part_path,
                media_type=metadata.media_type,
                max_pdf_pages=self.limits.max_pdf_pages,
                max_image_pixels=self.limits.max_image_pixels,
            )

            storage_ref = self._key(
                institution_id, application_id, metadata.sha256, operation_id
            )
            final_path = self._path(storage_ref)
            self._mkdir_private(final_path.parent)
            self._atomic_publish(part_path, final_path)
            published = True
            self._sync_directory(final_path.parent)
            self._verify_file(final_path, metadata)

            staged = StagedObject(
                storage_ref=storage_ref,
                media_type=metadata.media_type,
                size_bytes=metadata.size_bytes,
                sha256=metadata.sha256,
                operation_id=operation_id,
            )
            cleanup_errors = self._cleanup_operation(
                operation_dir, part_path, lock_path, lock_handle
            )
            lock_handle = None
            if cleanup_errors:
                raise StorageError("staging lease cleanup failed") from cleanup_errors[0]
            return staged
        except BaseException as exc:
            cleanup_errors: list[OSError] = []
            if published and final_path is not None:
                try:
                    final_path.unlink(missing_ok=True)
                    self._sync_directory(final_path.parent)
                except OSError as cleanup_error:
                    cleanup_errors.append(cleanup_error)
            cleanup_errors.extend(
                self._cleanup_operation(operation_dir, part_path, lock_path, lock_handle)
            )
            lock_handle = None
            self._add_cleanup_notes(exc, cleanup_errors)
            if isinstance(exc, (UploadValidationError, ValueError, StorageError)):
                raise
            if isinstance(exc, Exception):
                raise StorageError("private staging operation failed") from exc
            raise

    def abort(self, staged: StagedObject) -> None:
        """Compensate a failed pre-commit database transaction for this unique object."""
        if not isinstance(staged, StagedObject):
            raise StorageError("invalid staged object")
        expected_operation = str(staged.operation_id)
        key = PurePosixPath(staged.storage_ref)
        if not key.parts or key.parts[-1] != expected_operation:
            raise StorageError("staged object operation does not match its storage reference")
        try:
            path = self._path(staged.storage_ref)
            path.unlink(missing_ok=True)
            self._sync_directory(path.parent)
        except OSError as exc:
            raise StorageError("failed to abort staged object") from exc

    def reconcile_abandoned_staging(self) -> int:
        """Delete only abandoned .part files whose OS lease can be acquired.

        Active operations hold their lease before creating upload.part, so they
        cannot be mistaken for abandoned work. Persisted quarantine objects are
        never considered by reconciliation.
        """
        self._assert_root_safe()
        removed = 0
        for operation_dir in self.staging.iterdir():
            if _is_link_or_junction(operation_dir) or not operation_dir.is_dir():
                continue
            part_path = operation_dir / "upload.part"
            lock_path = operation_dir / "owner.lock"
            if _is_link_or_junction(part_path) or _is_link_or_junction(lock_path):
                continue
            if not part_path.is_file() or not lock_path.is_file():
                continue
            try:
                lock_handle = _acquire_file_lock(lock_path, blocking=False)
            except OSError:
                continue
            if lock_handle is None:
                continue
            try:
                part_path.unlink(missing_ok=True)
                removed += 1
                _release_file_lock(lock_handle)
                lock_handle = None
                lock_path.unlink(missing_ok=True)
                operation_dir.rmdir()
            except OSError:
                if lock_handle is not None:
                    try:
                        _release_file_lock(lock_handle)
                    except OSError:
                        pass
        return removed
