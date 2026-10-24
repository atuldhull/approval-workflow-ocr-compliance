"""Real sign-in (OIDC tokens) and server-side policy, without needing a running Keycloak or Cerbos."""
import json
import time
from dataclasses import replace
from uuid import UUID, uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from app.platform import auth, policy
from app.platform.errors import ServiceUnavailable
from app.platform.oidc import InvalidToken, JwksCache, TokenVerifier
from app.platform.settings import problems, settings
from conftest import NORTHFIELD, SUNRISE, headers
from contracts.enums import Role
from contracts.errors import Forbidden
from contracts.types import Principal, ResourceRef

ISSUER = "http://idp.test/realms/awoc"
AUDIENCE = "awoc-api"
SUNRISE_USER = "00000000-0000-4000-9000-000000000001"
NORTHFIELD_USER = "00000000-0000-4000-9000-000000000004"


def new_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def jwk(key, kid):
    d = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    return {**d, "kid": kid, "use": "sig", "alg": "RS256"}


KEY, OTHER = new_key(), new_key()


class FakeIdp:
    def __init__(self):
        self.keys = [jwk(KEY, "k1")]
        self.fetches = 0
        self.down = False

    def fetch(self, url):
        self.fetches += 1
        if self.down:
            raise httpx.ConnectError("down")
        return {"keys": self.keys}


def token(key=KEY, kid="k1", alg="RS256", **claims):
    now = int(time.time())
    body = {"iss": ISSUER, "aud": AUDIENCE, "sub": SUNRISE_USER, "iat": now, "exp": now + 300, "typ": "Bearer",
            "realm_access": {"roles": ["INSTITUTION", "offline_access"]},
            "institution_id": str(SUNRISE)}
    body.update(claims)
    body = {k: v for k, v in body.items() if v is not None}
    return jwt.encode(body, key, algorithm=alg, headers={"kid": kid})


def verifier(idp=None, clock=None):
    idp = idp or FakeIdp()
    cache = JwksCache("http://idp.test/certs", fetch=idp.fetch, now=clock or time.monotonic)
    return TokenVerifier(ISSUER, AUDIENCE, ("RS256",), cache, leeway=0)


# ---- token verification ----

def test_valid_token_gives_a_principal_from_its_claims():
    p = verifier().principal(token())
    assert p == Principal(UUID(SUNRISE_USER), Role.INSTITUTION, None, SUNRISE)


@pytest.mark.parametrize("bad", [
    lambda: token(key=OTHER),                                     # signature by a key the IdP never published
    lambda: token(exp=int(time.time()) - 10),                     # expired
    lambda: token(iss="http://evil.test/realms/awoc"),            # wrong issuer
    lambda: token(aud="some-other-api"),                          # wrong audience
    lambda: token(nbf=int(time.time()) + 600),                    # not yet valid
    lambda: token(exp=None),                                      # no expiry at all
    lambda: token(typ="ID"),                                      # an ID token is not an access token
    lambda: token(kid="unknown"),                                 # key id the IdP does not have
    lambda: token(sub="not-a-uuid"),
    lambda: "not.a.jwt",
    lambda: jwt.encode({"sub": SUNRISE_USER}, None, algorithm="none"),          # unsigned
    lambda: jwt.encode({"iss": ISSUER, "aud": AUDIENCE, "sub": SUNRISE_USER, "exp": int(time.time()) + 60},
                       "a-shared-secret-of-at-least-32-bytes!!", algorithm="HS256", headers={"kid": "k1"}),
])
def test_untrustworthy_tokens_are_rejected(bad):
    with pytest.raises(InvalidToken):
        verifier().principal(bad())


def test_token_signed_with_a_rotated_key_is_accepted_after_refresh():
    idp, t = FakeIdp(), [0.0]
    v = verifier(idp, clock=lambda: t[0])
    v.principal(token())
    idp.keys = [jwk(OTHER, "k2")]              # provider rotates its signing key
    t[0] += 60
    assert v.principal(token(key=OTHER, kid="k2")).role == Role.INSTITUTION
    assert idp.fetches == 2


def test_unknown_key_ids_cannot_force_repeated_fetches():
    idp, t = FakeIdp(), [0.0]
    v = verifier(idp, clock=lambda: t[0])
    for _ in range(5):
        with pytest.raises(InvalidToken):
            v.principal(token(kid="forged"))
    assert idp.fetches == 1


def test_provider_outage_without_cached_keys_is_503_not_allow():
    idp = FakeIdp()
    idp.down = True
    with pytest.raises(ServiceUnavailable):
        verifier(idp).principal(token())


def test_cached_keys_keep_working_during_a_provider_outage():
    idp, t = FakeIdp(), [0.0]
    v = verifier(idp, clock=lambda: t[0])
    v.principal(token())
    idp.down = True
    t[0] += 3600
    assert v.principal(token()).role == Role.INSTITUTION


@pytest.mark.parametrize("claims, message", [
    ({"realm_access": {"roles": ["offline_access"]}}, "exactly one application role"),
    ({"realm_access": {"roles": ["INSTITUTION", "AUDITOR"]}}, "exactly one application role"),
    ({"realm_access": {"roles": ["SYSTEM"]}}, "exactly one application role"),
    ({"institution_id": None}, "not linked to an institution"),
    ({"realm_access": {"roles": ["RO_OFFICER"]}, "region": None}, "has no region"),
])
def test_accounts_without_a_usable_scope_are_refused(claims, message):
    with pytest.raises(Forbidden, match=message):
        verifier().principal(token(**claims))


def test_officer_tokens_never_carry_an_institution_scope():
    p = verifier().principal(token(realm_access={"roles": ["RO_OFFICER"]}, region="Southern"))
    assert (p.role, p.region, p.institution_id) == (Role.RO_OFFICER, "Southern", None)


# ---- the API in real-sign-in mode ----

@pytest.fixture
def oidc(monkeypatch):
    monkeypatch.setattr(auth, "settings", replace(settings, demo_auth=False, oidc_issuer=ISSUER,
                                                   oidc_audience=AUDIENCE, oidc_jwks_url="http://idp.test/certs"))
    idp = FakeIdp()
    auth.set_verifier(verifier(idp))
    yield idp
    auth.set_verifier(None)


def bearer(**claims):
    return {"Authorization": f"Bearer {token(**claims)}"}


def test_forged_demo_headers_are_refused_in_real_mode(client, oidc):
    r = client.get("/api/applications", headers=headers("AUDITOR"))
    assert r.status_code == 401 and "demo identity headers" in r.text
    # even next to a valid token
    r = client.get("/api/applications", headers={**bearer(), "X-Demo-Role": "BUREAU_HEAD"})
    assert r.status_code == 401


def test_requests_without_a_token_are_401(client, oidc):
    r = client.get("/api/applications")
    assert r.status_code == 401 and r.headers["www-authenticate"].startswith("Bearer")


def test_invalid_token_is_401_without_details(client, oidc):
    r = client.get("/api/applications", headers=bearer(aud="other"))
    assert r.status_code == 401 and r.json()["detail"] == "invalid or expired token"


def test_signed_in_institution_works_and_cannot_reach_another_institution(client, oidc):
    created = client.post("/api/applications", headers=bearer(),
                          json={"institution_id": str(SUNRISE), "category": "NEW_PROGRAMME", "academic_year": "2027-28"})
    assert created.status_code == 201, created.text
    app_id = created.json()["id"]
    assert client.get("/api/auth/me", headers=bearer()).json()["institution_id"] == str(SUNRISE)

    other = bearer(sub=NORTHFIELD_USER, institution_id=str(NORTHFIELD))
    assert client.get(f"/api/applications/{app_id}", headers=other).status_code == 403
    assert client.get(f"/api/cases/{app_id}/timeline", headers=other).status_code == 403
    assert client.post(f"/api/applications/{app_id}/submit", headers=other).status_code == 403
    assert client.get("/api/applications", headers=other).json() == []


def test_identity_provider_outage_fails_closed(client, oidc):
    down = FakeIdp()
    down.down = True
    auth.set_verifier(verifier(down))  # no keys cached yet and the provider is unreachable
    assert client.get("/api/applications", headers=bearer()).status_code == 503


def test_auth_config_exposes_no_secrets(client, oidc):
    body = client.get("/api/auth/config").json()
    assert body["mode"] == "demo"  # the api module reads the process settings, which are demo in tests
    assert set(body) == {"mode", "demo_mode", "issuer", "client_id"}


# ---- policy ----

def _inst(iid=SUNRISE):
    return Principal(uuid4(), Role.INSTITUTION, None, iid)


def _ro(region="Southern"):
    return Principal(uuid4(), Role.RO_OFFICER, region, None)


def test_unknown_actions_and_kinds_are_denied():
    bureau = Principal(uuid4(), Role.BUREAU_HEAD)
    assert "unknown action" in policy.decide(bureau, "application.delete", ResourceRef("application"), True)
    assert "unknown resource kind" in policy.decide(bureau, "ledger.verify", ResourceRef("spaceship"), True)


def test_time_travel_is_refused_outside_demo_mode():
    assert policy.decide(_inst(), "sim.clock", ResourceRef("clock"), demo_mode=False)
    assert policy.decide(_inst(), "sim.clock", ResourceRef("clock"), demo_mode=True) is None


def test_institution_records_without_a_known_owner_are_refused():
    assert policy.decide(_inst(), "application.read", ResourceRef("application", uuid4()), True) == "record owner unknown"


def test_regional_officers_are_confined_to_their_region():
    app = ResourceRef("application", uuid4(), SUNRISE, "Southern")
    assert policy.decide(_ro("Southern"), "case.timeline", app, True) is None
    assert "own region" in policy.decide(_ro("Northern"), "case.timeline", app, True)
    # a record or list whose region the caller did not state is refused rather than assumed
    assert policy.decide(_ro(), "application.read", ResourceRef("application", uuid4(), SUNRISE), True)
    assert policy.decide(_ro(), "application.read", ResourceRef("application"), True)
    assert policy.decide(_ro(), "application.read", ResourceRef("application", region="Southern"), True) is None
    assert policy.decide(_ro(None), "ruleset.read", ResourceRef("ruleset"), True) == "regional officer has no region"


def test_regional_officer_api_access_follows_region(client):
    app_id = client.post("/api/applications", headers=headers("INSTITUTION", SUNRISE),
                         json={"institution_id": str(SUNRISE), "category": "NEW_PROGRAMME",
                               "academic_year": "2027-28"}).json()["id"]
    southern = {**headers("RO_OFFICER"), "X-Demo-Region": "Southern"}
    northern = {**headers("RO_OFFICER"), "X-Demo-Region": "Northern"}
    assert client.get(f"/api/cases/{app_id}/timeline", headers=southern).status_code == 200
    assert client.get(f"/api/cases/{app_id}/timeline", headers=northern).status_code == 403
    # the application list does not filter by region yet, so it is refused rather than leaked
    assert client.get("/api/applications", headers=southern).status_code == 403
    assert client.get("/api/applications", headers=headers("RO_OFFICER")).status_code == 401  # no region


def test_demo_headers_cannot_claim_the_system_role(client):
    assert client.get("/api/applications", headers=headers("SYSTEM")).status_code == 401


# ---- Cerbos client ----

def cerbos(handler):
    return auth.CerbosAuthz("http://cerbos.test", http=httpx.Client(transport=httpx.MockTransport(handler)))


def effect(value):
    return lambda req: httpx.Response(200, json={"results": [{"actions": {
        json.loads(req.content)["resources"][0]["actions"][0]: value}}]})


def test_cerbos_allow_and_deny():
    app = ResourceRef("application", uuid4(), SUNRISE, "Southern")
    cerbos(effect("EFFECT_ALLOW")).check(_inst(), "application.read", app)
    with pytest.raises(Forbidden):
        cerbos(effect("EFFECT_DENY")).check(_inst(), "application.read", app)


@pytest.mark.parametrize("handler", [
    lambda req: httpx.Response(500),
    lambda req: (_ for _ in ()).throw(httpx.ConnectTimeout("timeout")),
    lambda req: httpx.Response(200, json={"unexpected": True}),
])
def test_cerbos_unavailable_fails_closed(handler):
    with pytest.raises(ServiceUnavailable):
        cerbos(handler).check(_inst(), "application.read", ResourceRef("application", uuid4(), SUNRISE))


def test_cerbos_is_not_even_asked_about_unknown_actions():
    calls = []
    authz = cerbos(lambda req: calls.append(req) or httpx.Response(500))
    with pytest.raises(Forbidden):
        authz.check(_inst(), "application.delete", ResourceRef("application"))
    assert calls == []


def test_cerbos_request_carries_scope_attributes():
    body = auth.CerbosAuthz.request_body(_ro(), "case.timeline", ResourceRef("application", None, SUNRISE, "Southern"))
    assert body["principal"]["attr"] == {"region": "Southern"}
    assert body["resources"][0]["resource"]["attr"] == {"owner_institution_id": str(SUNRISE), "region": "Southern",
                                                       "is_collection": True}


# ---- startup configuration ----

def test_production_refuses_demo_security():
    found = problems(replace(settings, app_env="production", demo_auth=True, demo_mode=True))
    assert any("DEMO_AUTH" in p for p in found) and any("DEMO_MODE" in p for p in found)
    assert any("AUTHZ_ENGINE must be cerbos" in p for p in found)


def test_real_mode_refuses_missing_or_weak_identity_configuration():
    found = problems(replace(settings, demo_auth=False, oidc_algorithms=("HS256",)))
    assert any("OIDC_ISSUER" in p for p in found) and any("asymmetric" in p for p in found)
    assert problems(replace(settings, authz_engine="cerbos", cerbos_url=""))


def test_app_refuses_to_start_with_unsafe_configuration(monkeypatch):
    from app.platform import wiring
    monkeypatch.setattr(wiring, "settings", replace(settings, app_env="production"))
    with pytest.raises(RuntimeError, match="unsafe configuration"):
        wiring.wire()
