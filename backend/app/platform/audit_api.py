"""Audit endpoints for oversight roles. They return integrity results, never event payloads."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from app.platform import audit, replay
from app.platform.auth import current_principal
from app.platform.db import new_session
from app.platform.errors import ServiceUnavailable
from app.platform.models import Checkpoint
from app.platform.registry import port
from contracts.ports import AuthzPort
from contracts.types import Principal, ResourceRef

router = APIRouter(prefix="/audit", tags=["audit"])
AUDIT = ResourceRef("audit")


class CheckpointOut(BaseModel):
    id: str
    created_at: str
    head_seq: int
    entry_count: int
    key_id: str


@router.get("/verify")
def verify(principal: Principal = Depends(current_principal)):
    """Chain check plus comparison with the latest checkpoint held by the independent witness."""
    port(AuthzPort).check(principal, "audit.checkpoint.read", AUDIT)
    with new_session() as s:
        report = audit.verify(s, audit.configured_trusted_keys(), audit.configured_witness())
    return {**report.as_dict(), "witness_configured": audit.configured_witness() is not None}


@router.get("/checkpoints", response_model=list[CheckpointOut])
def checkpoints(principal: Principal = Depends(current_principal)):
    port(AuthzPort).check(principal, "audit.checkpoint.read", AUDIT)
    with new_session() as s:
        rows = s.scalars(select(Checkpoint).order_by(Checkpoint.created_at.desc()).limit(50)).all()
        return [CheckpointOut(id=str(c.id), created_at=c.created_at.isoformat(), head_seq=c.head_seq,
                              entry_count=c.entry_count, key_id=c.key_id) for c in rows]


@router.post("/checkpoints", response_model=CheckpointOut, status_code=201)
def create(principal: Principal = Depends(current_principal)):
    port(AuthzPort).check(principal, "audit.checkpoint.create", AUDIT)
    witness = audit.configured_witness()
    if witness is None:
        raise ServiceUnavailable("no checkpoint witness is configured (AUDIT_WITNESS_DIR)")
    with new_session() as s:
        copy = audit.create_checkpoint(s, audit.configured_signer(), witness)
        c = s.get(Checkpoint, copy["id"])
        return CheckpointOut(id=str(c.id), created_at=c.created_at.isoformat(), head_seq=c.head_seq,
                             entry_count=c.entry_count, key_id=c.key_id)


@router.post("/replay")
def run_replay(principal: Principal = Depends(current_principal)):
    """Rebuilds every registered projection from events (read-only) and compares it with the live tables."""
    port(AuthzPort).check(principal, "audit.replay", AUDIT)
    return replay.replay()
