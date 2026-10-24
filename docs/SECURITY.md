# Security: sign-in and permissions

## Two modes

| | Demo mode (default) | Real sign-in |
|---|---|---|
| Switch | `DEMO_AUTH=true` | `DEMO_AUTH=false` |
| Who is calling | `X-Demo-*` headers from the role switcher | Bearer access token from Keycloak (OIDC) |
| `X-Demo-*` headers | accepted | **refused with 401**, even next to a valid token |
| Policy engine | `AUTHZ_ENGINE=local` (default) or `cerbos` | `cerbos` (required when `APP_ENV=production`) |
| Use | laptops, demos, tests | anything that is not a local demo |

`APP_ENV=production` refuses to start if `DEMO_AUTH`, `DEMO_MODE` or the local policy engine is enabled, or if
the issuer or JWKS URL is not https. Real sign-in refuses to start without an issuer, audience and JWKS URL, or
with symmetric (`HS*`) algorithms. There is no silent fallback: if Keycloak's keys or Cerbos cannot be reached,
requests fail with 503.

## How a token is checked (`backend/app/platform/oidc.py`)

1. The algorithm must be on the allow-list (`OIDC_ALGORITHMS`, asymmetric only), match the key's declared algorithm,
   and fit the key's type (RSA / EC / OKP). Odd key and token combinations end in 401, never a 500.
2. The signing key is looked up by `kid` in the provider's JWKS. Keys are cached for 5 minutes and refetched on an
   unknown `kid` (key rotation), at most once every 30 seconds, so forged tokens cannot flood the provider.
3. Signature, `iss`, `aud`, `exp`, `nbf` and `iat` are verified (30 s leeway); `exp`, `iat`, `iss`, `aud` and `sub` must be present.
4. `typ` must be `Bearer`, so an ID token cannot be used as an access token.
5. Identity comes only from verified claims: `sub` (user id), exactly one application role from `realm_access.roles`,
   `institution_id` (required for institution accounts) and `region` (required for regional officers).
   Institution and region are user attributes that only a Keycloak administrator can set.

## Permissions (`backend/app/platform/policy.py`)

One table lists which roles may perform which action; anything not listed is denied. On top of it:

- **Institutions** only touch records they own. A record with an id but no known owner is refused.
- **Regional officers** only touch records in their own region. Application, deadline and dashboard requests
  must state the region; if they do not, the request is refused instead of guessed.
- **Time travel** (`sim.clock`) works only with `DEMO_MODE=true`.

`scripts/gen_cerbos_policies.py` turns this table into the Cerbos policies in `infra/cerbos/policies/` (CI fails if
they drift), and `backend/tests/test_cerbos_parity.py` compares both engines on 6,480 decisions against a running Cerbos.

### Not enforced yet (needs other modules)

| Check | Needed from | Until then |
|---|---|---|
| Committee members see only cases assigned to them | Person 1: assignment data, and `assigned_to` on `ResourceRef` (contract change C3) | `AUTHZ_REQUIRE_ASSIGNMENT=true` (forced on in production) refuses committee access to applications and deadlines outright. In development it is off, so committee members see all cases for the demo. |
| Stage-based actions (e.g. only act on a case in SCRUTINY) | Person 1: current stage passed in the resource (contract change) | Not checked by policy; Person 1's service checks the state |
| Regional officer: application list and single application | Person 1: filter `GET /applications` by `principal.region` and pass `region=` in `ResourceRef` for single reads | Refused for regional officers (safe, but they cannot use those two endpoints) |
| Regional officer: deadline list | Person 2: filter `GET /deadlines` by region and pass `region=` | Refused for regional officers |

## Running the real stack locally

```bash
cp .env.security.example .env.security
docker compose --env-file .env.security --profile security --profile worker up --build
python scripts/smoke_security.py              # 13 end-to-end checks with real tokens and Cerbos
```

Demo accounts and their password are listed in `infra/keycloak/README.md` (LOCAL DEMO ONLY).

The browser uses Authorization Code + PKCE (S256) with the public `awoc-ui` client. There is no client secret in
the frontend.

- The **access token is kept in memory only**; it is never written to browser storage.
- `sessionStorage` (cleared when the tab closes) holds only the refresh token, which Keycloak rotates on every use
  (`revokeRefreshToken`), and the ID token needed for logout. After a reload the session resumes through the refresh token.
- Any 401 from the API, or a refused refresh, ends the session and returns to the sign-in screen.
- Sign-out clears local state and ends the Keycloak session (`end_session_endpoint` with `id_token_hint`).
- An XSS bug could still use the session while the page is open, and could read the refresh token, as with any
  browser-held token. Removing that needs a server-side session (backend-for-frontend), which is not built.

## Response headers

Every `/api/` response carries `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy:
no-referrer`, `Cross-Origin-Resource-Policy: same-origin`, `Cache-Control: no-store` and
`Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`, plus HSTS when `APP_ENV=production`
(`platform/http_security.py`). The built UI's own CSP must be set by whatever serves it, for example
`default-src 'self'; connect-src 'self' <issuer origin>; frame-ancestors 'none'`. The Vite dev server is not
hardened and is for local use only.

With `DEMO_AUTH` on, the API logs a warning at startup.
