# Integration matrix (Person 3 view)

State of every point where Person 3's platform meets the other modules, checked against the code on `person-3`
and the remote branches on 2026-10-24, second check after sprint P3-13..18 (`origin/main` and `origin/person-2`
unchanged since the scaffold; `origin/person-1` added documents and a rules file only, no code or API).
Re-checked for sprint P3-19..24: still no new published interface from Persons 1 or 2, so no adapter changed.
Updated 27 Oct 2026 on `p3/finish` (Person 2's finished backend + Person 3's platform and screens): the Person 2 rows
below now describe what runs.

| State | Meaning |
|---|---|
| **Integrated** | Works end to end and is covered by tests |
| **Platform ready** | Person 3's side is built and tested; the other side has not connected yet |
| **Waiting P1 / P2** | Cannot progress until Person 1 / Person 2 builds something |
| **Contract approval** | Needs a `contracts/` change approved by all three |
| **Demo only** | Works, but only with synthetic fixtures or demo settings |

| Area | State | Evidence / what is missing | Details |
|---|---|---|---|
| Application intake and submission (create, submit, route, first clock, ledger) | **Integrated** | `tests/e2e/step01_submit_test.py`, `scripts/smoke_demo.py` (52 checks on the Docker stack, 27 Oct 2026) | - |
| Idempotent create / submit | **Platform ready**, Waiting P1 | Helper and table tested with P1's real service (`backend/tests/test_idempotency.py`); P1's endpoints do not call it yet; UI already sends `Idempotency-Key` | [P1 handoff](PERSON1_FROM_P3.md) #1 |
| Workflow transitions after submission | **Waiting P1** | No transition events exist; dashboards say "stage at submission" and turn PARTIAL if unknown `wf.*` events appear | P1 #4 |
| Role / region permissions | **Integrated** for institution and region scoping | `test_auth.py`, `test_role_matrix.py` (role x endpoint table), live Cerbos parity, `smoke_security.py` | P1 #8 (institution list) |
| Regional officer case and deadline lists | **Waiting P1 / P2** | Refused by policy (safe) until lists filter by region; deadline explain is refused too | P1 #2-3, P2 #4 |
| Stage and assignment permissions | **Waiting P1**, Contract approval (C3) | `AUTHZ_REQUIRE_ASSIGNMENT` refuses committee case access in production until then | P1 #5 |
| EVC scheduling | **Waiting P1**, Demo only (preview screen) | No EVC API or events | P1 #6 |
| Deadline status events (met / breached / extended) | **Waiting P2** | Only `dl.deadline_opened` exists; dashboard deadlines section is PARTIAL | P2 #3 |
| Compliance letters, obligations and evidence | **Integrated** | `test_compliance.py`, role matrix rows, `smoke_demo.py` (LoA from a confirmed fact, evidence, verification); compliance screen | P2 #7 |
| Documents: upload, scan, extraction, review, four-eyes | **Integrated** | `test_documents_*.py`, role matrix rows, `smoke_demo.py` with real ClamAV and the local text engine in Docker; documents and fact review screens | P2 #6 |
| Alert creation and escalation | **Integrated** for application deadlines | Timer worker in compose, `test_deadline_timer.py`, `smoke_demo.py`; obligation and letter deadlines never alert (scope lookup) | P2 status note |
| Outbox delivery (in-app, email, SMS mock) | **Platform ready** | Worker, retries, dead letters, per-recipient privacy, lease renewal, keyed recipient digests and requeue tested (`test_notifier.py`); checked live with Mailpit; fed only by platform fixtures so far | P2 #1 |
| Recipient groups and vacancy check | **Platform ready**, Contract approval (C2) | `platform/recipients.py`; `RecipientPort` proposed | P2 #2 |
| Alert acknowledgement | **Integrated** | Alerts screen; addressed role only (role matrix) | P2 #5 |
| Audit events, hash chain, checkpoints | **Integrated** for today's events | `test_audit.py`; local witness is DEMO ONLY | - |
| Replay completeness | **Integrated** for `wf.application_created/submitted`, `dl.deadline_opened` | Verdict is CONSISTENT_SUBSET as soon as other event types are stored; MISMATCH if a stored event cannot be read | P1 #4, P2 #3 |
| Replay and dashboard reads of `wf.application` / `dl.deadline` | **Approval needed** | Read-only SQL today, not yet an approved interface | P1 #7, P2 #7b |
| Frontend: applications, case view, inbox, audit, delivery, scorecard | **Integrated** | `frontend/src/test/app.test.jsx` (25 tests) | - |
| Frontend: documents, fact review, compliance, alerts | **Integrated** | Real API screens, `frontend/src/test/*.test.jsx`; EVC stays a labelled preview | P1 #6 |
| Dashboards | **Integrated** for applications, ageing, alert delivery; PARTIAL for deadlines; NOT_AVAILABLE for workload, EVC, compliance | `test_analytics.py` (incl. region changes, concurrency, 300 synthetic applications), `scripts/smoke_demo.py` | P1 #4-6, P2 #3, #7 |
| Scorecard | **Integrated** for ledger, replay, delivery, alert timeliness, document scanning, four-eyes, OCR agreement; routing NOT_EVALUATED until P1's answer key | `test_scorecard.py`, `test_analytics.py`, `smoke_demo.py` | P1 answer key |
| OpenAPI snapshot | **Contract approval** (C1 committed for review; C5 as a patch, verified to apply and to make the check pass) | `docs/proposals/PERSON3_CONTRACT_CHANGES.md` | - |

## Time

The notifier, the deadline timer worker and the idempotency expiry read time from `ClockPort`. In demo mode the
time-travel offset is stored in `dl.sim_clock` and re-read at most once a second, so separate worker processes
follow simulated time as well; outside demo mode the stored offset is ignored.
