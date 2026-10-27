# AICTE Approval Operations — local frontend redesign

Implemented in `frontend/`, starting from the Person 3 frontend as it stood before the redesign.

## Brand and design
**AICTE Approval Operations** names the actual work: approval routing, document review, compliance and operational assurance. Subtitle: **Workflow · OCR · Compliance**. Product branding, browser title and source namespace have been updated consistently. The existing official-portal provenance disclaimer is preserved.

The palette retains #5B4632 mocha, #F4D9A0 champagne and #CB792C amber on #141310 ink. Georgia headings pair with locally bundled Hanken Grotesk and JetBrains Mono. Thin brass rules, restrained surfaces, compact record indexes and an adjacent inspector replace oversized repeated visual cards. Institution totals now lead the page. Operational controls remain reachable on desktop and mobile.

Math Collective's actual current local source was studied before coding, including HomePage, HeroExperience, HeroNarrativeOverlay, MathFieldHero and scroll hooks. Its subject-driven compositions, direct CSS-variable updates and preference for lightweight rendering were translated into this product. Its older expensive library scene was not copied. The golden screenshot was visually inspected for warm lighting and contrast.

## Motion and figures
- Short route transitions preserve browser history, deep links, focus and role restrictions.
- Native page scroll changes camera perspective and the inspected record. Manual selections remain pinned until Follow scroll is chosen. Source states never change as a result of scrolling.
- Application dossiers unfold; prescribed route gateways advance in depth; regional spans use supplied counts; audit planes separate continuity, witness and replay; OCR layers use the real supplied page image.
- Officer buckets, inbox/delivery channels, EVC grids and evaluation matrices use lightweight CSS perspective with subject-specific layouts. Compliance folders expose an evidence inset only when evidence exists.
- Desktop scenes sit behind the interface; mobile uses bounded inline scenes. Reduced motion pauses automatic movement. Standard view removes WebGL. Missing/lost WebGL preserves the labelled evidence and controls.
- Scene rendering is event-driven, with no perpetual animation loop. Pixel ratio is capped, hidden/offscreen rendering stops, and GPU resources are disposed. Decorative delivery/workflow loops do not imply unrecorded progression.

See DESIGN.md, MOTION.md and SEMANTIC_MOTION_MAP.md for the complete system and screen map.

## Validation
- **91/91 frontend tests passed**, including authentication, hardening, provenance, operational actions and semantic boundaries.
- **Production build passed.** Main JavaScript is about 79.7 KB gzip; lazy Three.js scene chunk about 130.1 KB gzip. Vite reports its standard >500 KB uncompressed chunk advisory for that lazy chunk; it is not in the initial application bundle.
- **16 route/role variants**, **80 forward/reverse scroll states**, **64 responsive checks** at 390, 768, 1024 and 1920px. No document overflow, source-record mutation or unexpected write requests.
- **Zero axe WCAG A/AA violations** and **zero application exceptions** across the route matrix.
- Reduced-motion checks passed on every variant. All rendered scenes remained idle without input; native scroll moved each spatial scene. All five CSS compositions changed transform on scroll, reversed exactly and remained static with reduced motion.
- **13 interaction checks passed:** pinned selection/case opening, keyboard scene and record controls, history focus, role switching, mobile navigation/Escape, persistent standard mode, lost/no WebGL, sign-in/error rendering, and OCR commit-before-reveal.
- Existing backend on port 8000 was exercised with read-only browser requests. State-changing workflow behaviours remain covered by the source test fixtures. No applications were submitted, notifications sent or backend records changed by browser QA. OCR preview commit is local fixture state only.
- Local production sanity samples: overview heading 348ms / scene 1407ms; inbox heading 209ms / evidence 260ms; audit heading 220ms / scene 530ms. **Zero idle redraws in 700ms samples; zero >50ms main-thread tasks during the measured scroll samples.** These are local observations, not a guarantee for every device.

## Existing limitations kept visible
Regional-officer case listing receives the existing backend 403 and shows its explicit unavailable state. EVC, compliance and document-review previews retain honest sample/API-pending labels and disabled unsupported actions. Audit replay and witness coverage remain distinct from chain continuity. The visual register caps at 24 with a visible disclosure; full operational lists remain below. Lightweight supporting diagrams cap at eight index motifs.

## Scope and dependencies
**168/168 nonfrontend baseline files are byte-for-byte unchanged.** API client, OIDC implementation, document-review adapter, provenance helper, package files and Vite proxy configuration are unchanged. No new dependencies. No Git push, merge, deployment or backend/contract/migration change.

Existing test imports moved with the spatial module namespace; the stored standard-view key changed to `operations.flat`. The former experimental stylesheet layers were replaced by the coherent operations system. The backend target remains the existing default `http://localhost:8000`.

## Changed/new frontend files
- `REDESIGN_REPORT.md`
- `public/approval-mark.svg`
- `DESIGN.md`
- `index.html`
- `MOTION.md`
- `REDESIGN_PLAN.md`
- `SEMANTIC_MOTION_MAP.md`
- `src\App.jsx`
- `src\main.jsx`
- `src\components\CaseDetail.jsx`
- `src\components\Layout.jsx`
- `src\operations\buildEvidenceScene.js`
- `src\operations\operations.css`
- `src\operations\semantic.css`
- `src\operations\semanticData.js`
- `src\operations\World.jsx`
- `src\operations\WorldScene.jsx`
- `src\test\hardening.test.jsx`
- `src\test\operations.test.jsx`
- `src\test\provenance.test.jsx`
- `src\test\semantic.test.js`
- `src\views\ApplicationsView.jsx`
- `src\views\AuditView.jsx`
- `src\views\DashboardView.jsx`
- `src\views\DeliveryView.jsx`
- `src\views\InboxView.jsx`
- `src\views\OcrReviewView.jsx`
- `src\views\OverviewView.jsx`
- `src\views\PreviewViews.jsx`
- `src\views\ScorecardView.jsx`

## Removed or renamed frontend files
- `src\nebula\buildEvidenceScene.js`
- `src\nebula\golden.css`
- `src\nebula\nebula.css`
- `src\nebula\semantic.css`
- `src\nebula\semanticData.js`
- `src\nebula\World.jsx`
- `src\nebula\WorldScene.jsx`
- `src\test\nebula.test.jsx`

## Evidence and local run
Open `http://127.0.0.1:5174/` for the running app and `http://127.0.0.1:5174/review/operations/index.html` for the screenshot gallery. The production preview is at port 5176. To restart the development frontend: `npm run dev -- --host 127.0.0.1 --port 5174 --strictPort` from the frontend folder, with the existing backend running separately.

Evidence: review/operations/{unit-results,browser-results,interaction-results,diagram-motion,performance,validation-summary}.json, build.log, and screenshots. Browser QA scripts reuse the already-installed local Playwright/Axe tooling from the earlier experiment; app dependencies are unchanged.
