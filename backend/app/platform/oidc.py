"""Access-token verification for the identity provider (Keycloak, or any OIDC provider).

A token is trusted only after its signature verifies against a key from the provider's JWKS and its issuer,
audience, expiry and not-before claims check out. Role, region and institution come only from those verified
claims - never from request headers.
"""
import re
import time
from collections.abc import Callable
from typing import Any
from uuid import UUID

import httpx
import jwt
from jwt import PyJWK

from app.platform.errors import ServiceUnavailable
from contracts.enums import Role
from contracts.errors import Forbidden
from contracts.types import Principal

USER_ROLES = frozenset(r.value for r in Role if r != Role.SYSTEM)  # SYSTEM is never a signed-in user
REGION = re.compile(r"^[A-Za-z][A-Za-z -]{0,39}$")
KEY_TYPE_FOR = {"RS": "RSA", "PS": "RSA", "ES": "EC", "EdDSA": "OKP"}


class InvalidToken(Exception):
    """The token cannot be trusted. The reason is for logs only; clients just get 401."""


def fetch_json(url: str) -> dict[str, Any]:
    r = httpx.get(url, timeout=5.0)
    r.raise_for_status()
    return r.json()


class JwksCache:
    """Signing keys from the provider, refreshed on expiry or when an unknown key id appears (key rotation).

    Refreshes triggered by unknown key ids are rate-limited so forged tokens cannot make us hammer the provider.
    If the provider is down, keys already cached keep working; with no keys at all, requests fail with 503.
    """

    def __init__(self, url: str, fetch: Callable[[str], dict] = fetch_json, ttl: float = 300.0,
                 min_refresh_interval: float = 30.0, now: Callable[[], float] = time.monotonic):
        self.url, self.fetch, self.ttl, self.min_refresh_interval, self.now = url, fetch, ttl, min_refresh_interval, now
        self.keys: dict[str, PyJWK] = {}
        self.fetched_at: float | None = None
        self.last_attempt: float | None = None

    def _refresh(self) -> None:
        self.last_attempt = self.now()
        data = self.fetch(self.url)
        keys = {}
        for raw in data.get("keys", []):
            if raw.get("use", "sig") != "sig" or not raw.get("kid"):
                continue
            try:
                keys[raw["kid"]] = PyJWK(raw)
            except jwt.PyJWTError:
                continue  # key type this library cannot use for signatures
        self.keys = keys
        self.fetched_at = self.now()

    def get(self, kid: str) -> PyJWK:
        t = self.now()
        expired = self.fetched_at is None or t - self.fetched_at > self.ttl
        may_retry = self.last_attempt is None or t - self.last_attempt >= self.min_refresh_interval
        if expired or (kid not in self.keys and may_retry):
            try:
                self._refresh()
            except Exception as e:  # noqa: BLE001 - any failure to reach or parse the JWKS
                if not self.keys:
                    raise ServiceUnavailable("identity provider keys are unavailable") from e
        key = self.keys.get(kid)
        if key is None:
            raise InvalidToken("unknown signing key")
        return key


class TokenVerifier:
    def __init__(self, issuer: str, audience: str, algorithms: tuple[str, ...], jwks: JwksCache, leeway: int = 30):
        self.issuer, self.audience, self.algorithms, self.jwks, self.leeway = issuer, audience, algorithms, jwks, leeway

    def claims(self, token: str) -> dict[str, Any]:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as e:
            raise InvalidToken("malformed token") from e
        alg = header.get("alg")
        if alg not in self.algorithms:
            raise InvalidToken(f"algorithm {alg!r} not allowed")
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise InvalidToken("token has no key id")
        key = self.jwks.get(kid)
        declared = key._jwk_data.get("alg")
        if declared and declared != alg:
            raise InvalidToken("token algorithm does not match its key")
        if KEY_TYPE_FOR.get(alg[:2] if alg != "EdDSA" else alg) != key.key_type:
            raise InvalidToken("token algorithm does not fit the key type")
        try:
            claims = jwt.decode(
                token, key.key, algorithms=[alg], audience=self.audience, issuer=self.issuer, leeway=self.leeway,
                options={"require": ["exp", "iat", "iss", "aud", "sub"], "verify_signature": True},
            )
        except jwt.PyJWTError as e:
            raise InvalidToken(type(e).__name__) from e
        except (TypeError, ValueError) as e:  # library errors on odd key/token combinations must be 401, not 500
            raise InvalidToken("token could not be verified") from e
        if claims.get("typ") not in (None, "Bearer"):
            raise InvalidToken("not an access token")  # e.g. an ID token replayed as an access token
        return claims

    def principal(self, token: str) -> Principal:
        return principal_from_claims(self.claims(token))


def principal_from_claims(claims: dict[str, Any]) -> Principal:
    try:
        user_id = UUID(str(claims["sub"]))
    except (KeyError, ValueError) as e:
        raise InvalidToken("subject is not a user id") from e

    realm = claims.get("realm_access") or {}
    roles = {r for r in realm.get("roles", []) if r in USER_ROLES}
    if len(roles) != 1:
        raise Forbidden("account must hold exactly one application role")
    role = Role(roles.pop())

    region = claims.get("region")
    if region is not None and (not isinstance(region, str) or not REGION.match(region)):
        raise InvalidToken("malformed region claim")
    if role == Role.RO_OFFICER and not region:
        raise Forbidden("regional officer account has no region")

    institution_id = None
    if role == Role.INSTITUTION:
        try:
            institution_id = UUID(str(claims["institution_id"]))
        except (KeyError, ValueError):
            raise Forbidden("institution account is not linked to an institution") from None
    return Principal(user_id=user_id, role=role, region=region, institution_id=institution_id)
