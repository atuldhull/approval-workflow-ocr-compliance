"""Signed checkpoints of the ledger, and verification against them.

The hash chain (ledger.py) shows that no event changed after the entry that follows it. It cannot show that the
whole chain was not rebuilt, or that the newest entries were not cut off. A checkpoint fixes that: it records the
ledger head (seq, entry hash, entry count) at a moment in time, signed with an Ed25519 key, and a copy is handed
to a witness outside the database. Verification trusts only the witness copy and public keys from configuration -
never the database's own checkpoint rows.

A checkpoint is evidence of integrity for this system. It is not a legal or digital signature on any decision.

    python -m app.platform.audit checkpoint     # sign the current head and hand it to the witness
    python -m app.platform.audit verify         # chain + latest trusted checkpoint
"""
import base64
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.platform.errors import ServiceUnavailable
from app.platform.ledger import Ledger, canonical
from app.platform.models import Checkpoint, DomainEvent, LedgerEntry
from app.platform.registry import port
from app.platform.settings import settings
from contracts.ports import ClockPort

STATEMENT_VERSION = 1


# ---- keys ----

class Signer:
    def __init__(self, key_id: str, private_key: Ed25519PrivateKey):
        self.key_id, self.private_key = key_id, private_key

    @classmethod
    def from_pem_file(cls, key_id: str, path: str) -> "Signer":
        key = serialization.load_pem_private_key(Path(path).read_bytes(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("audit signing key must be Ed25519")
        return cls(key_id, key)

    def sign(self, data: bytes) -> str:
        return base64.b64encode(self.private_key.sign(data)).decode()


def public_key_b64(key: Ed25519PublicKey) -> str:
    return base64.b64encode(key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()


def load_trusted_keys(path: str) -> dict[str, Ed25519PublicKey]:
    """{key_id: base64 raw public key}. Old keys stay listed after rotation so old checkpoints still verify."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return {kid: Ed25519PublicKey.from_public_bytes(base64.b64decode(b64)) for kid, b64 in raw.items()}


# ---- witness: the independent copy ----

class Witness(Protocol):
    def publish(self, checkpoint: dict) -> None: ...
    def latest(self) -> dict | None: ...


class LocalFileWitness:
    """Append-only JSON lines in a directory outside the database (demo witness).

    In a real deployment this would be storage the database administrators cannot rewrite: a write-once bucket,
    another organisation's service, or a printed and countersigned digest.
    """

    def __init__(self, directory: str):
        self.path = Path(directory) / "checkpoints.jsonl"

    def publish(self, checkpoint: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(checkpoint, sort_keys=True) + "\n")

    def latest(self) -> dict | None:
        if not self.path.exists():
            return None
        lines = [ln for ln in self.path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        return json.loads(lines[-1]) if lines else None


class MemoryWitness:
    def __init__(self):
        self.items: list[dict] = []

    def publish(self, checkpoint: dict) -> None:
        self.items.append(json.loads(json.dumps(checkpoint)))

    def latest(self) -> dict | None:
        return self.items[-1] if self.items else None


# ---- create ----

def _head(session: Session) -> tuple[int, str, int]:
    head = session.execute(select(LedgerEntry.seq, LedgerEntry.entry_hash).order_by(LedgerEntry.seq.desc()).limit(1)).first()
    count = session.scalar(select(func.count()).select_from(LedgerEntry)) or 0
    return (head[0], head[1], count) if head else (0, "0" * 64, 0)


def create_checkpoint(session: Session, signer: Signer, witness: Witness) -> dict:
    """Signs the current head. Verifies the chain first: never sign a ledger that is already broken."""
    chain = Ledger().verify(session)
    if not chain.ok:
        raise ValueError(f"ledger does not verify (first bad seq {chain.first_bad_seq}); refusing to sign it")
    head_seq, head_hash, count = _head(session)
    revisions = sorted(r for r in session.scalars(select(DomainEvent.ruleset_rev).where(
        DomainEvent.seq <= head_seq, DomainEvent.ruleset_rev.is_not(None)).distinct()))
    statement = canonical({
        "v": STATEMENT_VERSION, "ledger": "awoc", "head_seq": head_seq, "head_hash": head_hash, "entry_count": count,
        "created_at": port(ClockPort).now().isoformat(), "key_id": signer.key_id, "ruleset_revisions": revisions,
    })
    signature = signer.sign(statement.encode())
    row = Checkpoint(created_at=port(ClockPort).now(), head_seq=head_seq, head_hash=head_hash, entry_count=count,
                     key_id=signer.key_id, statement=statement, signature=signature)
    session.add(row)
    session.flush()
    copy = {"id": str(row.id), "statement": statement, "signature": signature}
    witness.publish(copy)
    session.commit()
    return copy


# ---- verify ----

@dataclass
class AuditReport:
    ok: bool
    status: str             # VERIFIED | NO_TRUSTED_CHECKPOINT | CHAIN_BROKEN | UNTRUSTED_KEY | INVALID_SIGNATURE
                            # | TRUNCATED | HISTORY_REWRITTEN | ENTRIES_DELETED
    detail: str
    checked: int
    first_bad_seq: int | None = None
    checkpoint_seq: int | None = None
    checkpoint_at: str | None = None
    checkpoint_key_id: str | None = None
    entries_after_checkpoint: int | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def verify(session: Session, trusted_keys: dict[str, Ed25519PublicKey], witness: Witness | None) -> AuditReport:
    chain = Ledger().verify(session)
    if not chain.ok:
        return AuditReport(False, "CHAIN_BROKEN", chain.detail or "chain does not verify", chain.checked,
                           chain.first_bad_seq)

    latest = witness.latest() if witness else None
    if latest is None:
        return AuditReport(True, "NO_TRUSTED_CHECKPOINT",
                           "The chain is internally consistent, but there is no trusted checkpoint yet, so a rebuilt "
                           "chain or deleted newest entries cannot be ruled out.", chain.checked)

    statement = latest["statement"]
    cp = json.loads(statement)
    base = dict(checked=chain.checked, checkpoint_seq=cp["head_seq"], checkpoint_at=cp["created_at"],
                checkpoint_key_id=cp["key_id"])
    key = trusted_keys.get(cp["key_id"])
    if key is None:
        return AuditReport(False, "UNTRUSTED_KEY", f"checkpoint is signed with key '{cp['key_id']}', which is not "
                                                   "in the trusted key configuration", **base)
    try:
        key.verify(base64.b64decode(latest["signature"]), statement.encode())
    except (InvalidSignature, ValueError):
        return AuditReport(False, "INVALID_SIGNATURE", "checkpoint signature does not verify", **base)

    head = session.get(LedgerEntry, cp["head_seq"]) if cp["head_seq"] else None
    max_seq = session.scalar(select(func.max(LedgerEntry.seq))) or 0
    if cp["head_seq"] and head is None:
        status = "TRUNCATED" if max_seq < cp["head_seq"] else "ENTRIES_DELETED"
        return AuditReport(False, status, f"ledger entry {cp['head_seq']} recorded in the checkpoint is missing "
                                          f"(newest entry now {max_seq})", first_bad_seq=cp["head_seq"], **base)
    if head is not None and head.entry_hash != cp["head_hash"]:
        return AuditReport(False, "HISTORY_REWRITTEN", f"entry {cp['head_seq']} no longer has the hash recorded in "
                                                       "the checkpoint: the chain up to it was rebuilt",
                           first_bad_seq=cp["head_seq"], **base)
    count = session.scalar(select(func.count()).select_from(LedgerEntry).where(LedgerEntry.seq <= cp["head_seq"])) or 0
    if count != cp["entry_count"]:
        return AuditReport(False, "ENTRIES_DELETED", f"checkpoint covered {cp['entry_count']} entries, "
                                                     f"{count} remain", **base)
    after = session.scalar(select(func.count()).select_from(LedgerEntry).where(LedgerEntry.seq > cp["head_seq"])) or 0
    return AuditReport(True, "VERIFIED", "Chain verifies and matches the latest trusted checkpoint. Entries after "
                                         "the checkpoint are covered by the chain only until the next checkpoint.",
                       entries_after_checkpoint=after, **base)


# ---- configuration ----

def configured_signer() -> Signer:
    if not (settings.audit_signing_key_file and settings.audit_signing_key_id):
        raise ServiceUnavailable("checkpoint signing is not configured (AUDIT_SIGNING_KEY_FILE, AUDIT_SIGNING_KEY_ID)")
    return Signer.from_pem_file(settings.audit_signing_key_id, settings.audit_signing_key_file)


def configured_trusted_keys() -> dict[str, Ed25519PublicKey]:
    return load_trusted_keys(settings.audit_trusted_keys_file) if settings.audit_trusted_keys_file else {}


def configured_witness() -> Witness | None:
    return LocalFileWitness(settings.audit_witness_dir) if settings.audit_witness_dir else None


def main() -> int:
    from app.main import create_app
    from app.platform.db import new_session

    create_app()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "verify"
    with new_session() as s:
        if cmd == "checkpoint":
            witness = configured_witness()
            if witness is None:
                print("AUDIT_WITNESS_DIR is not set")
                return 1
            print(json.dumps(json.loads(create_checkpoint(s, configured_signer(), witness)["statement"]), indent=2))
            return 0
        report = verify(s, configured_trusted_keys(), configured_witness())
        print(json.dumps(report.as_dict(), indent=2))
        return 0 if report.ok else 2


if __name__ == "__main__":
    sys.exit(main())
