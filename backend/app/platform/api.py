from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from app.platform.auth import current_principal
from app.platform.db import new_session
from app.platform.models import DomainEvent
from app.platform.registry import port
from app.platform.settings import settings
from contracts.ports import AuthzPort, CasePort, LedgerPort
from contracts.types import Principal, ResourceRef

router = APIRouter(tags=["audit"])


class TimelineEvent(BaseModel):
    seq: int
    at: str
    event_type: str
    role: str
    ruleset_rev: str | None
    payload: dict


class VerifyOut(BaseModel):
    ok: bool
    checked: int
    first_bad_seq: int | None
    detail: str | None


class AuthConfigOut(BaseModel):
    mode: str                 # demo | oidc
    demo_mode: bool
    issuer: str | None
    client_id: str | None


class MeOut(BaseModel):
    user_id: UUID
    role: str
    region: str | None
    institution_id: UUID | None


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/auth/config", response_model=AuthConfigOut, tags=["auth"])
def auth_config():
    """Public: tells the browser how to sign in. Contains no secrets (the browser client is public, PKCE)."""
    oidc = settings.auth_mode == "oidc"
    return AuthConfigOut(mode=settings.auth_mode, demo_mode=settings.demo_mode,
                         issuer=settings.oidc_issuer if oidc else None,
                         client_id=settings.oidc_client_id if oidc else None)


@router.get("/auth/me", response_model=MeOut, tags=["auth"])
def me(principal: Principal = Depends(current_principal)):
    port(AuthzPort).check(principal, "auth.me", ResourceRef("principal"))  # always about the caller
    return MeOut(user_id=principal.user_id, role=str(principal.role), region=principal.region,
                 institution_id=principal.institution_id)


@router.get("/cases/{application_id}/timeline", response_model=list[TimelineEvent])
def timeline(application_id: UUID, principal: Principal = Depends(current_principal)):
    with new_session() as session:
        case = port(CasePort).lookup(session, application_id)
        port(AuthzPort).check(principal, "case.timeline",
                              ResourceRef("application", application_id, case.institution_id, case.region))
        # an application's timeline includes events about it and about things attached to it (its deadlines)
        rows = session.scalars(
            select(DomainEvent).where(
                (DomainEvent.aggregate_id == application_id)
                | (DomainEvent.payload["subject_id"].astext == str(application_id))
            ).order_by(DomainEvent.seq)
        ).all()
        return [TimelineEvent(seq=e.seq, at=e.at.isoformat(), event_type=e.event_type, role=e.role,
                              ruleset_rev=e.ruleset_rev, payload=e.payload) for e in rows]


@router.get("/ledger/verify", response_model=VerifyOut)
def verify(principal: Principal = Depends(current_principal)):
    port(AuthzPort).check(principal, "ledger.verify", ResourceRef("ledger"))
    with new_session() as session:
        r = port(LedgerPort).verify(session)
        return VerifyOut(ok=r.ok, checked=r.checked, first_bad_seq=r.first_bad_seq, detail=r.detail)
