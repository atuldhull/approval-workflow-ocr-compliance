# Requests to Person 1 from Person 3

These are requests, not changes: nothing in Person 1's folders has been edited. Each item lists what exists today,
what is needed, and how we will both know it works. Items marked **contract** need all three approvals.

## 1. Use the idempotency helper on create and submit

- **Exists:** `app.platform.idempotency.idempotency_key` (FastAPI dependency) and `idempotent_response(...)`;
  tested with your real `service.create_application` in `backend/tests/test_idempotency.py`. The UI already sends
  `Idempotency-Key`.
- **Needed:** the patch in `docs/IDEMPOTENCY.md` applied to `backend/app/intake/api.py` (`create`, `submit`), and the
  same pattern on every future transition endpoint.
- **In / out:** header `Idempotency-Key` (8-128 chars `[A-Za-z0-9_\-:.]`), optional. Replays return the original
  status and body with `Idempotent-Replayed: true`; the same key with a different body is 422; a concurrent duplicate waits,
  then replays (409 after 5 s).
- **Security:** keys are scoped per user; the command must run inside the `uow` the helper passes in, not a new one.
- **Acceptance:** posting the same create twice with one key returns the same id and stores one
  `wf.application_created` event; a different body with that key is 422.
- **Contract:** yes, for the OpenAPI snapshot (C4) once applied.

## 2. Region filtering on the application list

- **Exists:** `GET /applications` filters for institutions only and checks `ResourceRef("application")`.
- **Needed:** for `RO_OFFICER`, filter by the institution's `ro_region == principal.region` and check
  `ResourceRef("application", region=principal.region)`.
- **Security:** the policy refuses regional officers today *because* the list is unfiltered; do not pass `region=`
  without filtering.
- **Acceptance:** a Southern officer sees Southern applications only; a request with no region stays 403.
- **Contract:** no.

## 3. Region on single-application reads

- **Needed:** `GET /applications/{id}` passes `region=` (from `CasePort.lookup`) in its `ResourceRef`.
- **Acceptance:** Southern officer 200 on a Southern case, 403 on a Northern case. **Contract:** no.

## 4. Events for the rest of the workflow

- **Needed:** schemas and events for stage transitions, deficiency raised / answered, decisions (and withdrawals),
  e.g. `wf.stage_changed`, `wf.deficiency_raised`, `wf.decision_recorded`; ids, enums and dates only (no free text,
  which goes in `case_note`).
- **Then either** extend `backend/app/analytics/projections.py::ApplicationsProjection` with me, or register your own
  projector from `workflow/wiring.py` with `app.platform.replay.register(...)`.
- **Acceptance:** after a transition, `POST /api/audit/replay` stays `VERIFIED_COMPLETE` and the dashboard's stage
  counts move.
- **Contract:** yes (new event schemas).

## 5. Stage and assignment for permissions

- **Needed:** committee assignment data (who is assigned to which case) and, once contract change **C3** is approved,
  `stage=` and `assigned_to=` in every case-level `ResourceRef`.
- **Security:** until then `AUTHZ_REQUIRE_ASSIGNMENT` (on in production) refuses committee members all application and
  deadline access, rather than guessing.
- **Acceptance:** a committee member can open an assigned case and gets 403 on an unassigned one, with the guard on.
- **Contract:** yes (C3).

## 6. EVC scheduling API and events

- **Needed:** `GET` of proposed slots per request (request id, institution, slot, expert count, conflicts) and an
  approve action, plus events for request / slot / assignment.
- **Then:** the EVC preview screen (`frontend/src/views/PreviewViews.jsx`) switches to it, and the dashboard's EVC
  queue section becomes available. **Contract:** yes (OpenAPI and event schemas).

## 7. A read-only view for replay and dashboards

- **Exists today (disclosed):** `ApplicationsProjection.live()` in `backend/app/analytics/projections.py` runs a
  read-only `SELECT id, institution_id, category, academic_year, status, current_stage, ruleset_rev FROM
  wf.application` to compare replayed state with yours. It never writes, but it depends on your table layout.
- **Needed:** either approve that query as a stable read-only interface, or provide a view (e.g.
  `wf.v_application_status` with those columns) or a port method; I will switch to it.
- **Acceptance:** renaming a `wf.application` column no longer breaks replay. **Contract:** yes, if it is a port.

## 8. Institution list visible to institutions

- **Exists today:** `GET /institutions` returns every institution (name, regional office) to every signed-in role,
  institutions included. Pinned as current behaviour in `backend/tests/test_role_matrix.py` ("institution list").
- **Needed (your decision):** if institutions should not see each other, return only the caller's institution for
  `INSTITUTION` and keep the full list for officers.
- **Acceptance:** an institution user gets exactly one row; officers get all. I will update the matrix row.
  **Contract:** no.
