# AICTE Approval Operations — design system

**AICTE Approval Operations · Workflow · OCR · Compliance** is an independently built prototype for approval
routing, document review, compliance and operational assurance. It is not the official AICTE portal and is not
connected to it; the case screen says so next to every status, and the top bar always says the data is synthetic.

The workspace is product software, not a landing page. Every screen opens on its working surface: a compact
header (title and one sentence), then figures and controls. Visuals sit beside the controls they explain and never
cover a form or a table.

## Colour roles

Colour encodes hierarchy and meaning. The palette is built from three anchors: charcoal `#171717`, forest
`#06110C` and crimson `#A31C1B`. Token names live in `src/styles.css` (`:root`); the values in use are set by the
product layer in `src/product/` (`product.css`, then `luxury.css`, `atelier.css` and `atmosphere.css`, loaded in that
order from `main.jsx`). The token names are older than the palette, so `--brass` now holds crimson and `--teal`
holds sage.

| Role | Tokens | Value | Used for |
|---|---|---|---|
| Forest / charcoal ink | `--ink-0` … `--ink-4`, `--line`, `--line-strong` | `#06110C` → `#303B32` | Chrome (sidebar, top bar), page, panels, hover, selected rows, hairlines |
| Ivory text | `--text`, `--text-2`, `--text-3` | `#F1F0E8`, `#C0C9BF`, `#A1AFA3` | Primary, secondary and supporting text (`--text-3` keeps ≥ 4.5:1 on panels) |
| Reading paper | `--paper`, `--paper-ink` | `#E9E8DF`, `#232A24` | The document reading surface only |
| Crimson (selection) | `--brass`, `--brass-strong`, `--brass-soft` | `#A31C1B`, `#D44E46` | Selection, the active navigation item, primary buttons, the current stage marker |
| Amber (attention) | `--amber`, `--warn` | `#EFC58B` | Next deadline, "needs you", open obligations, demo-assumption notices |
| Sage (technical relation) | `--teal` | `#A3CBB2` | Hash chain continuity, recorded events, evidence links |
| Info blue | `--info` | `#B3CBE4` | In-process cases, unverified evidence, the replay layer |
| Status | `--ok`, `--warn`, `--bad` | `#A5D1AD`, `#EFC58B`, `#FFAAA0` | Recorded outcomes, always with a word |

Rules: a status is never shown by colour alone (badges carry a dot and a word); green appears only for a recorded
positive outcome; amber is not used for decoration; crimson marks what the user selected or should press, never a
result.

## Atmosphere

Each screen sits on a quiet forest field with one soft light and a faint line drawing taken from the screen's
subject (`src/product/Atmosphere.jsx`, `atmosphere.css`). The layer is `aria-hidden`, has `pointer-events: none`
and never covers a control. The Atmosphere select beside the page title offers Auto, Full, Reduced and Static; the
choice is kept in `localStorage` (`awoc.atmosphere`). Under `prefers-reduced-motion` every mode is still.

A few screens add an illustrative instrument above their working surface: the operations pulse on the dashboard,
the route sculpture on a case, the trust trace on Audit and the review protocol on Fact review
(`src/product/Instruments.jsx`, `DossierSculpture.jsx`). They read the same API data as the screen, never run an
action, and never show a stage as done unless the server says so.

## Type

- Georgia — page titles (set large, beside the one-sentence description), section headlines in the instruments,
  the open record's title in an inspector, the case title. Nowhere else.
- Hanken Grotesk (bundled) — interface text: 13.5px body, 12.5px secondary, 11.5px labels. Labels are sentence
  case; there are no tracked uppercase eyebrows.
- JetBrains Mono (bundled) — internal references, hashes, file names, sequence numbers, times on the EVC grid.
- Figures use tabular numerals. Dates are IST calendar dates (`dateIST`) or IST timestamps (`when`); raw ISO strings
  are not shown in working surfaces.

## Space, shape, states

Spacing 4/8/12/16/24/32/48 (`--s1`…`--s7`); panel radius 6px, controls 4px; sidebar 220px (60px rail); top bar
52px. Focus is a 2px light sage ring offset from the surface. Buttons: primary (crimson), secondary (raised forest),
ghost. Touch targets are at least 36px on phones (44px for navigation).

Loading keeps the shape of what is coming (skeleton bars with a fixed minimum height, so content does not jump).
Empty states are a quiet dashed box with an explanation. A 403 reads as a rule ("Not available to your role") with
no retry; other failures offer "Try again". A coded refusal (guard, intake or EVC code) is shown in plain words from
`workflowText.js`; an unknown code reads as words, never as a guess about why.

## Layout patterns

- **KPI row** (`Kpis`): server figures only; a missing figure reads "—"; attention or failure tone only when the
  value is non-zero.
- **List → inspector** (`.split`, `Inspector`): the list or index on the left, the selected record on the right,
  sticky on desktop and stacked on narrow screens. Selecting only inspects; it never changes a record.
- **Evidence workbench** (`.workbench`): the document on an ivory reading surface beside the index (Documents) or
  the review panel (Fact review).
- **Lifecycle strip** (`Lifecycle`): deadline → alert → delivery → inbox → acknowledgement, with the current screen's
  step marked. It explains the pipeline; it never shows progress.
- **Assurance console** (Audit): three independent layer panels, then history and an inspector with the figure.
- **Action list** (`CaseActions`): exactly the `available_actions` the server returns for the signed-in role at the
  case's stage. Enabled actions open an inline form; blocked ones fold under "Not available now (n)", each with its
  guard reason in words. Nothing is offered that the server did not list.
- **Checklist** (`Checklist`): one row per server checklist item with Mandatory/Optional and Provided/Not provided
  badges, a picker of the case's scanned-clean document versions, the DSC confirmation, and a per-item message when
  the server refuses with `MANDATORY_ITEMS_MISSING`. The DEMO ASSUMPTION label from the server is always shown.
- **Workspace blocks** (`.round`, `.committee`): bordered blocks inside the case inspector for deficiency rounds and
  committees; forms inside them use `.action-form` (stacked) or `.inline-form` (one row, wraps on phones).
- **Simulated note** (`.alert.simulated`): amber note on the EVC screen naming the SIMULATED authorised selector
  (stand-in); the APH 1.8(a) selection happens on AICTE's portal.

## Responsive

Designed at 390, 768, 1024, 1440 and 1920 px. Below 1180px, splits and workbenches stack (inspector after the
list, reader before the panel); below 860px the sidebar becomes a top bar with a menu sheet, the session controls
fold behind "Demo session", KPI rows become two columns, the route stepper becomes vertical and tables scroll
inside their panel. No page scrolls horizontally at any of those widths.

## Data rules

1. Applications, routes, deadlines, dashboard counts, pendency, notifications, delivery and audit results come from
   the backend. Route steps are exactly the stages returned for the case.
2. Route position is not proof of completion: earlier stages read "Before current (completion not supplied)".
3. Regions are drawn only when returned: one region is one row. Absent regions are not added.
4. Audit keeps continuity, witness and replay separate; a broken chain is never combined into a stronger claim, and a
   same-machine witness is labelled DEMO ONLY.
5. Fact review keeps type-before-reveal and four-eyes exactly as the server enforces them; the reading surface
   never shows a machine value.
6. EVC scheduling runs on the API (queue, pool, EDF/CP-SAT proposal, publication). Panels are labelled as the
   SIMULATED authorised selector (stand-in); visit length, AM/PM slots and the expert policy are labelled demo
   assumptions. Proposals made in a tab are kept in sessionStorage only because no run listing exists.
7. Next steps on the overview are derived only from recorded facts (draft status, open obligations).
8. Every write the server makes idempotent sends one Idempotency-Key per user action and reuses it on retry; a
   confirmation appears only after the server answers. A server-decided refusal (4xx with a code) starts a fresh key;
   a lost answer, 5xx or "still being processed" keeps it (`actionKey.js`). Case actions also send the case's
   `expected_version`; a version conflict reloads the case and says so.
9. The checklist, its items and the DSC requirement come from the server (`/applications/{id}/checklist`,
   `/rulesets/{key}/checklists/{category}`); the client keeps no checklist of its own. The deficiency item and reason
   vocabulary is mirrored from the pinned ruleset because no endpoint publishes it yet.

See `MOTION.md` for motion and rendering and `SEMANTIC_MOTION_MAP.md` for what each figure encodes.
