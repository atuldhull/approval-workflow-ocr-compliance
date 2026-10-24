# Integration matrix (Person 3 view)

State of every point where Person 3's platform meets the other modules, checked against the code on `person-3`
and the remote branches on 2026-10-24, second check after sprint P3-13..18 (`origin/main` and `origin/person-2`
unchanged since the scaffold; `origin/person-1` added documents and an agent-rules file only, no code or API).

| State | Meaning |
|---|---|
| **Integrated** | Works end to end and is covered by tests |
| **Platform ready** | Person 3's side is built and tested; the other side has not connected yet |
| **Waiting P1 / P2** | Cannot progress until Person 1 / Person 2 builds something |
| **Contract approval** | Needs a `contracts/` change approved by all three |
| **Demo only** | Works, but only with synthetic fixtures or demo settings |

| Area | State | Evidence / what is missing | Details |
|---|---|---|---|
| Application intake and submission (create, submit, route, first clock, ledger) | **Integrated** | `tests/e2e/step01_submit_test.py`, Docker run | - |
| Idempotent create / submit | **Platform ready**, Waiting P1 | Helper and table tested with P1's real service (`backend/tests/test_idempotency.py`); P1's endpoints do not call it yet; UI already sends `Idempotency-Key` | [P1 handoff](PERSON1_FROM_P3.md) #1 |
| Workflow transitions after submission | **Waiting P1** | No transition events exist; dashboards say "stage at submission" and turn PARTIAL if unknown `wf.*` events appear | P1 #4 |
| Role / region permissions | **Integrated** for institution and region scoping | `test_auth.py`, live Cerbos parity, `smoke_security.py` | - |
| Regional officer case and deadline lists | **Waiting P1 / P2** | Refused by policy (safe) until lists filter by region | P1 #2-3, P2 #4 |
| Stage and assignment permissions | **Waiting P1**, Contract approval (C3) | `AUTHZ_REQUIRE_ASSIGNMENT` refuses committee case access in production until then | P1 #5 |
| EVC scheduling | **Waiting P1**, Demo only (preview screen) | No EVC API or events | P1 #6 |
| Deadline status events (met / breached / extended) | **Waiting P2** | Only `dl.deadline_opened` exists; dashboard deadlines section is PARTIAL | P2 #3 |
| Compliance obligations and evidence | **Waiting P2**, Demo only (preview screen) | No API or events | P2 #7 |
| OCR facts and confirmation | **Platform ready (UI)**, Waiting P2, Demo only | Commit-before-reveal and a working all-or-nothing confirm flow through `frontend/src/integrations/documentReview.js`, tested with injected adapters; with the fixture adapter confirm stays disabled | P2 #6 |
| Alert creation and escalation | **Waiting P2** | Not built by P2 | P2 #1-2 |
| Outbox delivery (in-app, email, SMS mock) | **Platform ready** | Worker, retries, dead letters, per-recipient privacy, lease renewal, keyed recipient digests and requeue tested (`test_notifier.py`); checked live with Mailpit; fed only by platform fixtures so far | P2 #1 |
| Recipient groups and vacancy check | **Platform ready**, Contract approval (C2) | `platform/recipients.py`; `RecipientPort` proposed | P2 #2 |
| Alert acknowledgement | **Waiting P2** | Inbox button disabled | P2 #5 |
| Audit events, hash chain, checkpoints | **Integrated** for today's events | `test_audit.py`; local witness is DEMO ONLY | - |
| Replay completeness | **Integrated** for `wf.application_created/submitted`, `dl.deadline_opened` | Verdict is CONSISTENT_SUBSET as soon as other event types are stored; MISMATCH if a stored event cannot be read | P1 #4, P2 #3 |
| Replay and dashboard reads of `wf.application` / `dl.deadline` | **Approval needed** | Read-only SQL today, not yet an approved interface | P1 #7, P2 #7b |
| Frontend: applications, case view, inbox, audit, delivery, scorecard | **Integrated** | `frontend/src/test/app.test.jsx` (25 tests) | - |
| Frontend: document review, EVC, compliance | **Demo only** | Labelled previews; nothing is saved | P1 #6, P2 #6-7 |
| Dashboards | **Integrated** for applications, ageing, alert delivery; PARTIAL for deadlines; NOT_AVAILABLE for workload, EVC, compliance | `test_analytics.py` | P1 #4-6, P2 #3, #7 |
| Scorecard | **Integrated** for ledger, replay, delivery; routing / OCR / alerts NOT_EVALUATED until answer keys exist | `test_analytics.py` | P2 #8 |
| OpenAPI snapshot | **Contract approval** (C1 committed for review; C5 as a patch, verified to apply and to make the check pass) | `docs/proposals/PERSON3_CONTRACT_CHANGES.md` | - |

## Time

The notifier and the idempotency expiry read time from `ClockPort`. In the API process that includes demo time
travel; the separate worker process has its own clock without the offset, so in a time-travel demo, run the worker
with `--once` from the API container if delays must follow simulated time.
