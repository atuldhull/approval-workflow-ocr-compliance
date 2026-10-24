"""Who is calling, and may they do this?

Two identity modes, chosen by DEMO_AUTH:
- demo (DEMO_AUTH=true, local only): X-Demo-* headers pick a synthetic user so the UI can switch roles.
- oidc (DEMO_AUTH=false): a Bearer access token from the identity provider (Keycloak), verified in oidc.py.
  X-Demo-* headers are refused outright in this mode.

Two policy engines, chosen by AUTHZ_ENGINE, both driven by the table in policy.py:
- local: evaluated in-process.
- cerbos: asked over HTTP. If Cerbos cannot answer, the request fails (503); it never falls back to allow.
"""
from uuid import UUID

import httpx
from fastapi import Header, HTTPException, Request

from app.platform import policy
from app.platform.errors import ServiceUnavailable
from app.platform.oidc import InvalidToken, JwksCache, TokenVerifier
from app.platform.settings import Settings, settings
from contracts.enums import Role
from contracts.errors import Forbidden
from contracts.types import Principal, ResourceRef

COLLECTION = "_collection_"  # Cerbos needs a resource id; list-level checks use this one


class Authz:
    """Local policy engine."""

    def check(self, principal: Principal, action: str, resource: ResourceRef) -> None:
        reason = policy.decide(principal, action, resource, settings.demo_mode)
        if reason:
            raise Forbidden(reason)


class CerbosAuthz:
    """Asks a Cerbos policy decision point. Denies on anything but an explicit EFFECT_ALLOW."""

    def __init__(self, url: str, timeout: float = 2.0, http: httpx.Client | None = None):
        self.url = url.rstrip("/")
        self.http = http or httpx.Client(timeout=timeout)

    @staticmethod
    def request_body(principal: Principal, action: str, resource: ResourceRef) -> dict:
        p_attr = {k: str(v) for k, v in (("region", principal.region), ("institution_id", principal.institution_id))
                  if v is not None}
        r_attr = {k: str(v) for k, v in (("owner_institution_id", resource.owner_institution_id),
                                         ("region", resource.region)) if v is not None}
        r_attr["is_collection"] = resource.id is None
        return {
            "requestId": f"{principal.user_id}:{action}",
            "principal": {"id": str(principal.user_id), "roles": [str(principal.role)], "attr": p_attr},
            "resources": [{
                "actions": [action],
                "resource": {"kind": resource.type, "id": str(resource.id) if resource.id else COLLECTION,
                             "attr": r_attr},
            }],
        }

    def check(self, principal: Principal, action: str, resource: ResourceRef) -> None:
        reason = policy.precheck(action, resource, settings.demo_mode)
        if reason:
            raise Forbidden(reason)
        try:
            r = self.http.post(f"{self.url}/api/check/resources", json=self.request_body(principal, action, resource))
            r.raise_for_status()
            effect = r.json()["results"][0]["actions"].get(action)
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as e:
            raise ServiceUnavailable("authorisation service unavailable") from e
        if effect != "EFFECT_ALLOW":
            raise Forbidden(f"{principal.role} may not {action} on this {resource.type}")


def build_authz(s: Settings):
    return CerbosAuthz(s.cerbos_url, s.cerbos_timeout_seconds) if s.authz_engine == "cerbos" else Authz()


_verifier: TokenVerifier | None = None


def get_verifier() -> TokenVerifier:
    global _verifier
    if _verifier is None:
        _verifier = TokenVerifier(settings.oidc_issuer, settings.oidc_audience, settings.oidc_algorithms,
                                  JwksCache(settings.oidc_jwks_url), settings.oidc_leeway_seconds)
    return _verifier


def set_verifier(verifier: TokenVerifier | None) -> None:
    global _verifier
    _verifier = verifier


def _unauthorised(detail: str) -> HTTPException:
    return HTTPException(status_code=401, detail=detail, headers={"WWW-Authenticate": 'Bearer error="invalid_token"'})


def _bearer(request: Request) -> str:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="sign-in required", headers={"WWW-Authenticate": "Bearer"})
    return token.strip()


def _demo_principal(user: UUID | None, role: Role | None, institution: UUID | None, region: str | None) -> Principal:
    if user is None or role is None:
        raise HTTPException(status_code=401, detail="X-Demo-User and X-Demo-Role headers are required")
    if role == Role.SYSTEM:
        raise HTTPException(status_code=401, detail="SYSTEM is not a user role")
    if role == Role.INSTITUTION and institution is None:
        raise HTTPException(status_code=401, detail="institution users need X-Demo-Institution")
    if role == Role.RO_OFFICER and not region:
        raise HTTPException(status_code=401, detail="regional officers need X-Demo-Region")
    return Principal(user_id=user, role=role, region=region,
                     institution_id=institution if role == Role.INSTITUTION else None)


def current_principal(
    request: Request,
    x_demo_user: UUID | None = Header(default=None),
    x_demo_role: Role | None = Header(default=None),
    x_demo_institution: UUID | None = Header(default=None),
    x_demo_region: str | None = Header(default=None),
) -> Principal:
    if settings.demo_auth:
        return _demo_principal(x_demo_user, x_demo_role, x_demo_institution, x_demo_region)
    if any(name.lower().startswith("x-demo-") for name in request.headers.keys()):
        raise HTTPException(status_code=401, detail="demo identity headers are not accepted")
    try:
        return get_verifier().principal(_bearer(request))
    except InvalidToken:
        raise _unauthorised("invalid or expired token") from None
