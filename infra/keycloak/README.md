# Local Keycloak realm - DEMO ONLY

`realm-awoc.json` is imported by `docker compose --profile security up`. It exists only for local demos and tests.

- Every account is synthetic and shares the password `demo-only-password`. Never import this realm anywhere real.
- `awoc-ui` is the browser client: public (no secret), Authorization Code + PKCE (S256), redirects to
  http://localhost:5173 only.
- `awoc-smoke` allows the password grant so local smoke tests can fetch a token from a script. It must never
  exist in a real deployment.
- `institution_id` and `region` are user attributes that only an administrator can set; they reach the API
  as access-token claims, together with the `awoc-api` audience.

| Username | Role | Scope |
|---|---|---|
| inst.sunrise | INSTITUTION | Sunrise Institute of Technology (DEMO) |
| inst.northfield | INSTITUTION | Northfield College of Engineering (DEMO) |
| scrutiny | SCRUTINY_COMMITTEE | national |
| ro.southern | RO_OFFICER | Southern region |
| bureau.officer | BUREAU_OFFICER | national |
| bureau.head | BUREAU_HEAD | national |
| auditor | AUDITOR | national |

Keycloak admin console: http://localhost:8081 (`admin` / `demo-only-admin` unless overridden in `.env.security`).
