# Design system — Approval Workflow

An operations product for AICTE approvals: institutions file, officers scrutinise, the bureau oversees,
auditors verify. People work in it for long sessions, so legibility and honest data come first; the
atmosphere (depth, light, motion) sits behind the work, never on top of it.

## The idea

**The approval route is the product's own object.** Every application travels a route of stages
(self-disclosure, scrutiny, expert visit, hearing, council). The mark, the case journey, the institution's
workflow path and the empty states are all drawn from that route: nodes joined by a line. Nothing here
could belong to another product.

## Decisions against the design skill's app defaults (and their limits)

The house style for app screens (design-taste-frontend, `references/app-screens.md`) bans navy dark
themes, glow, glass and entrance motion. This brief asks for a midnight base, depth and motion. The
owner's brief wins on atmosphere; the skill wins on substance:

| Brief asks for | Kept as | Limit |
|---|---|---|
| Midnight / slate base | A near-neutral midnight (`#0b0f16`), not saturated navy | Text tiers all reach 4.5:1 |
| Glow | A soft light behind the page's one hero element and focus rings | Never on cards, text or buttons at rest |
| Glass | None. Opaque surfaces one tone step apart | — |
| Entrance motion | One staggered reveal per section, once | Content is never hidden without JavaScript or with reduced motion |
| 3D | Four scenes, each carrying real data | Every scene has a 2D/text fallback |

Kept from the skill without exception: colour on data and status only, one primary action per screen,
tabular right-aligned numbers, no icons in tinted circles, no sparklines, no invented figures, sentence-case
labels, zeros shown as zeros and missing values as a dash.

## Tokens (`src/styles.css`, `:root`)

| Role | Value | Use |
|---|---|---|
| `--ground` | `#0b0f16` | Page and sidebar (one ground, divided by a 1px line) |
| `--surface` | `#121823` | Panels |
| `--raised` | `#18202d` | Hover, wells, nested panels |
| `--active` | `#1f2938` | Selected nav item and selected rows |
| `--border` / `--rule` / `--control` | `#232d3b` / `#1a2230` / `#3a4658` | Panel edge / row rule / control edge |
| `--text` / `--muted` / `--faint` | `#edf2f8` / `#a9b4c3` / `#8f9aaa` | Three text tiers, each ≥ 4.5:1 on `--surface` |
| `--accent` | `#35d0c0` | The one data hue: the current stage, the main series, focus |
| `--signal` | `#7cb4ff` | Links and informational marks only |
| `--positive` / `--negative` / `--warning` | `#43c47f` / `#f06b7c` / `#f2b552` | Status only, as text or as the pale pill pair |

**Worlds.** Each screen sets `--world` (a hue) used only by its backplate light and its title rule:
control room teal, cases cyan, signal blue, traffic blue-grey, integrity ice, evidence warm paper,
field green, board neutral. Data colour never changes between worlds.

## Type

- **Hanken Grotesk** (variable, bundled locally) for everything; **JetBrains Mono** only for IDs, hashes
  and codes.
- Scale: 12 / 14 / 16 / 20 / 28 px; one display size of 40 px only for a case's reference on its journey.
  Weights 400 / 500 / 650.
- Tabular figures on every number that is compared or updates.
- Sentence case; no tracked uppercase labels.

## Space and layout

- 4px base; gaps 16 (inside panels) and 24 (between panels); panel padding 20; section gap 40.
- Shell: 248px sidebar, collapsible to a 72px rail; content fluid with 32px gutters (16px on phones),
  max 1360px.
- Below 860px the sidebar folds to a 56px top bar with a menu sheet; nothing scrolls sideways.

## Surfaces, radius, elevation

- A 1px border or a tone step separates surfaces, never both. Shadows only on what floats (menu sheet,
  tooltips, the 3D scenes' floating planes).
- Radius: 10 panels, 8 controls, 6 chips, round for status dots. Nested radii step down.

## Status and states

- Pills: pale-on-dark pairs (`--pill-*`), text and dot, never saturated fills with white text.
- Loading: the final layout with flat bars at real size and a slow opacity pulse; no shimmer.
- Empty: the panel keeps its frame and header; one sentence and the route glyph.
- Error: inside the panel that failed, with what failed and a Try again for retryable errors.
- Forbidden (403): a calm locked panel stating the rule that refused it; no retry.
- Preview (backend not built): a labelled band and disabled actions that say why.

## Iconography

Line icons drawn inline at 16px, 1.5px stroke, in `--muted`; never in coloured containers.
