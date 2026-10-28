# AICTE Approval Operations — Workflow · OCR · Compliance

**SIH 2026 · Problem Statement 26262: Integrated Approval Workflow Automation, Compliance Monitoring and Alert
Management · AICTE (Regulation Bureau) · Theme: Smart Education · Team ASTRAL**

[![ci](https://github.com/atuldhull/approval-workflow-ocr-compliance/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/atuldhull/approval-workflow-ocr-compliance/actions/workflows/ci.yml)

| Team member | Area |
|---|---|
| Person 1 | Intake, workflow engine, deficiency and re-scrutiny, committees, approval letters, EVC queue, expert pool and scheduling |
| Person 2 | Documents, OCR and fact confirmation, compliance obligations, deadlines, alerts and timers |
| Person 3 | Platform (sign-in and Cerbos policies, idempotency, audit ledger and replay, notifier, analytics and scorecard), the whole frontend, infrastructure |

> **Independent prototype.** This is a student project built for Smart India Hackathon 2026. It is **not** the
> official AICTE portal, is not connected to it, and uses **synthetic data only**: every institution, account,
> expert and document in the demo is fictional and marked DEMO.

## Problem and solution

AICTE approvals follow the Approval Process Handbook (APH): each kind of application goes through its own sequence of
scrutiny, expert visits and committees, with deficiencies sent back to the institution, response windows, letters and
post-approval conditions. Where a case stands, which deadlines apply to it and what evidence backs each decision are
hard to see in one place, and missed deadlines are found late.

This prototype runs the whole approval in one system. Each application is routed by a versioned APH ruleset pinned at
submission; scrutiny, deficiency and re-scrutiny rounds, committees and expert visits (EVC) are commands with guards
and permissions; uploaded documents are malware-scanned and read by OCR, but a fact only counts after an officer has
entered it blind and a second officer has confirmed it; approval letters open compliance obligations; every clock
raises an alert ladder (reminder, breach, escalation) delivered in-app and by email; and every state change is
written to a hash-chained, signed and replayable audit ledger.

## Screenshots

| | |
|---|---|
| ![Bureau head dashboard with the operations pulse and the alert queue](docs/screenshots/dashboard.png) | ![Public showcase opening on the application dossier](docs/screenshots/showcase.png) |
| Dashboard: stage counts rebuilt from the audit event log, a case route to inspect, alerts that need the role | Showcase at `#showcase`: a guided walk-through of the product that ends in the workspace |
| ![Scrutiny committee recording a deficiency on a case](docs/screenshots/scrutiny-deficiency.png) | ![Regional officer planning expert visits with the CP-SAT optimiser](docs/screenshots/evc-scheduling.png) |
| Case under scrutiny: the prescribed route, deficiency round, committee workspace, demo-assumption labels | EVC scheduling: visit requests, CP-SAT or earliest-deadline-first planning, simulated panel selection |
| ![Fact review with blind entry before the OCR reading is revealed](docs/screenshots/fact-review-blind-entry.png) | ![Deadline alerts with escalation levels and acknowledgement](docs/screenshots/deadline-alerts.png) |
| Fact review: the officer types the value first; the OCR reading is revealed only after that | Alerts: escalation ladder per deadline, acknowledgement by the addressed role |
| ![Audit view: hash chain, signed checkpoint and replay](docs/screenshots/audit.png) | ![Scorecard listing how each check was measured](docs/screenshots/scorecard.png) |
| Audit: hash chain, signed checkpoint held by a witness, replay of read models | Scorecard: each check says how it was measured and what it found |

All screenshots come from the end-to-end run described under [Tests](#tests) and show synthetic data. The
background atmosphere can be set to Auto, Full, Reduced or Static from the control at the top of each screen, and
stays still when the system asks for reduced motion.

## Problem statement coverage

Each row is something PS 26262 asks for. "How to verify" points at a screen in the running app, an API endpoint
(all under `http://localhost:8000/api`; interactive docs at `http://localhost:8000/docs`) or a test file.

| PS requirement | What we built | Module | How to verify |
|---|---|---|---|
| Approval workflow automation, APH-routed | 22 routes (the 21 APH Table 2.3 categories plus new institution) in a versioned ruleset; the route is pinned at submission; transitions are data, not code | `backend/app/intake`, `backend/app/workflow`, `rulesets/aph-2024-27/r1/routes.yaml` | `GET /api/rulesets`; screen **Cases**; `backend/tests/test_transition_grammar.py`, `backend/tests/test_routing_answer_key.py`, `tests/e2e/step01_submit_test.py` |
| Intake checks before submission | Per-category checklist and DSC confirmation; submit is refused with per-item reasons | `backend/app/intake` | `GET /api/applications/{id}/checklist`; `backend/tests/test_intake_checklists.py`, `backend/tests/test_checklist_read.py` |
| Scrutiny, deficiency and re-scrutiny | Committees with tasks, observations and versioned reports; a deficiency pauses the processing clock and opens the response window; re-scrutiny reviews only the open items | `backend/app/workflow` | `POST /api/cases/{id}/actions`, `GET /api/cases/{id}/deficiencies`; `backend/tests/test_deficiency_loop.py`, `backend/tests/test_rescrutiny.py`, `backend/tests/test_committee.py` |
| Expert visit (EVC) scheduling | Visit queue, expert pool with availability and conflicts of interest, simulated panel selector, earliest-deadline-first baseline and CP-SAT optimiser, propose / discard / publish | `backend/app/evc` | screen **EVC scheduling**; `POST /api/evc/schedule:propose`, `POST /api/evc/schedule:publish`; `backend/tests/test_scheduler_cpsat.py`, `backend/tests/test_scheduler_edf.py`, `backend/tests/test_evc_decisions.py` |
| "Only EVC" routes (A1) | Random inspection of an existing institution (APH cl. 2.3.5(a), p.31) and the EVC on a verified complaint (cl. 7.10, p.89): the case starts at the expert visit and its request is queued on submission; each route can carry its own EVC timeline (the new institution route uses `EVC_NEW_INSTITUTION`) | `backend/app/workflow`, `rulesets/aph-2024-27/r1/routes.yaml` | screen **EVC scheduling**; `GET /api/applications/{id}/evc`; `backend/tests/test_appeal.py`, `backend/tests/test_routing_answer_key.py` |
| Case summary (A4) | One read of a case: route and clause, stage history, committees and reports, deficiency rounds, EVC visit, letters, obligations, clocks and the appeal; a printable view | `backend/app/workflow` | case screen (Case summary, then Print); `GET /api/cases/{id}/summary`; `backend/tests/test_appeal.py` |
| Appeal to the SAC and Letter of Rejection | An LoD opens the 7-day appeal window (APH cl. 1.11(a), p.25; cl. 2.24(a), p.45); the institution may appeal once; the Standing Appellate Committee recommends, does not recommend or refers the case back for Scrutiny or EVC; the bureau head records the Council's final decision: LoA / EoA, or a Letter of Rejection that must carry a speaking order (cl. 1.10(b)). An unappealed window lapses and the LoD stands | `backend/app/workflow` | case screen (Appeal panel); `GET /api/cases/{id}/appeal`, `POST /api/cases/{id}/actions` (`file_appeal`, `sac_recommend`, `issue_lor`); `backend/tests/test_appeal.py` |
| Approval letters | LoA / EoA / LoD only at the last applicable stage and only when the cited report authorises the decision; issued from the case screen in the demo stack | `backend/app/workflow`, `backend/app/compliance` | `GET /api/compliance/letters`; `backend/tests/test_guard_facts_runtime.py`, `backend/tests/test_compliance.py` |
| Document upload and malware scan | Idempotent upload, versions, ClamAV scan; nothing is used before it is scanned clean | `backend/app/documents` | screen **Documents**; `POST /api/document-versions/{id}/scan`; `backend/tests/test_documents_api.py` |
| OCR with human confirmation | PDF text layer or Tesseract (English and Hindi); blind entry before the OCR value is revealed; review; four-eyes confirmation by a second officer | `backend/app/documents` | screen **Fact review**; `POST /api/document-facts/{id}/entry`, `POST /api/document-facts/{id}/reveal`; `backend/tests/test_documents_ocr.py`, `backend/tests/test_documents_review.py` |
| Compliance monitoring: obligations and evidence | An LoA opens the security deposit and Affidavit 3 (15 days, APH cl. 2.25(f)) and the remaining requirements (one month, Affidavit 3 item 5); institutions submit evidence; an officer verifies it | `backend/app/compliance` | screen **Compliance**; `GET /api/compliance/obligations`, `POST /api/compliance/evidence/{id}/verify`; `backend/tests/test_compliance.py`, `backend/tests/test_compliance_rules.py` |
| Time-bound undertakings (D1–D4) | An officer records an undertaking with its clause, what it asks, the evidence that meets it and the due date it states (or a recordable rule such as the 7-day no-admission affidavit); it gets a clock, reminders and escalation like any obligation | `backend/app/compliance` | screen **Compliance** (Record undertaking); `POST /api/compliance/obligations`; `backend/tests/test_document_validity.py`, `backend/tests/test_compliance.py` |
| Lease and document validity (E1–E4) | Land lease, occupancy/completion, structural stability and fire safety certificates (APH cl. 6.17): the expiry is confirmed from the document (four-eyes) or recorded by an officer; advance reminders (90/30/7 days), an expiry ladder to the regional officer, bureau officer and bureau head; a renewal is a new version offered as evidence and accepted by an officer; the lease also shows its EoA stop year (cl. 2.1(e)) | `backend/app/compliance`, `backend/app/documents`, `backend/app/deadlines` | screen **Compliance** (Document validity); `POST /api/compliance/validity`, `GET /api/compliance/obligations?kind=DOCUMENT_VALIDITY`; `backend/tests/test_document_validity.py`, `backend/tests/test_deadline_lease.py` |
| Deadlines with escalation | Rule-based due dates with explanations (calendar days, month-end clamp, Indian working-day calendars, due on a stated date); per-rule reminders; a timer worker (in the default stack) marks missed clocks breached and raises reminder, breach, escalation and vacancy levels; every open, pause, resume, close and breach is an event in the ledger | `backend/app/deadlines`, `calendars/` | screen **Alerts**; `GET /api/deadlines/{id}/explain`, `POST /api/sim/timers/run`; `backend/tests/test_deadline_timer.py`, `backend/tests/test_deadline_service.py`, `backend/tests/test_deadline_calendars.py` |
| Alert management and notifications | Each alert is addressed to one role and acknowledged by it; messages also go out when something is recorded on a case (deficiency, EVC visit published, evidence decided, letter issued, deadline missed), naming the case, the rule and the due date, configured in `notifications.yaml`; delivery in-app, by email (SMTP) and mock SMS, with retries, dead letters and delivery metrics | `backend/app/platform` (notifier), `backend/app/deadlines` | screens **Inbox**, **Alerts**, **Alert delivery**; Mailpit at `http://localhost:8025`; `POST /api/alerts/{id}/ack`; `backend/tests/test_notifier.py`, `backend/tests/test_event_notifications.py` |
| Role- and region-based access | Keycloak (OIDC with PKCE) or demo sign-in; Cerbos or the local policy engine decides every request; institutions see only their own records, regional officers only their region | `backend/app/platform`, `infra/` | `python scripts/smoke_security.py`; `backend/tests/test_role_matrix.py`, `backend/tests/test_cerbos_parity.py`, `backend/tests/test_auth.py` |
| Tamper-evident audit | Hash-chained ledger of every state change, Ed25519-signed checkpoints held by a witness, read-only replay that rebuilds read models from the events | `backend/app/platform` | screen **Audit**; `GET /api/audit/verify`, `POST /api/audit/replay`; `backend/tests/test_ledger.py`, `backend/tests/test_audit.py` |
| Safe retries | `Idempotency-Key` on commands: a retried request returns the first result instead of acting twice | `backend/app/platform` | `backend/tests/test_idempotency.py`, `backend/tests/test_p1_idempotency.py` |
| Consolidated reports (F3) | Pendency, EVC status, undertaking compliance, document validity, overdue cases and region-wise processing performance, each with a CSV download, all rebuilt from the event log | `backend/app/analytics` | screen **Reports**; `GET /api/reports`, `GET /api/reports/{report_type}`; `backend/tests/test_reports.py` |
| Analytics and scorecard | Dashboard built from events: applications by stage, ageing, deadlines, committee workload, EVC queue, compliance and document validity, alerts by region; a scorecard of eight checks, each stating how it was measured; OCEL export of the event log | `backend/app/analytics` | screens **Dashboard**, **Scorecard**; `GET /api/analytics/scorecard`, `GET /api/dashboards/pendency`, `POST /api/exports`; `backend/tests/test_scorecard.py`, `backend/tests/test_analytics.py`, `backend/tests/test_reports.py` |

Where each timer, route and rule comes from (APH clause and page, or demo assumption):
[docs/RULES_EVIDENCE.md](docs/RULES_EVIDENCE.md).

## Architecture

A FastAPI + PostgreSQL modular monolith: one process, one database, one schema and one owner per module. Modules call
each other only through the ports in `contracts/ports.py`, inside the caller's transaction, so a transition, its
deadlines, its ledger events and its outbox rows commit together or not at all. Details:
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

```mermaid
flowchart LR
    UI["React UI (Vite :5173 or nginx :8088)"] -->|"/api"| API
    KC["Keycloak (OIDC, PKCE)"] -.->|sign-in| UI
    subgraph API["FastAPI app :8000"]
        direction TB
        intake & workflow & evc
        documents & compliance & deadlines
        platform & analytics
    end
    API --> DB[("PostgreSQL 16<br/>wf · evc · doc · cmp · dl · plat · an")]
    API -->|policy decisions| CB["Cerbos"]
    API -->|token keys| KC
    documents -->|scan| AV["ClamAV"]
    documents -->|OCR| TS["Tesseract eng + hin"]
    NW["notifier worker"] --> DB
    NW -->|SMTP| MP["Mailpit (demo mail sink)"]
    DW["deadline timer worker"] --> DB
    platform -->|signed checkpoints| WT["audit witness (file)"]
```

The default stack runs the database, backend, UI and deadline timer worker, with demo sign-in and the built-in policy
engine. Keycloak, Cerbos, Mailpit, ClamAV and the notification worker are optional Compose profiles.

## Approval workflow

Stages and actions as defined in [`rulesets/aph-2024-27/r1/routes.yaml`](rulesets/aph-2024-27/r1/routes.yaml). Each
category uses a subset of the stages (for example `CHANGE_OF_NAME` is Scrutiny only; `NEW_PROGRAMME` is Scrutiny, EVC
and SHC as applicable; `NEW_INSTITUTION` adds EC and Council). The "letter" box is the bureau officer's decision action
at the last applicable stage, not a stage of its own.

```mermaid
stateDiagram-v2
    [*] --> DRAFT
    DRAFT --> SELF_DISCLOSURE: submit (EoA self-disclosure, NRI seats)
    DRAFT --> SCRUTINY: submit (all other routes)
    DRAFT --> EVC: submit (Only EVC: random inspection, complaint)
    SCRUTINY --> DEFICIENT: record_deficiency
    DEFICIENT --> RESCRUTINY: submit_compliance
    RESCRUTINY --> RESCRUTINY: start_rescrutiny
    RESCRUTINY --> DEFICIENT: record_deficiency
    SCRUTINY --> EVC: advance_to_evc
    RESCRUTINY --> EVC: advance_to_evc
    EVC --> SHC: complete_evc (SHC as applicable)
    EVC --> EC: complete_evc (new institution)
    SHC --> EC: advance (new institution)
    EC --> COUNCIL: advance
    state "letter at last applicable stage" as LETTER
    SELF_DISCLOSURE --> LETTER
    SCRUTINY --> LETTER
    RESCRUTINY --> LETTER
    EVC --> LETTER
    SHC --> LETTER
    COUNCIL --> LETTER
    LETTER --> APPROVED: issue_loa / issue_eoa
    LETTER --> APPEAL_WINDOW: issue_lod (7 days)
    APPEAL_WINDOW --> SAC: file_appeal (once)
    APPEAL_WINDOW --> REJECTED: close_appeal_window (lapsed)
    SAC --> SAC: sac_recommend / sac_not_recommend
    SAC --> SCRUTINY: sac_refer_scrutiny
    SAC --> EVC: sac_refer_evc
    SAC --> APPROVED: issue_loa / issue_eoa (Council)
    SAC --> REJECTED: issue_lor + speaking order (Council)
    APPROVED --> [*]
    REJECTED --> [*]
    WITHDRAWN --> [*]
```

From any active stage the bureau officer can also `reject` (to REJECTED) or `revert` (to a stage visited before), and
the institution can `withdraw` (to WITHDRAWN). Submitting opens the processing clock; a deficiency pauses it and opens
the institution's response window; the compliance response closes the window and resumes the clock.

## Run it

Needs Docker Desktop (or Docker Engine with Compose v2). The default stack uses ports 5173, 8000 and 5432 (set
`DB_PORT=5433` in `.env` if 5432 is taken); the optional profiles add 3310, 8081, 3592, 8025 and 8088. Everything
binds to 127.0.0.1 only.

```bash
cp .env.example .env
docker compose --profile worker --profile scanning up --build
```

On start the backend applies the migrations and seeds the demo data, dated from the demo clock, so every screen has
work without manual setup (the first start takes about half a minute longer; later starts add nothing):

- the demo institutions and the notification directory;
- fourteen demo cases driven through the case API: two under scrutiny with their processing clock overdue, one fresh
  under scrutiny, one deficient awaiting the institution's reply, two in the EVC queue with visit requests for the
  planner, one random inspection (an "Only EVC" route) queued for its visit, one with its EVC visit published, one at
  SHC, one with an LoD issued three days ago and its appeal window open, one whose appeal was filed and waits at the
  SAC, and three approved with an LoA issued from the case (one of them 20 days ago, so its deposit and Affidavit 3
  are overdue and escalating);
- on the approved cases: a land lease expiring in 60 days, a lease that expired 12 days ago (breached, escalating), a
  fire safety certificate with its renewal under review, a structural stability certificate, and a recorded
  undertaking.

The seeds can be rerun at any time (`docker compose exec backend python -m app.workflow.demo_seed`, then
`python -m app.compliance.demo_seed`). For a larger expert pool for the planner:

```bash
docker compose exec backend python -m generator.cases.seed_evc_demo --at 2026-10-28T04:30:00Z   # use today's date (UTC)
```

- UI: http://localhost:5173 (public walk-through of the product at http://localhost:5173/#showcase)
- API docs: http://localhost:8000/docs

ClamAV downloads its signatures on first start, which takes a few minutes; until then uploads stay `scan_pending`.
`docker compose up --build` without profiles starts the database, backend, UI and deadline timer worker.

**Demo sign-in (default).** The top bar has an "Acting as" switcher with these synthetic roles: Institution
(Sunrise), Institution (Northfield), Scrutiny committee, Regional officer Southern, Regional officer Northern, Bureau
officer, Bureau head and Auditor. The same bar shows `DEMO SIGN-IN`, `Synthetic data` and `SIMULATED TIME`, with
`+7 days`, `+30 days` and `Run timers now` for time travel. The Atmosphere control beside each page title and
"Pause animations" in the sidebar turn the background effects and transitions down or off.

**Real sign-in (optional).** Keycloak, Cerbos and Mailpit (captured demo email at http://localhost:8025), with the
eight matching demo accounts listed in [infra/keycloak/README.md](infra/keycloak/README.md):

```bash
cp .env.security.example .env.security
docker compose --env-file .env.security --profile security --profile worker --profile scanning up --build
```

**Letters.** The demo stack issues approval letters from the case screen (`WF_ENABLE_LETTER_ISSUANCE` is set in
`docker-compose.yml`; the code default stays off). The request is in
[docs/p1/contract_requests/2026-10-26_letter_issuance.md](docs/p1/contract_requests/2026-10-26_letter_issuance.md).

The production UI image (nginx) runs with `docker compose --profile web up --build web` on :8088. Signed audit
checkpoints are set up as described in [docs/AUDIT.md](docs/AUDIT.md).

<details>
<summary>Backend without Docker</summary>

Needs Python 3.12 and a PostgreSQL database.

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows   (macOS/Linux: source .venv/bin/activate)
pip install -r backend/requirements-dev.txt
set DATABASE_URL=postgresql+psycopg://awoc:awoc@localhost:5432/awoc     # export on macOS/Linux
alembic -c backend/alembic.ini upgrade heads
python generator/cases/seed_demo.py
python -m app.platform.demo_seed && python -m app.workflow.demo_seed && python -m app.compliance.demo_seed   # DEMO_MODE=true
uvicorn app.main:app --app-dir backend --reload
```

Frontend: `cd frontend && npm install && npm run dev`
</details>

## Walkthrough

The path the end-to-end run drove through the UI (all profiles on, letter issuance on):

1. **Institution (Sunrise):** create a draft for *New programme*. Submit is refused with the missing checklist items;
   upload the PDF under My documents (ClamAV: clean), link it, confirm DSC, submit. The case moves to Scrutiny.
2. **Scrutiny committee:** form the scrutiny committee, assign a task, add an observation, save report v1 and record a
   deficiency on the core reference document. The case moves to Deficiency reply.
3. **Institution:** upload a new version and send the compliance response. The case moves to Re-scrutiny.
4. **Scrutiny committee:** start re-scrutiny and accept the response. The round closes and the case goes to the expert
   visit; an EVC request is queued.
5. **Regional officer Southern:** preview the simulated panel and propose an earliest-deadline-first schedule; the
   **bureau officer** discards it; the regional officer proposes again with CP-SAT; the **bureau head** publishes it.
   The case shows the published visit.
6. **Scrutiny committee:** form the EVC committee, save the EVC report and complete the expert visit.
7. **Bureau officer:** issue the Letter of Approval. Citing the scrutiny report is refused with a reason; citing the
   EVC report issues the LoA. The case is Approved and two obligations appear under Compliance.
8. **Institution** uploads a scanned letter; **scrutiny** extracts it with Tesseract, types the value blind, reveals
   the OCR reading and reviews it; the same officer is told it cannot also confirm; **Regional officer Southern**
   confirms it.
9. **Institution** submits a deposit receipt as evidence; the **regional officer** accepts it; the obligation is Met.
10. **Bureau head:** `+30 days`, then `Run timers now`. Alerts escalate; the regional officer acknowledges one; the
    Inbox and Mailpit show the notices.
11. **Audit:** the chain verifies, a checkpoint is signed and published to the witness, replay runs, and the
    Scorecard evaluates all eight checks.
12. **Appeal (seeded case `LOD-APPEAL-OPEN`):** the **institution (Riverbend)** sees the LoD with the days left in
    the appeal window and files the appeal with its grounds; the case moves to SAC. The **scrutiny committee** forms
    the SAC committee, saves its report and recommends. The **bureau head** records the Council's decision; a Letter
    of Rejection is refused without a speaking order. The case summary prints the whole history.
13. **Bureau head:** the **Reports** screen shows pendency, EVC status, undertakings, document validity, overdue
    cases and region-wise performance, each downloadable as CSV.

`python scripts/smoke_demo.py --docker` checks the same ground through the API on the default stack. It moves the
demo clock forward, so run it on a stack whose data you do not need.

## Tests

Covered: every workflow transition and guard; all 22 routes against an independent routing answer key; deficiency
and re-scrutiny rounds; EVC scheduling (EDF and CP-SAT) and publication; document scanning, OCR, blind entry and
four-eyes rules; compliance obligations; deadline calculation and timers; alert delivery with retries; the status every
role gets from every endpoint (local engine and Cerbos); ledger tampering (edited and deleted events); replay;
idempotent retries; and the scorecard. `tests/e2e/` runs the demo-script steps against a real database.

```bash
python -m pytest                          # backend; needs a disposable PostgreSQL database, see below
python scripts/check_contracts.py         # shared contracts valid and up to date
python scripts/check_migration_heads.py   # one migration head per module
python scripts/gen_cerbos_policies.py --check
node --test .github/scripts/contract-approval.test.js
cd frontend && npm test && npm run build
```

The test fixture drops and recreates a database named `awoc_test`, so it runs only against a local PostgreSQL
(`DATABASE_URL=postgresql+psycopg://awoc:awoc@localhost:5432/awoc_test`) and only with
`AWOC_TEST_DATABASE_DISPOSABLE=1` set. With Cerbos running, set `CERBOS_TEST_URL=http://localhost:3592` to compare both
policy engines decision by decision. CI (`.github/workflows/ci.yml`) runs all of the above on every push and pull
request.

Results at the time of writing (28 October 2026, on this branch):

| Check | Result |
|---|---|
| Backend suite (Python 3.12, PostgreSQL 16) | 7066 passed, 1 skipped (Cerbos parity, run separately) |
| Cerbos 0.40.0 parity and role matrix | 56 passed |
| Frontend unit tests (Vitest) | 191 passed |
| Contract-approval rule tests | 27 passed |
| `smoke_demo.py --docker` (real ClamAV and Tesseract) | 54 / 54 |
| `smoke_security.py` (real Keycloak and Cerbos) | 38 / 38 |
| Browser run, 8 roles at 1440 px and 390 px | 138 page visits, 446 link and history checks, 0 console errors, 0 failed requests |

## Tech stack

- Backend: Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Pydantic 2, PostgreSQL 16
- Scheduling: Google OR-Tools CP-SAT
- Documents: pypdf, Tesseract OCR (English, Hindi), Pillow, ClamAV
- Identity and access: Keycloak 26 (OIDC, PKCE), Cerbos 0.40, PyJWT
- Audit: SHA-256 hash chain, Ed25519-signed checkpoints (cryptography)
- Frontend: React 18, Vite, three.js (showcase and figures), Vitest and Testing Library
- Delivery: Docker Compose, nginx (production UI image), Mailpit (local mail sink), GitHub Actions

## Security and privacy

- The demo switches (`DEMO_AUTH`, `DEMO_MODE`) must be off outside a demo; `APP_ENV=production` refuses to start
  otherwise.
- Every request is authorised by role and scope (own institution, own region), by Cerbos or by the local policy
  engine; parity tests keep the two in step.
- Event payloads carry ids, codes, dates and hashes only; free text and personal data are stored separately and
  referenced.
- All accounts, passwords and keys in `infra/` and the `.env*.example` files are local demo values. Real secrets
  belong in `.env` and `.secrets/`, which are git-ignored.

Details: [docs/SECURITY.md](docs/SECURITY.md), [docs/AUDIT.md](docs/AUDIT.md),
[docs/IDEMPOTENCY.md](docs/IDEMPOTENCY.md).

## Known limitations

- **Internal processing times are demo assumptions.** The APH sets no internal SLAs (Table 2.2 gives every
  category's processing period as "As per Public Notice Period" or "Year round"), so the processing clock, the
  deficiency response window, the EVC visit window, every reminder offset and escalation step, the expert eligibility
  and conflict rules and the scheduling capacity are labelled **DEMO ASSUMPTION** in the YAML and in the UI. The
  post-approval rules (deposit and Affidavit 3 in 15 days, remaining requirements in one month, the no-admission
  affidavit, LoA validity, lease and certificate validity, the appeal window) cite their APH clause and page. Every
  rule and its status: [docs/RULES_EVIDENCE.md](docs/RULES_EVIDENCE.md). Route clause citations are still marked
  `UNCONFIRMED` and the routing answer key is a manual transcription of Table 2.3; see
  [docs/p1/ASSUMPTIONS.md](docs/p1/ASSUMPTIONS.md) and
  [docs/handoffs/APH_CONFORMANCE_PROPOSALS.md](docs/handoffs/APH_CONFORMANCE_PROPOSALS.md).
- **Expert panels are simulated.** A labelled stand-in selector forms panels; under the APH the real selection
  happens on AICTE's own portal.
- **Letter issuance is a switch.** The demo stack turns `WF_ENABLE_LETTER_ISSUANCE` on; the code default stays off.
  Shared-contract changes need all three members' approval ([docs/CONTRACT_APPROVAL.md](docs/CONTRACT_APPROVAL.md));
  the requests are in [docs/p1/contract_requests/](docs/p1/contract_requests/).
- **Seeded files skip ClamAV.** The demo seed scans the synthetic PDFs it builds itself with its own check (recorded as
  scanner `demo_seed`), so the stack needs no ClamAV to start; uploads made in the UI still wait for the real scan.
- **The demo witness is not independent.** Signed checkpoints go to a local file on the same machine.
- **Time travel distorts one figure.** After demo time travel the scorecard's "longest lag" for alerts can show
  thousands of hours for letters dated before their deadline existed; the outcome is still correct.
- Opening an obligation from the Compliance table does not put `?obligation=` in the address (inbound links work).
- OCR is Tesseract (English and Hindi) and has been measured only on synthetic documents.
- Not connected to any AICTE system; what an integration would need is in
  [docs/handoffs/AICTE_INTEGRATION_READINESS.md](docs/handoffs/AICTE_INTEGRATION_READINESS.md).

## Repository layout

```
backend/app/      one package per module (intake, workflow, evc, documents, compliance, deadlines, platform, analytics)
backend/migrations/versions/<module>/   one Alembic chain per module
contracts/        shared ports, enums, event schemas, OpenAPI snapshot (changes need all three members)
rulesets/         versioned APH rules (routes.yaml, deadlines.yaml, checklists.yaml)
calendars/        working-day calendars
generator/        synthetic demo data, scale generator and answer keys
frontend/         React UI and the public showcase
infra/            local Keycloak realm and generated Cerbos policies (demo only)
scripts/          contract, migration and policy checks; smoke tests; audit key generation
tests/e2e/        demo-script steps as end-to-end tests
docs/             architecture, design notes, per-member plans and reports
```

All documentation is indexed in [docs/README.md](docs/README.md); module ownership is in
[docs/OWNERSHIP.md](docs/OWNERSHIP.md).

## Licence

No licence has been chosen yet.
