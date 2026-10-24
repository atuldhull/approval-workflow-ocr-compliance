# Motion system

Motion explains where you are and what changed. It never decorates data, never delays reading, and
always has a calm alternative.

## Principles

1. **Transform and opacity only** (plus `clip-path` for reveals). No layout animation.
2. **One reveal per element, once.** Sections stagger in by 60 ms steps, rising 18 px.
3. **Content never depends on motion.** Hidden-until-revealed styles apply only when JavaScript has
   added `html.motion`, and that class is never added under `prefers-reduced-motion: reduce`.
4. **Data never moves for show.** Numbers do not count up; charts do not grow from zero.

## Tokens

| Token | Value | Use |
|---|---|---|
| `--ease-out` | `cubic-bezier(.16,1,.3,1)` | Arrivals |
| `--ease-in` | `cubic-bezier(.7,0,.84,0)` | Departures |
| `--dur-1` / `--dur-2` / `--dur-3` | 140 / 260 / 520 ms | Feedback / panels / world transitions |

## World transitions (route changes)

The navigation state updates at once; the old world leaves in 160 ms, then the new one arrives. Each
world has its own arrival, so moving between areas reads as moving between places:

| World | Screens | Arrival |
|---|---|---|
| zoom | Overview, dashboards | From 0.96 scale and 40 px back in Z, as if the camera moves in |
| slide | Cases, delivery | 24 px from the right, no depth (work screens stay calm) |
| rise | Case detail, scorecard | From a 6° backwards tilt, standing up |
| iris | Audit | A circular clip opening from the centre |
| scan | Document review | A clip sweeping down the page, like a scanner bar |
| drift | Inbox | 16 px up with a short fade |
| pan | EVC, compliance | 32 px from the left |

Reduced motion: every world arrives with a 120 ms fade and no travel.

## Scroll

- `--scroll` (px) is written to `<html>` once per animation frame while scrolling.
- Backplates move at 0.15–0.35 of the scroll speed; nothing in the content plane is scroll-linked except
  the scenes below.
- The case journey tilts from 46° to 10° as it scrolls into view (the camera descends onto the route).

## 3D scenes

| Screen | Scene | Technique | Interaction | Fallback |
|---|---|---|---|---|
| Audit | Ledger helix: every ledger entry a block, anchored entries teal, unanchored amber, a broken link red | Three.js (lazy-loaded) | Drag or arrow keys to turn; hover names the entry | CSS block strip; reduced motion stops the slow turn |
| Case detail | Approval route as a stair of stage planes in depth; the current stage raised toward the viewer | CSS 3D (`preserve-3d`) | Scroll-linked tilt; pointer parallax | Flat ordered list under 640px and with reduced motion |
| National dashboard | Regions as extruded columns on a tilted plane, height = applications | CSS 3D boxes | Drag or Turn buttons | The region bar list beside it carries the same numbers |
| Document review | The page on a stack of sheets; annotation boxes lift off the page after a reading is committed | CSS 3D | Pointer tilt; zoom control | Flat page; boxes appear without lift |

The institution's workflow path, the regional ageing radar and the delivery pipeline are **2D** (SVG and
CSS) and are described as such.

## Micro-interactions

- Buttons: press scales to 0.97 in 90 ms; hover lifts the border tone.
- Panels: hover raises 2 px with a brighter edge (pointer devices only).
- Focus: a 2px accent ring that grows in from 0 in 140 ms.
- Sidebar: the active indicator slides between items; collapsing animates width and fades labels.
- Menus and sheets: 200 ms scale-from-0.98 with fade; Escape closes and focus returns.
- Unread signals: a 2.4 s soft pulse on the dot only, paused for reduced motion.
