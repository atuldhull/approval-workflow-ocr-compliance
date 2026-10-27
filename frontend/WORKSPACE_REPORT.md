# Workspace redesign report

Scope: the authenticated workspace of AICTE Approval Operations (`frontend/src/views`, `components`, `operations`,
global styles). Backend, contracts, migrations, policies, rulesets, `main.jsx`, `api.js` and the public showcase are
unchanged. `App.jsx` changed in two lines (no eyebrow above the title; no departure delay on route change).
This document supersedes the validation figures in `REDESIGN_REPORT.md`.

## Diagnosis (before)

Screenshots of every screen for six roles at 1440×900 and 390×844 showed:

1. **One template for every screen.** Each route opened with a "world": an eyebrow, a 47px poetic heading ("Three
   different questions of trust.", "The scope of review."), a scroll-driven 3D or CSS figure and a numbered register
   of the same records — then the real working table repeated underneath. On a 900px screen the first working
   control was below the fold on most screens (audit verification, dashboard sections, compliance table, delivery
   outbox).
2. **Content hidden by motion.** Panels were invisible until an IntersectionObserver revealed them; full-page
   captures of the dashboard showed a blank lower half.
3. **Raw values in the visual layer.** Registers printed `2026-10-27T12:44:21.108054Z`, `deadline.escalated`,
   `NO_TRUSTED_CHECKPOINT · CHAIN_ONLY`, "chain result: true", lower-case category codes.
4. **Monotone brown/gold.** Mocha, champagne and amber were used for surfaces, selection, attention and decoration
   alike, so colour carried no meaning; every label was tracked uppercase mono.
5. **Weak figures.** Extruded brown blocks (dossiers, bars, plinths) overlapped the KPI strip on the overview and
   dominated the dashboard; they encoded little beyond "a record exists".
6. **Mobile.** The session controls took ~220px above every page; 3D scenes pushed content further down.

## Decisions

- Remove the "world" from every working screen. Each screen now opens with a compact header and its working
  surface: KPIs, the list, the inspector, the document.
- One canvas, only where it adds meaning: the audit inspector, as a small companion figure, never a backdrop.
- Colour by role (see `DESIGN.md`): graphite workspace, ivory text and reading paper, brass for selection, amber for
  attention only, teal for technical relations, status colours always with words.
- Overview → detail everywhere: list on the left, inspector on the right, stacked on narrow screens.
- No fabricated data: next steps derive from recorded facts; pendency shows only returned regions and stages; the
  EVC screen stays a labelled preview.

## Per-screen changes

| Screen | Change |
|---|---|
| Shell | 220px graphite sidebar, sentence-case items, brass selection; slim top bar; session controls fold behind "Demo session" on phones; page title 22px Georgia with one-line description |
| Institution overview | KPI row (applications, in process, drafts, next deadline with rule and case, obligations needing evidence); application board with returned route track, status and a next step from recorded facts; due-next list; stage counts; open obligations; intentional empty state with a way in |
| Cases | New-application form as one compact row; case list with status chips, text filter and sort; case inspector with status, provenance (AICTE ids "Not linked"), route stepper of returned stages, deadline axis and clocks with source badges, audit timeline. Create and submit unchanged |
| Documents | Evidence workbench: index (documents → versions → scan state → actions) beside an ivory reading surface showing the clean page image inline; PDFs open via View document (CSP forbids embedded viewers); upload form unchanged |
| Fact review | Version picker; reading surface beside the review panel; review-progress counts; blind entry, reveal, review and four-eyes confirmation untouched |
| Compliance | Due-date axis (one marker per date, obligations stacked, status outline); obligations table with an evidence column; obligation inspector with a who-does-what list, evidence, notes and verification; letters below |
| Alerts | Lifecycle strip; counts (open, escalated, acknowledged, vacant, awaiting your role); escalation ladder per alert; acknowledgement unchanged; toast only after the server answers |
| Inbox | Lifecycle strip; grouped stream beside a notice inspector (mark read also available there) |
| Delivery | Lifecycle strip; state counts with dead letters set apart; outbox table beside an attempts inspector; requeue confirmation unchanged |
| Dashboards | Scope chip ("Southern region only" / "All regions"); KPI row; region × stage pendency matrix from `/dashboards/pendency`; section panels with ordered stage bars and a stated region count; unavailable sections grouped and labelled |
| EVC (preview) | Week grid with sample slots at their IST times, conflicts marked, slot inspector with disabled actions; PREVIEW banner and "Sample" badge throughout |
| Scorecard | Instrument: summary counts, then one row per check reading check → method → found → outcome; derived tones are labelled "from the result"; measurements without a verdict say so |
| Audit | Overall verdict with copy/download; three layer panels (hash chain, trusted checkpoint, replay) each with question, result, limits and its own action; replay result table and gaps; checkpoint history; inspector with the spatial figure and the selected layer's facts |

## Measurements

| | Baseline | After |
|---|---|---|
| Tests | 121 passing | 130 passing (9 new in `src/test/workspace.test.jsx`; 2 World tests rewritten) |
| `npm run build` | passes | passes |
| Main JS | 287.80 kB (91.01 kB gzip) | 302.67 kB (93.72 kB gzip) |
| CSS | 62.80 kB (14.44 kB gzip) | 54.45 kB (11.43 kB gzip) |
| Lazy Three.js chunk | 504.68 kB (130.13 kB gzip) | 472.23 kB (120.01 kB gzip) |
| Canvases per screen | up to 1 on 7 screens | 1, audit only |

Browser checks (Chromium via playwright-cli, local backend on 8051 with synthetic data):

- **axe-core WCAG 2 A/AA** on 31 role/screen combinations: 0 violations (two found and fixed: muted text contrast on
  the selected document version, and the scrollable reading surface not being focusable).
- **Horizontal overflow** at 390, 768, 1024 and 1920 px on the same 31 combinations: none (one found and fixed: an
  off-screen table label escaping its scroll container on compliance at 390px).
- **Console errors**: 0, apart from the expected 403 responses (regional officer case list; bureau officer checkpoint
  read).
- **CSP**: production build served by `vite preview` on 5222 with the nginx policy injected; 12 screens across three
  roles, including the inline document image: 0 `securitypolicyviolation` events, 0 errors.
- **Audit scene**: 2 frames on load, 0 frames over 1.5s idle, 0 frames and 0 long tasks during 40 scroll steps;
  1 canvas.

## Screenshots

- Before: `opsui-shots/before/` — `{1440|390}-{role}-{screen}.png` and `-full.png` (180 files)
- After: `opsui-shots/after/` — same names (180 files)

Roles: sunrise (institution), scrutiny, ro-southern, bureau-officer, bureau-head, auditor. The folders are kept outside the repository; they are not committed.

## Backend gaps met (not worked around)

- No ledger-wide event listing: the audit history shows signed checkpoints and replay projections; individual events
  are only available per case (`/cases/:id/timeline`).
- No per-stage completion or transition events: route steps before the current one stay "before current".
- ~~Regional officers are refused `GET /applications` (403)~~: resolved, their list now comes from `GET /cases?region=`.
- No text extraction engine in the local stack (`extract` returns `ADAPTER_UNAVAILABLE`): fact review shows the empty
  state and the extract action.
- ~~No EVC scheduling API~~: resolved, see the workflow catch-up below.
- The deadline API does not return an "overdue" status for obligations or a calendar version; neither is computed here.

## Remaining weaknesses

- PDFs cannot be read inline under the current CSP (no `frame-src`/`object-src`); the reading surface shows a placard
  and View document opens the file in a tab. Rendering PDF pages to images would need a new dependency or a server
  endpoint.
- The top bar still carries many demo controls at 1440px; below 1560px the breadcrumb is hidden to keep it on one line.
- The overview fetches deadlines per in-process case (capped at 12), as before; a scope-wide deadline endpoint would
  remove the fan-out.
- `LedgerChamber.jsx` and `three/LedgerScene.jsx` remain in the tree (covered by a test) but are no longer rendered.
- Axe and the overflow sweep were run against seeded synthetic data; screens with long real-world lists were not
  load-tested.

## Workflow catch-up (checklist, case actions, committees, EVC)

The screens were built before the workflow, intake and EVC backends landed; this pass connects them.

| Role | Screen | Change |
|---|---|---|
| Institution | New application | Shows the chosen category's checklist from `/rulesets/{key}/checklists/{category}` before the draft exists |
| Institution | Case (draft) | Checklist panel: item states, link a scanned-clean document version per item (`document_ref`), confirm DSC, save or submit; `MANDATORY_ITEMS_MISSING` explained per item |
| Institution | Case (submitted) | Action list (compliance response, withdraw); answer each open deficiency item with one of its documents |
| Institution | Documents | Upload offers the application's own checklist items, then supporting documents; the hard-coded list is gone |
| Scrutiny committee | Case | Action list with guard reasons; committee workspace (form, assign task, observation, report version); record deficiency; re-scrutiny review per item; complete the expert visit |
| Regional officer | Cases | List from `GET /cases?region=` (was refused) |
| Regional officer | EVC scheduling | Queue of its region, panel preview, CP-SAT/EDF proposal, expert pool (register, availability, COI) |
| Bureau officer / head | EVC scheduling | Same, plus publishing or discarding a proposed run from the server-side run list; 409 conflicts in words |
| Bureau officer | Case | Reject, revert and the letter actions; letters read "switched off" while `WF_ENABLE_LETTER_ISSUANCE` is off, and offer a letter form (cited committee report, F. No.) when it is on |
| Auditor | EVC scheduling | Read-only queue and pool |
| Oversight | Scorecard | Routing line shows 22/22 with "Acceptance source unverified", taken from the answer key's own source text |
| Public | Showcase | EVC stage and workspace tile now "Built"; stage notes describe the checklist, guards and the letter flag |

Tests: 177 passing (32 new in `src/test/workflow.test.jsx`, 3 existing tests updated); `npm run build` passes.

Browser walkthrough (Chromium via playwright-cli, local backend, synthetic data): one NEW_PROGRAMME case was driven
end to end from the browser. Draft created; a submit without items was refused with per-item messages; a document was
uploaded, linked and the DSC confirmed; submitted. The scrutiny committee formed its committee, assigned a task, added
an observation and a report, and recorded a deficiency. The institution uploaded and sent its response. Re-scrutiny
was started and the response accepted, which moved the case to the expert visit. The regional officer registered an
expert, set availability and proposed with CP-SAT; the bureau officer published by reference (a second publish showed
the 409 in words). An EVC committee was formed and the visit completed. With `WF_ENABLE_LETTER_ISSUANCE=true` the
bureau officer was refused for citing the scrutiny report (`DECISION_NOT_AUTHORISED`, in words), then issued the LoA
citing the EVC report, and the letter appeared under Compliance. No horizontal overflow at 390 px on the new screens
(one found and fixed: checkboxes stretched to full width). Screenshots are kept outside the repository.

Backend gaps met (reported, not worked around):

- ~~No read of the deficiency item or reason vocabulary~~: resolved, items and reasons come from
  `GET /rulesets/{key}/deficiency-vocabulary` of the case's pinned ruleset; `workflowText.js` keeps only the labels.
- ~~No per-case committee list~~: resolved, `GET /cases/{id}/committees` (the letter form takes each committee's latest report
  from it).
- ~~No list or read of EVC proposal runs~~: resolved, runs come from `GET /evc/schedule/runs` and
  `GET /evc/schedule/runs/{id}` (nothing is kept in the browser); the bureau publishes or discards a proposed run from its detail,
  so publish-by-reference is gone. Unplanned requests show their `explanation_code` in plain words, and the run shows its daily cap,
  slot capacity and CP-SAT candidate window.
- No dry-run or compare endpoint: a second proposal only sees requests the first left queued, so the comparison table
  shows the input fingerprint and says when runs are not comparable.
- ~~No per-case EVC read~~: resolved, the case uses `GET /applications/{id}/evc` and shows the published visit date,
  half-day and panel references.
- ~~Regional officers refused `GET /applications/{id}`~~: resolved server-side (own region only); the case screen reads it for every
  role again. Their list still comes from `GET /cases?region=`.
- No user directory: committee members other than yourself are demo accounts only; expert references are unverified.

Accessibility and CSP check of the changed screens (production build served by `vite preview` with the nginx policy as a
response header, local backend on a fresh synthetic database; axe-core WCAG 2 A/AA run in Chromium):

- EVC scheduling as bureau officer, regional officer (Southern) and auditor; case screen as bureau officer, regional officer,
  scrutiny committee and institution: 0 axe violations and 0 `securitypolicyviolation` events after two fixes.
- Fixed: muted text on the selected run row and on the selected application row fell below 4.5:1 (`.table tr.current .muted`,
  `.row.active .row-sub`).
- Fixed: after switching demo identity the run list briefly kept the previous identity's rows, so a regional officer opened the
  bureau's all-region run and got a 403. The list now remounts per identity and only opens the newest run once it has loaded.
- Remaining console error: the existing 403 on `GET /applications` for regional officers (their list comes from
  `GET /cases?region=`), as before.
