# Motion and rendering

Motion confirms what just happened; it never decorates or delays. All of it is CSS except the audit figure.

## Transitions

| Moment | Motion | Duration |
|---|---|---|
| Route change | The new screen replaces the old one at once; its content fades in and rises 4px | 160ms |
| Row → inspector | The inspector content fades in from 6px to the right; the list does not move | 170ms |
| Fact reveal | The machine reading fades in after the server records the reviewer's entry | 200ms |
| Server confirmation | A toast (`Toast`) appears only after the request succeeded | 180ms |
| Bars | Horizontal bars grow from zero once when rendered | 360ms |
| Navigation indicator | Slides to the selected item | 180ms |
| Loading | Skeleton bars pulse slowly; their size matches the content that replaces them | — |
| Atmosphere | The background light drifts slowly behind the screen; it restarts when the route changes | ambient |

There is no departure delay, no route-level zoom or iris, no blocking overlay, no click-zoom and no scroll-driven
choreography. Scrolling never selects a record or changes a figure.

## Reduced motion

`prefers-reduced-motion` and the in-app "Pause animations" switch (stored in `awoc.motion`) both apply: every
animation and transition collapses to 1ms and the `motion` class is removed from `<html>`, so nothing is hidden
waiting for an entrance. The Atmosphere select (Auto, Full, Reduced, Static; stored in `awoc.atmosphere`) controls
the background separately: Reduced and Static stop its drift, and under `prefers-reduced-motion` it is still in
every mode.

## The audit figure

The audit inspector holds the only canvas in the product (`src/operations/World.jsx`, `WorldScene.jsx`,
`buildEvidenceScene.js`):

- lazy-loaded (`React.lazy`), so Three.js is not in the initial bundle; one canvas at a time;
- rendered on demand: a frame is drawn only when the selected layer, the size, visibility or the data change —
  there is no animation loop and no scroll listener;
- offscreen and hidden-tab rendering stops (IntersectionObserver, `visibilitychange`); device pixel ratio is capped
  at 1 on narrow screens and 1.5 elsewhere;
- geometry, materials and label textures are disposed on unmount, and the context is released;
- `aria-hidden` and `pointer-events: none`: the console beside it carries all information and every action;
- "Standard view" (stored in `operations.flat`), missing WebGL, a lost context or a render failure all fall back to
  the same three glyphs drawn in SVG.

Measured locally on the dev server (Chromium, 1440×900): 2 frames on load, 0 further frames over 1.5s idle, 0 frames
and 0 long tasks (>50ms) while scrolling the audit page 40 steps. These are local observations, not guarantees.
