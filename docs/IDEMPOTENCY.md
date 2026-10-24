# Idempotent commands

A client that retries a request (timeout, double click, flaky network) must not create a second application or
submit twice. Mutating endpoints accept an `Idempotency-Key` header; the platform guarantees the command runs at
most once per key.

## Behaviour (`backend/app/platform/idempotency.py`, table `plat.idempotency_key`)

| Situation | Response |
|---|---|
| First request with a key | Runs the command; stores the response **in the same transaction** |
| Same key, same request, after it completed | The original status and body, header `Idempotent-Replayed: true`, nothing runs |
| Same key, different body or path parameters | 422 |
| Same key while the first is still running | Waits for it, then replays; after 5 s, 409 (retry shortly) |
| The command failed (any error) | Nothing is stored; retrying with the same key runs it again |
| Key older than `IDEMPOTENCY_TTL_HOURS` (24) | Treated as new |
| No header | Runs normally (no protection) |

Keys are scoped per user, HTTP method and route template, so two users cannot collide. Keys are stored only as
SHA-256 hashes; no headers or tokens are stored. The notifier worker purges expired rows.

**Why it is safe:** the key row is inserted at the start of the command's unit of work and the response written
at its end, then everything commits together. A crash before commit loses both; a crash after commit keeps both.
A concurrent duplicate blocks on the primary key until the first transaction finishes.

Tested in `backend/tests/test_idempotency.py` with Person 1's real `create_application` service and the real ledger:
identical retry, changed request, two concurrent requests, restart, failure and rollback, cross-user keys,
expiry, purge, lock timeout, and no duplicate domain events.

## Status

| Part | State |
|---|---|
| Platform mechanism, table, migration, tests | Done (Person 3) |
| UI sends a fresh key per action and reuses it on retry | Done (Person 3) |
| `POST /applications` and `POST /applications/{id}/submit` use it | **Waiting for Person 1** (their files) |
| OpenAPI snapshot gains the `Idempotency-Key` header | Contract change - all three approve |

## Integration patch for Person 1 (`backend/app/intake/api.py`)

```diff
+from app.platform.idempotency import idempotency_key, idempotent_response
@@
 @router.post("/applications", response_model=ApplicationOut, status_code=status.HTTP_201_CREATED)
-def create(body: ApplicationIn, principal: Principal = Depends(current_principal)):
-    with unit_of_work(principal) as uow:
-        return _out(service.create_application(uow, body.institution_id, body.category, body.academic_year))
+def create(body: ApplicationIn, principal: Principal = Depends(current_principal),
+           key: str | None = Depends(idempotency_key)):
+    return idempotent_response(
+        principal, key, "POST", "/applications", {}, body.model_dump(mode="json"),
+        lambda uow: service.create_application(uow, body.institution_id, body.category, body.academic_year),
+        lambda a: _out(a).model_dump(mode="json"), status_code=201)
@@
 @router.post("/applications/{application_id}/submit", response_model=ApplicationOut)
-def submit(application_id: UUID, principal: Principal = Depends(current_principal)):
-    with unit_of_work(principal) as uow:
-        return _out(service.submit_application(uow, application_id))
+def submit(application_id: UUID, principal: Principal = Depends(current_principal),
+           key: str | None = Depends(idempotency_key)):
+    return idempotent_response(
+        principal, key, "POST", "/applications/{application_id}/submit", {"application_id": str(application_id)}, None,
+        lambda uow: service.submit_application(uow, application_id),
+        lambda a: _out(a).model_dump(mode="json"))
```

Every future transition endpoint should follow the same pattern. After applying it, run
`python scripts/check_contracts.py --write` and include the refreshed `contracts/openapi.json` in the pull request.

Note on `submit`: a second submit **without** a key still gets 409 from the service (already submitted); with the
same key it replays the original 200, which is what a retrying client needs.
