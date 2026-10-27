"""Signed checkpoints of the ledger, and verification against them.

The hash chain (ledger.py) shows that no event changed after the entry that follows it. It cannot show that the
whole chain was not rebuilt, or that the newest entries were not cut off. A checkpoint fixes that: it records the
ledger head (seq, entry hash, entry count) at a moment in time, signed with an Ed25519 key, and a copy is handed
to a witness outside the database. Verification trusts only the witness copy and public keys from configuration -
never the database's own checkpoint rows.

A checkpoint is evidence of integrity for this system. It is not a legal or digital signature on any decision.

    python -m app.platform.audit checkpoint     # sign the current head and hand it to the witness
    python -m app.platform.audit verify         # chain + latest trusted checkpoint
    python -m app.platform.audit publish        # retry checkpoints left PENDING by a witness failure
    python -m app.platform.audit export f.jsonl # published copies, for independent storage
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

class WitnessError(Exception):
    """The witness cannot be read or written, or holds something unusable."""


class WitnessCorrupt(WitnessError):
    """The witness answered, but what it holds cannot be a checkpoint copy."""


class WitnessConflict(WitnessError):
    """Publishing would rewind the trusted history (a lower head than already published)."""


class Witness(Protocol):
    kind: str

    def publish(self, checkpoint: dict) -> None: ...   # idempotent by checkpoint id
    def latest(self) -> dict | None: ...


def _check_order(existing: list[dict], checkpoint: dict) -> bool:
    """True if this exact copy is already published (a retry). Raises WitnessConflict if accepting it would create
    a competing trusted history: a different copy under the same id, a different head hash at an entry the
    witness already vouches for, or a head older than the latest one."""
    same_id = [c for c in existing if c["id"] == checkpoint["id"]]
    if same_id:
        if any(c["statement"] != checkpoint["statement"] or c["signature"] != checkpoint["signature"] for c in same_id):
            raise WitnessConflict(f"witness already holds a different checkpoint with id {checkpoint['id']}")
        return True
    new = json.loads(checkpoint["statement"])
    for c in existing:
        old = json.loads(c["statement"])
        if old["head_seq"] == new["head_seq"] and old["head_hash"] != new["head_hash"]:
            raise WitnessConflict(f"witness already vouches for a different entry {new['head_seq']}; "
                                  "refusing a competing history")
    if existing:
        last = json.loads(existing[-1]["statement"])["head_seq"]
        if new["head_seq"] < last:
            raise WitnessConflict(f"witness already holds a checkpoint at entry {last}; refusing to publish "
                                  f"{new['head_seq']}")
    return False


class LocalFileWitness:
    """DEMO ONLY: append-only JSON lines in a local directory.

    It lives on the same machine as the database, so it is not truly independent. In a real deployment the
    witness must be storage the database administrators cannot rewrite: a write-once bucket, another
    organisation's service, or a printed and countersigned digest (see `export_checkpoints`).
    """
    kind = "local-file (DEMO ONLY)"

    def __init__(self, directory: str):
        self.path = Path(directory) / "checkpoints.jsonl"

    def _all(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            lines = [ln for ln in self.path.read_text(encoding="utf-8").splitlines() if ln.strip()]
            items = [json.loads(ln) for ln in lines]
        except OSError as e:
            raise WitnessError(f"witness file cannot be read: {type(e).__name__}") from e
        except ValueError as e:
            raise WitnessCorrupt("witness file is corrupt (a line is not valid JSON)") from e
        if not all(isinstance(i, dict) and {"id", "statement", "signature"} <= i.keys() for i in items):
            raise WitnessCorrupt("witness file is corrupt (an entry is missing fields)")
        return items

    def publish(self, checkpoint: dict) -> None:
        if _check_order(self._all(), checkpoint):
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(checkpoint, sort_keys=True) + "\n")
        except OSError as e:
            raise WitnessError(f"witness file cannot be written: {type(e).__name__}") from e

    def latest(self) -> dict | None:
        items = self._all()
        return items[-1] if items else None


class MemoryWitness:
    kind = "memory (tests)"

    def __init__(self):
        self.items: list[dict] = []
        self.fail_next = False

    def publish(self, checkpoint: dict) -> None:
        if self.fail_next:
            self.fail_next = False
            raise WitnessError("simulated witness outage")
        if not _check_order(self.items, checkpoint):
            self.items.append(json.loads(json.dumps(checkpoint)))

    def latest(self) -> dict | None:
        return self.items[-1] if self.items else None


# ---- create and publish ----
#
# The database and the witness cannot commit atomically. Publication is therefore a recoverable two-step process:
#   1. sign the statement and commit the checkpoint row as PENDING (durable intent; nothing is published yet);
#   2. hand exactly that signed copy to the witness (idempotent by id), then mark the row PUBLISHED.
# A crash or witness failure between the steps leaves a PENDING row that publish_pending() re-publishes - the same
# statement and signature, never re-signed - so the trusted history cannot fork. A failed database commit in step 1
# publishes nothing. New checkpoints are refused while an older one is still pending.

def _head(session: Session) -> tuple[int, str, int]:
    head = session.execute(select(LedgerEntry.seq, LedgerEntry.entry_hash).order_by(LedgerEntry.seq.desc()).limit(1)).first()
    count = session.scalar(select(func.count()).select_from(LedgerEntry)) or 0
    return (head[0], head[1], count) if head else (0, "0" * 64, 0)


def _copy(row: Checkpoint) -> dict:
    return {"id": str(row.id), "statement": row.statement, "signature": row.signature}


def sign_checkpoint(session: Session, signer: Signer) -> Checkpoint:
    """Step 1. Verifies the chain first: never sign a ledger that is already broken."""
    if session.scalar(select(func.count()).select_from(Checkpoint).where(Checkpoint.status == "PENDING")):
        raise CheckpointPending("an earlier checkpoint is not published yet; publish it first")
    chain = Ledger().verify(session)
    if not chain.ok:
        raise ValueError(f"ledger does not verify (first bad seq {chain.first_bad_seq}); refusing to sign it")
    head_seq, head_hash, count = _head(session)
    revisions = sorted(r for r in session.scalars(select(DomainEvent.ruleset_rev).where(
        DomainEvent.seq <= head_seq, DomainEvent.ruleset_rev.is_not(None)).distinct()))
    now = port(ClockPort).now()
    statement = canonical({
        "v": STATEMENT_VERSION, "ledger": "awoc", "head_seq": head_seq, "head_hash": head_hash, "entry_count": count,
        "created_at": now.isoformat(), "key_id": signer.key_id, "ruleset_revisions": revisions,
    })
    row = Checkpoint(created_at=now, head_seq=head_seq, head_hash=head_hash, entry_count=count, key_id=signer.key_id,
                     statement=statement, signature=signer.sign(statement.encode()), status="PENDING")
    session.add(row)
    session.commit()
    return row


def publish_pending(session: Session, witness: Witness) -> list[str]:
    """Step 2, also the recovery path. Returns the ids published. A witness failure leaves rows PENDING."""
    done = []
    for row in session.scalars(select(Checkpoint).where(Checkpoint.status == "PENDING").order_by(Checkpoint.created_at)):
        try:
            witness.publish(_copy(row))
        except WitnessError as e:
            row.publish_error = str(e)[:500]
            session.commit()
            raise
        row.status, row.published_at, row.publish_error = "PUBLISHED", port(ClockPort).now(), None
        session.commit()
        done.append(str(row.id))
    return done


def create_checkpoint(session: Session, signer: Signer, witness: Witness) -> dict:
    """Signs the current head and publishes it. On a witness failure the checkpoint stays PENDING (WitnessError)."""
    row = sign_checkpoint(session, signer)
    publish_pending(session, witness)
    return _copy(row)


def export_checkpoints(session: Session) -> list[dict]:
    """Published checkpoint copies, for handing to independent storage. Each copy verifies on its own signature."""
    rows = session.scalars(select(Checkpoint).where(Checkpoint.status == "PUBLISHED").order_by(Checkpoint.head_seq,
                                                                                               Checkpoint.created_at))
    return [_copy(r) for r in rows]


class CheckpointPending(Exception):
    pass


# ---- verify ----

@dataclass
class AuditReport:
    ok: bool
    status: str             # VERIFIED | NO_TRUSTED_CHECKPOINT | CHAIN_BROKEN | WITNESS_UNAVAILABLE | WITNESS_CORRUPT
                            # | UNTRUSTED_KEY | INVALID_SIGNATURE
                            # | TRUNCATED | HISTORY_REWRITTEN | ENTRIES_DELETED
    detail: str
    checked: int
    first_bad_seq: int | None = None
    checkpoint_seq: int | None = None
    checkpoint_at: str | None = None
    checkpoint_key_id: str | None = None
    entries_after_checkpoint: int | None = None
    # What a passing result actually covers: NONE (failed), CHAIN_ONLY (no trusted checkpoint to compare with),
    # CHECKPOINTED_WITH_NEWER_ENTRIES (anchored up to the checkpoint; newer entries rely on the chain alone), or
    # CHECKPOINTED (anchored through the latest entry). Only CHECKPOINTED rules out a rebuilt or cut-off chain.
    assurance: str = "NONE"
    unpublished_checkpoints: int = 0
    witness_kind: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def verify(session: Session, trusted_keys: dict[str, Ed25519PublicKey], witness: Witness | None) -> AuditReport:
    report = _verify(session, trusted_keys, witness)
    report.unpublished_checkpoints = session.scalar(
        select(func.count()).select_from(Checkpoint).where(Checkpoint.status == "PENDING")) or 0
    report.witness_kind = getattr(witness, "kind", None)
    if report.ok:
        if report.status != "VERIFIED":
            report.assurance = "CHAIN_ONLY"
        elif report.entries_after_checkpoint:
            report.assurance = "CHECKPOINTED_WITH_NEWER_ENTRIES"   # the newest entries are not anchored yet
        else:
            report.assurance = "CHECKPOINTED"
    return report


def _verify(session: Session, trusted_keys: dict[str, Ed25519PublicKey], witness: Witness | None) -> AuditReport:
    chain = Ledger().verify(session)
    if not chain.ok:
        return AuditReport(False, "CHAIN_BROKEN", chain.detail or "chain does not verify", chain.checked,
                           chain.first_bad_seq)
    if witness is None:
        return AuditReport(True, "NO_TRUSTED_CHECKPOINT",
                           "The chain is internally consistent, but no witness is configured, so a rebuilt chain or "
                           "deleted newest entries cannot be ruled out.", chain.checked)
    try:
        latest = witness.latest()
        cp = json.loads(latest["statement"]) if latest else None
        if cp is not None and not {"head_seq", "head_hash", "entry_count", "created_at", "key_id"} <= cp.keys():
            raise WitnessCorrupt("latest witness entry is not a checkpoint statement")
    except WitnessCorrupt as e:
        return AuditReport(False, "WITNESS_CORRUPT", str(e), chain.checked)
    except (ValueError, TypeError, AttributeError):
        return AuditReport(False, "WITNESS_CORRUPT", "latest witness entry is not a checkpoint statement", chain.checked)
    except WitnessError as e:
        return AuditReport(False, "WITNESS_UNAVAILABLE", f"{e}. Integrity against the trusted checkpoint cannot be "
                                                         "checked right now.", chain.checked)
    if latest is None:
        return AuditReport(True, "NO_TRUSTED_CHECKPOINT",
                           "The chain is internally consistent, but the witness holds no checkpoint yet, so a rebuilt "
                           "chain or deleted newest entries cannot be ruled out.", chain.checked)

    statement = latest["statement"]
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
        if cmd == "export":   # python -m app.platform.audit export <file.jsonl>
            out = Path(sys.argv[2])
            out.write_text("".join(json.dumps(c, sort_keys=True) + "\n" for c in export_checkpoints(s)), encoding="utf-8")
            print(f"exported published checkpoints to {out}")
            return 0
        if cmd in ("checkpoint", "publish"):
            witness = configured_witness()
            if witness is None:
                print("AUDIT_WITNESS_DIR is not set")
                return 1
            if cmd == "publish":
                print(f"published {len(publish_pending(s, witness))} pending checkpoint(s)")
                return 0
            print(json.dumps(json.loads(create_checkpoint(s, configured_signer(), witness)["statement"]), indent=2))
            return 0
        report = verify(s, configured_trusted_keys(), configured_witness())
        print(json.dumps(report.as_dict(), indent=2))
        return 0 if report.ok else 2


if __name__ == "__main__":
    sys.exit(main())
