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
they drift), and `backend/tests/test_cerbos_parity.py` compares both engines on 14,040 decisions (6 principals,
30 actions, 13 kinds, 6 record shapes) against a running Cerbos. `backend/tests/test_role_matrix.py` pins the HTTP
status every role gets from every endpoint, and passes unchanged with `AUTHZ_ENGINE=cerbos` (checked 27 Oct 2026 on
Cerbos 0.40.0).

### Documents, compliance and alerts (Person 2's endpoints)

The policy decides who may try; the module then applies its own rules, which the matrix pins as well.

| Endpoint | Allowed by policy | Then, in the module |
|---|---|---|
| `POST /applications/{id}/documents` | the owning institution (`document.upload`) | `Idempotency-Key` required; refused before any byte is stored |
| `GET /applications/{id}/documents`, `GET /document-versions/{id}/facts` | officers in scope, auditor, the owning institution | institutions see confirmed values only, never OCR proposals |
| `GET /documents` | the same; a regional officer always gets their own region, another region is 403 | |
| `POST /document-versions/{id}/scan` | the owning institution (rescan of its own upload) | a version that already has a verdict is returned unchanged |
| `POST /document-versions/{id}/extract`, `/document-facts/{id}/entry`, `/reveal`, `/review` | committee and regional officer in scope (`document.fact.review`) | only a clean version is extracted; the suggestion is shown only to the officer who typed first; that officer must finish the review |
| `POST /document-facts/{id}/confirm` | any officer in scope (`document.fact.confirm`) | four-eyes: the reviewer gets 409; the database refuses such a row too |
| `POST /compliance/letters` | bureau officer and head | one LoA / EoA per case and year |
| `GET /compliance/letters`, `/obligations` (lists and single) | officers in scope, auditor, the owning institution | lists are filtered to the caller's scope |
| `POST /compliance/obligations/{id}/evidence` | the owning institution | only a scanner-approved version of the same case |
| `POST /compliance/evidence/{id}/verify` | officers in scope | never an automated actor (also a database constraint) |
| `GET /alerts` | officers, auditor, institutions | institution: its own alerts; committee: alerts addressed to the committee; regional officer: own region (a `region` filter is replaced, not refused) |
| `POST /alerts/{id}/ack` | officers and institutions in scope | only the role the alert is addressed to (others 403) |
| `POST /sim/clock`, `POST /sim/timers/run` | everyone, only with `DEMO_MODE=true` | demo controls; refused to all roles otherwise |

### Not enforced yet (needs other modules)

| Check | Needed from | Until then |
|---|---|---|
| Committee members see only cases assigned to them | Person 1: assignment data, and `assigned_to` on `ResourceRef` (contract change C3) | `AUTHZ_REQUIRE_ASSIGNMENT=true` (forced on in production) refuses committee access to applications and deadlines outright. In development it is off, so committee members see all cases for the demo. |
| Stage-based actions (e.g. only act on a case in SCRUTINY) | Person 1: current stage passed in the resource (contract change) | Not checked by policy; Person 1's service checks the state |
| Regional officer: application list and single application | Person 1: filter `GET /applications` by `principal.region` and pass `region=` in `ResourceRef` for single reads | Refused for regional officers (safe, but they cannot use those two endpoints) |
| Regional officer: deadline list and explanation | Person 2: filter `GET /deadlines` by region and pass `region=` (also in `GET /deadlines/{id}/explain`) | Refused for regional officers, even for their own region's deadlines |

## Running the real stack locally

```bash
cp .env.security.example .env.security
docker compose --env-file .env.security --profile security --profile worker --profile scanning up --build
python scripts/smoke_security.py              # 36 end-to-end checks with real tokens and Cerbos
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
(`platform/http_security.py`). The one response that is not JSON, `GET /api/document-versions/{id}/content` (a
version scanned clean), sets its own `Cache-Control: private, no-store` and `Content-Security-Policy: default-src
'none'; sandbox`, an inline `Content-Disposition` with a sanitised file name, and keeps the other headers. The
Vite dev server is not hardened and is for local use only.

The built UI is served by the production image in `frontend/Dockerfile` (unprivileged nginx, config in
`frontend/nginx/default.conf.template`):

- CSP `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; font-src 'self';
  connect-src 'self' <OIDC_ORIGIN>; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'`,
  with no `unsafe-inline` or `unsafe-eval`. This is the main defence for the refresh token in `sessionStorage`.
- `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, and a `Permissions-Policy`.
- The page itself is `no-store`; hashed assets are cached for a year; `/api/` is proxied and never cached.
- Viewing a document: the Documents and Fact review screens fetch `/api/document-versions/{id}/content` with the
  user's own headers (demo headers or the bearer token), accept only `application/pdf`, `image/png` and
  `image/jpeg` (anything else is refused and never turned into a URL), rebuild the Blob with that type, and open
  it as a `blob:` URL in a new tab with `opener` cleared. If the browser blocks the tab, a download link is
  offered instead. Each URL is revoked a minute after opening, and any still held when the screen closes are
  revoked then. The UI CSP needs no change for this: a `blob:` document inherits the page's policy, `img-src`
  already allows `blob:`, and Chromium's PDF viewer renders the file with `object-src 'none'` in force (checked
  against the policy above on 27 Oct 2026). The only effect is cosmetic: the browser's own image viewer cannot apply
  its inline centring styles under `style-src 'self'`. The Vite dev server sends no CSP.
- Settings: `API_UPSTREAM` (where `/api` goes) and `OIDC_ORIGIN` (the identity provider the browser may call).
- It serves plain HTTP on 8080. TLS, HSTS for the UI, and the real host names and Keycloak redirect URIs belong
  to the deployment in front of it and have not been set up.

## Frontend dependency advisories (25 Oct 2026)

`npm audit --omit=dev` reports nothing. `npm audit` reports six advisories, all in development and test tooling
that is not in the built bundle or the production image:

| Package | Severity | Where it runs | Reachable here? |
|---|---|---|---|
| vite 5.4 (direct) | high | Vite dev server | Only on the developer's machine; the server is published on 127.0.0.1 only |
| esbuild (via vite) | moderate | Vite dev server | Same |
| vitest 2.1 (direct), @vitest/mocker, vite-node | critical / moderate | Test runner | Only when tests run; the Vitest UI server is not used |
| tinypool (via vitest) | critical | Test runner workers | Needs attacker-controlled worker options; tests run our own code only |

Every fix needs a major upgrade (Vite 5 → 6.4.4 or later, Vitest 2 → 4.1.11 or later, with `@vitejs/plugin-react`).
Planned as one change after team integration, with the full test and browser suites. Do not use
`npm audit fix --force`.

With `DEMO_AUTH` on, the API logs a warning at startup.
