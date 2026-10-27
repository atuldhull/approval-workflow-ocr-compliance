# Showcase report

A public, backend-free walk-through of **AICTE Approval Operations** (Workflow · OCR · Compliance), an independent SIH
2026 prototype for PS 26262. It is not the AICTE portal, is not connected to it, issues no approvals and holds no AICTE
records; the page says so in its top bar and footer. Art direction and reference study: `SHOWCASE_REFERENCE.md`.

## How to reach it

- `#showcase` — top of the walk-through. `#showcase/<chapter>` for `challenge`, `route`, `evidence`, `deadlines`,
  `audit`, `workspace`. `#showcase/tour/<n>` opens the guided tour, paused, at step *n*.
- From the app: **How it works ↗** in the workspace top bar, on the sign-in card and on the "Connection interrupted"
  card (so it is reachable when the API is down).
- Every other fragment still goes to the workspace. `ShowcaseGate` (`src/showcase/entry.jsx`) only swaps what is
  rendered for `#showcase…` fragments; the workspace's own routing, deep links (`#applications?case=…`), history and
  scroll restoration are untouched. Leaving the showcase pushes a history entry, so Back returns to it, and focus
  lands on the workspace's content region once it has mounted.
- Skippable: a skip link ("Skip to the workspace") and an **Open workspace** button are always in the top bar.

## What was built

| Chapter | What it shows | Rendering |
|---|---|---|
| Hero | "Every approval has a path. Every decision needs evidence." A procedural institutional file opens, its sheets lift into reviewable layers with fields framed for checking, a brass route with five milestones extends, then time ticks, responsible-role plates, a deadline flag and document-to-milestone threads appear | One WebGL canvas (Three.js, lazy). SVG figure for standard view / no WebGL / while loading |
| 01 The Challenge | 22 categories, 4 route shapes, 3 kinds of clock, 6 roles (all counted from the rule set and role list), and the four questions the product answers | HTML |
| 02 A Route for Every Application | Category picker (4 quick picks + all 22). Route drawn from the embedded snapshot of `routes.yaml`: isometric stage plinths, dashed conditional SHC only where the route has it, EC and Council only for a new institution, deficiency loop only where there is a scrutiny stage, evidence and clock markers. Stage panel: purpose, evidence, responsible actor (only where the rule set names one), and built / preview / illustrative. Previous/Next and a stage index; manual selection pins until **Follow scroll**. **Inspect a real case** goes to `#applications` | SVG, scroll-selected stage |
| 03 Documents into Evidence | Original document → your reading (typed and committed first) → machine-proposed reading (sealed until you commit) → confirmed fact (needs a second officer). Interactive, all local state | HTML |
| 04 Deadlines and Responsibility | One illustrative case on a 45-day axis: the 30-day internal processing clock pauses at a deficiency, the institution's 15-day clock runs and stops at its response, processing resumes with its due date moved by the 8 held days. Cards for AICTE_PROCESSING, INSTITUTION_RESPONSE and APPEAL_7D (clause 2.24(a), never paused, reminder only). Obligation → alert → delivery → acknowledgement, and the standard ladder (L0–L3) | SVG + HTML |
| 05 Trust Through Audit | Progressive by scroll: one event → a chain → hash links (real SHA-256 of the shown canonical text, computed in the browser) → signed checkpoint over #41–#44 with the demo witness labelled → replay table (recorded vs rebuilt) → the three layers tilted together as one structure, with what each can and cannot show | HTML/CSS 3D, scroll steps |
| 06 Enter the Workspace | The real screens, built vs preview (EVC), Open workspace / Inspect a case | HTML |

**Guided tour** (`Tour.jsx`): 8 steps, 17 s each while playing (≈ 2 min 16 s). Start, Next, Previous, Pause/Resume,
jump-to-step, step indicator with a progress strip, Exit (button or Escape), ←/→ inside the bar, no focus trap, no
audio. Each step scrolls to its place and focuses that chapter's heading. Auto-advance is a single timeout per step
and runs only while playing; the last step's button is **Enter workspace**, and when playing through, the tour ends by
entering the workspace. Deep link `#showcase/tour/<n>` opens paused. The tour never calls the API (tested).

## Semantic truth table

Every animated or drawn element, and what it represents. Nothing moves without scroll or a click.

| Element | Represents | Does not represent |
|---|---|---|
| Closed file, printed cover | One application, as filed | A real application or AICTE file (cover says SAMPLE-0000, not an AICTE file number) |
| Cover swinging open | The application being opened for review | Any decision |
| Section dividers (Part B, Part D) | Sections of an application bundle | Specific APH sections |
| Sheets lifting into a fan | Documents becoming separately reviewable items | Verified documents |
| Amber frames on printed fields | Fields a person must read and confirm | A machine verdict or an error |
| Brass rail extending | The prescribed route for the illustrative category (New programme) | Progress of a real case |
| Stone plinths | Route stages (Submitted, Scrutiny, Expert visit, Outcome recorded) | Completed stages |
| Hollow brass ring (SHC) | A stage the rule set marks "as applicable" | A stage every case passes |
| Milestone captions | Built / preview / conditional status in this prototype | Official status |
| Teal role plates | Who the rule set makes responsible (only where it names one; "Not named in rule set" otherwise) | Assigned individuals |
| Tick marks | Elapsed time along the route | Real dates |
| Amber flag at Scrutiny | The 30-day internal processing clock (demo assumption) | An AICTE deadline |
| Teal threads | Which document a milestone relies on (checklist → submitted; land and building → scrutiny) | Automatic linking or approval |
| Light pool moving to the route | Attention moving from the file to its route | — |
| Journey: raised champagne plinth | The stage being inspected | The case's current stage |
| Journey: solid vs dashed segments | Prescribed vs conditional path | Recorded transitions |
| Journey: amber dotted loop | Deficiency → institution response → re-scrutiny (rule set transitions) | That every case is deficient |
| Journey: doc / clock glyphs | Evidence handled in the workspace / a clock that runs here | — |
| Evidence: sealed card | The machine reading exists but is withheld until your entry is committed | Hidden data you can't get |
| Deadlines: bars, dashed gap | Running clock, paused clock, unused allowance | Real cases |
| Audit: cards appearing, teal links | Events in sequence, each carrying the previous event's hash | That the events are true |
| Audit: brass plate | A signed checkpoint over #41–#44, copied to a witness | A legal or digital signature on an approval |
| Audit: amber outline on #45 | An entry after the checkpoint, covered by the chain only | A broken record |
| Audit: teal table | Read models rebuilt from events vs those stored | Anything the events do not describe |
| Tour progress strip | Position in the tour | Workflow progress |

## Engineering notes

- **One canvas, on demand.** `HeroCanvas.jsx` renders only when the target progress changes; a damped catch-up loop
  runs until the pose settles, then stops. At rest nothing is drawn. Pixel ratio is capped at 1.75 (1.5 portrait).
  `IntersectionObserver` and `visibilitychange` suspend it; WebGL context loss falls back to the SVG figure. On unmount
  every texture, geometry, material, the PMREM target and the renderer are disposed and the context is released.
  Shaders are compiled (`compileAsync`) before the first frame and the canvas fades in when ready.
- **Pure function of progress.** `scene.js` poses everything from `p ∈ [0, 1]`, so reverse scroll restores each frame.
- **Shared Three.js.** The showcase imports the same `three@0.170.0`; Vite now emits it as one shared chunk used by
  both the workspace scenes and the showcase. No second copy, no new dependency.
- **Native scroll only.** No wheel or touch interception. Sticky stages with passive scroll listeners write `--p` once
  per frame; React state changes at step boundaries only.
- **Procedural assets.** Geometry is built in code; textures are drawn on canvas (forms, cover, board fibre, divider
  cards, labels, contact shadow). Nothing is downloaded. Labels shrink to fit their plates.
- **Compositions per layout.** Wide screens: file right of the copy, route across the desk. Portrait (phones and
  portrait tablets): file below the copy, route laid toward the viewer, smaller textures and shadow map. Wide frames
  narrower than the design aspect pull the camera back.
- **Reduced motion** (OS setting or the app's Pause animations switch): one composed 3D frame (pose 0.78), the hero's
  story as static text beneath it, every journey stage and audit layer shown at once, no transitions.
- **Standard view / no WebGL:** SVG dossier figure with the same content (sheets, frames, milestones, roles, time,
  thread). The choice is remembered (`showcase.flat`).
- **CSP.** Built CSS and JS only; React style props and `style.setProperty` go through CSSOM, which `style-src 'self'`
  allows; canvases are drawn in memory; no inline scripts, no injected `<style>`, no remote fonts or images.

## Changes outside `src/showcase/`

Kept minimal for merging:

- `src/main.jsx`: wraps `<App />` in `<ShowcaseGate>` (stylesheet imports unchanged).
- `src/App.jsx`: one import, and `<ShowcaseLink />` in three places (top bar identity slot, sign-in card, connection
  error card). No other behaviour changed.
- `src/test/showcase.test.jsx`: new tests.

## Tests and build

- **136 / 136 tests pass** (121 existing, unchanged, + 15 new in `showcase.test.jsx`): fragment recognition and parsing;
  showcase renders with zero requests; workspace deep links still reach the app and its config request; round trip
  workspace → showcase → Back; standard view without WebGL; reduced-motion static frames; motion path when allowed;
  chapter deep link focuses its heading; route shapes for self-disclosure, New programme and New institution; stage
  panel and manual selection; commit-before-reveal with zero requests; audit wording; tour Next/Previous/Pause/jump/
  Escape; auto-advance only while playing; paused deep-linked tour; full tour sends no non-GET request and ends in the
  workspace.
- `npm run build` passes.

## Measurements

Local, headless Chromium (software WebGL), production build served by `vite preview` on port 5212 with the nginx CSP
header added to the HTML response. Local sanity checks, not guarantees for every device.

| Check | Result |
|---|---|
| CSP violations (whole page, scrolled top to bottom) | 0 |
| Console errors / warnings, page errors | 0 / 0 / 0 |
| Requests during the showcase | GET only; 0 to `/api/` |
| Idle redraws at rest (3 s) and after scrolling (2 s) | 0 and 0 |
| Frames drawn during a 40-step wheel scroll through the hero and back | ≈ 250 (only while moving) |
| Long tasks during that scroll | 0 (before shader precompile: one of 313 ms) |
| Long tasks on load | 2 (≈ 540 ms and ≈ 510 ms; before replacing per-speck grain drawing: 636 ms and 1,571 ms) |
| Reverse scroll | pose 1.000 → 0.000, scrollY back to 0 |
| Horizontal overflow at 390 / 768 / 1024 / 1440 / 1920 | 0 px at all |
| Keyboard | Logical tab order through skip link, brand, chapters, actions, hero buttons, view toggle, category picks, stage index, controls, evidence input, workspace buttons; every stop visible |
| Landmarks | banner header, `Chapters` nav, main, one h1, labelled sections, contentinfo footer |

Chunk sizes (minified / gzip):

| Chunk | Baseline | Now |
|---|---|---|
| Main JS `index-*.js` | 287.80 / 91.01 kB | 289.50 / 91.55 kB (+1.7 / +0.5 kB: the gate and link) |
| Main CSS | 62.80 / 14.44 kB | 63.21 / 14.55 kB |
| Three.js | inside `WorldScene` 504.68 / 130.13 kB | shared `three.module` 503.67 / 128.40 kB; `WorldScene` 7.50 / 3.44 kB |
| `Showcase` JS / CSS (lazy) | — | 50.65 / 16.60 kB · 29.61 / 6.92 kB |
| `HeroCanvas` (lazy, WebGL only) | — | 21.01 / 9.18 kB |

Accessibility: `@axe-core/playwright` (or axe-core) is not installed in this repository and no new dependency was
added, so no automated axe run was made. Checks done by hand: keyboard order and visibility (above), landmarks and
heading outline, `aria-pressed` on toggles, `aria-current` on the chapter index and audit steps, live regions for the
stage panel, machine reading and tour step, SVG figures with `<title>`, canvas `aria-hidden`, focus moved to headings
on navigation. Text colours on ink: stone `#c5bba9` and dim `#a39882` are both above 6:1.

## Screenshots

Saved outside the repository (a few later ones are committed under `docs/screenshots/`):

- Before: `before-root-1440.png`, `before-root-390.png` (API down, connection screen).
- Hero 1440×900 at 0/25/50/75/100 % of the hero: `hero-final1440-{0,25,50,75,100}.png` (iterations `hero-w1440*`).
- Hero 390×844: `hero-prod390-{0,25,50,75,100}.png`, contact sheet `contact-prod390.png`.
- Other sizes: `hero-768x1024-{0,85}.png`, `hero-1024x768-{0,85}.png`, `hero-1920x1080-{0,85}.png`.
- Chapters 1440: `ch-w1440b-*.png` (challenge, route at 0 and 60 %, evidence, deadlines, audit at 0/50/99 %, workspace).
- Reduced motion: `reduced-1440-hero.png`, `reduced-1440-audit.png`. No WebGL: `nowebgl-1440-hero.png`,
  `nowebgl-1440-hero-70.png`.
- App chrome link: `workspace-chrome-link-1440.png` (API mocked read-only in the browser).

## Dependencies

None added.

## Limitations

- Route data is a snapshot of `routes.yaml` embedded in the bundle; if the rule set changes, `src/showcase/data.js`
  must be updated by hand (the workspace itself reads the live rule set).
- Stage "built / preview / illustrative" labels and named actors reflect this repository on 27 Oct 2026 (EVC scheduling
  is a preview; SHC, EC and Council have no dedicated tooling; actors are named only where `routes.yaml` names them).
- The SVG fallback is a faithful but simpler drawing; it does not animate the cover opening.
- Load still has two main-thread tasks of about half a second each in headless software WebGL (bundle evaluation,
  scene build and texture upload). Real GPUs should do better, but low-end phones were not measured.
- The 3D labels are canvas text on planes; at 390 px the smallest captions on the final overview frame are small,
  though the same information is in the chapters below.
- The tour's step timing is fixed (17 s); it is not adapted to reading speed.
- No automated axe run (tool not available); accessibility was checked by hand.
- In the workspace top bar the link wraps under the role switcher at 1440 px because the identity slot wraps; styling
  that slot belongs to the workspace's own stylesheet.
