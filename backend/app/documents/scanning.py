"""Malware scanning boundary and the ClamAV (clamd INSTREAM) adapter.

The service depends only on MalwareScanner, so tests use a fake. Any failure to
get a definite answer raises ScannerUnavailable: the version then stays
scan_pending, is never served, and can be rescanned later (fail closed).
"""

from __future__ import annotations

import os
import re
import socket
import struct
from dataclasses import dataclass
from enum import StrEnum
from typing import BinaryIO, Protocol, runtime_checkable

from app.documents.validation import MAX_READ_CHUNK_BYTES

DEFAULT_CLAMD_HOST = "127.0.0.1"
DEFAULT_CLAMD_PORT = 3310
DEFAULT_CLAMD_TIMEOUT_SECONDS = 30.0
# Signature names as reported by clamd; anything else is not repeated in events.
SIGNATURE_PATTERN = re.compile(r"^[A-Za-z0-9._:/-]{1,200}$")


class ScanVerdict(StrEnum):
    CLEAN = "CLEAN"
    INFECTED = "INFECTED"


@dataclass(frozen=True)
class ScanResult:
    verdict: ScanVerdict
    signature: str | None = None


class ScannerUnavailable(RuntimeError):
    """The scanner could not give a definite CLEAN or INFECTED answer."""


@runtime_checkable
class MalwareScanner(Protocol):
    scanner_key: str  # recorded in doc.document_scanned; the v1 schema allows "clamav" and "demo_seed"

    def scan(self, source: BinaryIO) -> ScanResult: ...


class ClamdScanner:
    """Streams bytes to clamd over TCP with the INSTREAM command."""

    scanner_key = "clamav"

    def __init__(self, host: str = DEFAULT_CLAMD_HOST, port: int = DEFAULT_CLAMD_PORT,
                 timeout: float = DEFAULT_CLAMD_TIMEOUT_SECONDS):
        if not host or not 0 < port < 65536 or timeout <= 0:
            raise ValueError("clamd host, port and timeout must be valid")
        self.host = host
        self.port = port
        self.timeout = timeout

    @classmethod
    def from_environment(cls) -> ClamdScanner:
        try:
            port = int(os.environ.get("CLAMAV_PORT", str(DEFAULT_CLAMD_PORT)))
            timeout = float(os.environ.get("CLAMAV_TIMEOUT_SECONDS", str(DEFAULT_CLAMD_TIMEOUT_SECONDS)))
        except ValueError as exc:
            raise ValueError("CLAMAV_PORT and CLAMAV_TIMEOUT_SECONDS must be numbers") from exc
        return cls(os.environ.get("CLAMAV_HOST", DEFAULT_CLAMD_HOST), port, timeout)

    def scan(self, source: BinaryIO) -> ScanResult:
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as conn:
                conn.sendall(b"zINSTREAM\0")
                for chunk in iter(lambda: source.read(MAX_READ_CHUNK_BYTES), b""):
                    conn.sendall(struct.pack("!L", len(chunk)) + chunk)
                conn.sendall(struct.pack("!L", 0))
                reply = self._read_reply(conn)
        except OSError as exc:
            raise ScannerUnavailable("malware scanner is unreachable") from exc
        return self.parse_reply(reply)

    @staticmethod
    def _read_reply(conn: socket.socket) -> bytes:
        reply = bytearray()
        while not reply.endswith(b"\0"):
            chunk = conn.recv(4096)
            if not chunk:
                break
            reply.extend(chunk)
            if len(reply) > 4096:
                raise ScannerUnavailable("malware scanner reply is too long")
        return bytes(reply)

    @staticmethod
    def parse_reply(reply: bytes) -> ScanResult:
        """`stream: OK` is clean, `stream: <name> FOUND` is infected; anything else is no answer."""
        text = reply.rstrip(b"\0").decode("utf-8", "replace").strip()
        _, _, status = text.partition(": ")
        if status == "OK":
            return ScanResult(ScanVerdict.CLEAN)
        if status.endswith(" FOUND"):
            name = status[: -len(" FOUND")].strip()[:200]
            return ScanResult(ScanVerdict.INFECTED, name or "unknown")
        raise ScannerUnavailable("malware scanner did not return a verdict")
