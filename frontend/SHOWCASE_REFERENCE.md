# Showcase reference study and art direction

The showcase (`#showcase`, source in `src/showcase/`) is a public, backend-free walk-through of AICTE Approval
Operations, an independent SIH 2026 prototype for problem statement 26262. This note records what was studied before
building it, what was taken and what was rejected, and the art direction chosen.

## 1. Math Collective: how it gets impact cheaply

Read locally at `D:\math-collective\frontend\src\features\home\`: `HomePage.jsx`, `HeroExperience.jsx`,
`HeroNarrativeOverlay.jsx`, `MathFieldHero.jsx`, `mathField.js`, and `src/lib/heroSpan.js`. Only technique was
taken; no branding, copy or geometry.

| Technique | Why it works there | Role here | Cost | Supported by existing deps? | Decision |
|---|---|---|---|---|---|
| Scroll and pointer written to CSS custom properties, coalesced into one rAF, no React state per frame (`MathFieldHero`) | Compositor-only transform/opacity, zero reconciliation while scrolling | Every scroll-driven section writes `--p` to its own element (`scroll.js`); React state changes only at step boundaries | Near zero | Yes (plain DOM) | **Reuse** |
| One shared definition of the hero's scroll span (`heroSpan.js`, written after three copies drifted apart) | Overlay, title and figure stay in sync | Progress is measured from the section's own box (`sectionProgress`), so the hero, journey and audit cannot disagree with their CSS heights | Near zero | Yes | **Adapt** (measure the element instead of a token) |
| Discrete narrative bands with setState only when the band index changes (`HeroNarrativeOverlay`) | Each beat lands; no 60 Hz re-render | Hero beats change at fixed progress thresholds that follow the scene's phases | Near zero | Yes | **Reuse** |
| Its own history: a 1,545-line Three.js scene with bloom every frame was replaced because it caused scroll lag | Expensive rendering cost scroll performance | The one WebGL scene here renders on demand only, has no post-processing and stops when settled | n/a | n/a | **Lesson taken**: spend effort on modelling, materials and camera, not on per-frame effects |
| Device tiering at render time (`prefersReducedHero`: width, cores, memory, Save-Data) | The first paint is already the right variant; no flash | Portrait screens get a separate composition (camera keys, route direction, texture size, shadow map size) chosen synchronously | Low | Yes | **Adapt** (by layout, not by core count, so evaluators on any laptop see the same scene) |
| Pause when off-screen via a sentinel and IntersectionObserver; `visibilitychange` | No work for a hidden hero | `IntersectionObserver` on the canvas host and `visibilitychange` cancel the frame request | Near zero | Yes | **Reuse** |
| `DeferUntilNear` + `useIdlePrefetch` for below-the-fold chunks | Lazy chunks load before they are needed but not on first paint | The showcase is one lazy chunk; Three.js is a second lazy chunk loaded only when WebGL is available and the spatial view is on | Low | Yes (`React.lazy`) | **Adapt** |
| Stylesheet injected into `<head>` at runtime (`ensureMathFieldStyles`) | Keeps the component self-contained | Would violate this product's CSP (`style-src 'self'`, no inline styles) | n/a | n/a | **Reject**: all CSS ships as a built file |
| Perpetual CSS spin animations (260/205/340 s periods) | Ambient life in a decorative figure | Motion here must mean something; nothing moves without scroll or a click | Low | Yes | **Reject** |
| framer-motion / GSAP entrances | Polished title cards | Not dependencies of this project; CSS transitions do the same for two properties | ~30–60 KB | No | **Reject** (no new dependency) |

## 2. Public references

Fetched successfully:

- **Palantir Foundry, Ontology overview** (`palantir.com/docs/foundry/ontology/overview/`). The page has no explanatory
  diagram; it describes "semantic" elements (objects, properties, links) and "kinetic" elements (actions, functions) as
  an operational layer over data. Lesson used: separate *what a thing is* (a document, a stage, an event) from *what
  changes it* (a person's reading, a deficiency, a checkpoint). The documents chapter keeps those four states apart
  rather than morphing one into the other.
- **Linear homepage** (`linear.app`). Repeated section rhythm (large heading, one sentence, one product visual), small
  "Fig."-style technical labels, and one story carried across several sections. Lessons used: numbered chapter
  coordinates (`02 / 06`), mono captions on every figure, and one illustrative case (New programme) carried from the
  hero into the journey.

Could not be accessed from this environment, so nothing here is claimed from them:

- Codrops articles (HTTP 403).
- The three.js manual page on rendering on demand (the URL tried returned 404). The on-demand pattern used here is the
  one already in this repository (`src/operations/WorldScene.jsx`) and is described in `MOTION.md`.
- React Three Fiber and GSAP documentation were not fetched; neither library is used.

## 3. Three art directions

Scores are 1–5 (5 best). Performance and mobile are scored for this product's constraints: one WebGL canvas, strict
CSP, no remote assets.

**A. Digital Dossier.** The application itself is the hero: a physical institutional file, lit like a product shot,
that opens into reviewable sheets and then extends its own route. Editorial chapters follow, each with one precise
figure.

**B. Approval Atlas.** A cartographic surface: every category route drawn as a transit-map line across a terrain of
stages, the visitor flying over it.

**C. Evidence Observatory.** An instrument: concentric layers (documents, facts, deadlines, audit) seen through a lens
that changes focus with scroll.

| | Impact | Domain fit | Originality | Feasibility | Readability | Performance | Reuse | Mobile | Total |
|---|---|---|---|---|---|---|---|---|---|
| A. Digital Dossier | 5 | 5 | 4 | 4 | 4 | 4 | 4 | 4 | **34** |
| B. Approval Atlas | 4 | 4 | 3 | 3 | 3 | 3 | 3 | 2 | 25 |
| C. Evidence Observatory | 4 | 3 | 4 | 3 | 2 | 3 | 2 | 3 | 24 |

B reads well for routes but turns documents, deadlines and audit into decoration on a map, and wide maps crop badly at
390 px. C is striking but abstract: an evaluator has to learn the metaphor before learning the product. A starts from
the object every approval officer already knows, and each later chapter is a part of that object taken out and
explained.

**Chosen: A, Digital Dossier**, borrowing one idea from B: the journey chapter draws stages as small isometric
"plinths" on a faint isometric ground, the atlas cue without the map.

## 4. Blueprint: Digital Dossier

**Palette roles** (all already in the product or derived from it):

| Role | Value | Used for |
|---|---|---|
| Ink | `#141310` | Ground of every section; desk of the 3D scene shows through a transparent canvas |
| Graphite | `#1c1a16`, `#24211c` | Raised panels (evidence steps, notifications) |
| Ivory | `#f0e9dc` | Body headings, event cards in the chain |
| Stone | `#c5bba9`, dim `#a39882` | Secondary text, captions (dim keeps ≥ 6:1 on ink) |
| Mocha | `#5B4632` | File board, selected slab sides |
| Brass | `#b8925a` | Metal: eyelets, route rail, plinth caps, timeline bars |
| Champagne | `#F4D9A0` | Emphasis, primary action, selected stage |
| Amber | `#CB792C` | "Needs a person": review frames, clocks, deficiency branch, demo-witness flag |
| Teal (restrained) | `#5aa39b` / `#7cc0b7` | Technical relations only: document-to-milestone threads, hash links, replay layer, responsible-role plates |

**Typography.** Georgia for editorial headings and 3D labels; Hanken Grotesk (bundled) for reading; JetBrains Mono
(bundled) for coordinates, identifiers, hashes and provenance lines. No remote fonts.

**Materials.** Matte board with a woven fibre map; ivory paper with a sparse tooth and darkened edges; printed forms
drawn on canvas with type, rules, checkboxes and grey "text bars" instead of invented content; brass at full metalness
with moderate roughness so it catches a dim room environment; stone plinths.

**Lighting.** A soft spotlight pool (key) over the file with wide penumbra for product-shot falloff, a directional key
for soft PCF shadows, a low cool hemisphere fill, an amber rim from behind, and a dim `RoomEnvironment` for speculars.
Contact shadow is a baked radial texture. No bloom, no glow, no particles. The pool follows the story from the file to
the route.

**Camera language.** Long lens (27°) at a high three-quarter angle, composed to the right of the copy on wide screens.
Five keyframes eased with smoothstep: rest, open, layers, route, overview. Portrait screens use their own keyframes and
lay the route toward the viewer so it fits a 390 px column. The camera only moves with scroll and is a pure function of
progress, so scrolling back restores every frame.
