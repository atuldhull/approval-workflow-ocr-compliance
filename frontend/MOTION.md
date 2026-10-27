# Motion and rendering

## Navigation
Routes use a short 160ms departure and 260ms arrival. The route system, role restrictions, case deep links, browser history and restored content focus are preserved. Reduced motion skips the route delay and transform.

## Normal scrolling
A passive scroll listener coalesces into one requestAnimationFrame. Continuous progress is written to the section's CSS property and dataset directly. React state changes only when the inspected record boundary changes. Manual selection pins the chosen record until Follow scroll is selected. Neither scrolling nor selecting makes a business decision or changes a source status.

Three.js is lazy-loaded for dossiers, approval routes, aggregate regional spans, assurance planes and OCR pages. The canvas lives behind the desktop interface. On mobile it occupies a bounded inline region. Camera movement differs by subject: route travel follows depth, dossier leaves separate, assurance planes shift laterally, regional spans change perspective, and OCR pages open toward a reading angle.

| Screen | Transition |
|---|---|
| Overview | zoom |
| Applications | slide |
| Dashboard | pan |
| Inbox | drift |
| Alerts | drift |
| Documents | scan |
| Fact review | scan |
| EVC | rewind |
| Compliance | collapse |
| Audit | iris |
| Delivery | tunnel |
| Scorecard | rise |
Officer buckets, inbox/delivery channels, candidate-date grids and evaluation matrices use CSS perspective. Scroll modifies only transform; record labels remain accessible in the HTML index. No synthetic movement through workflow or delivery stages is implied.

## Cost controls
WorldScene renders on invalidation, without a perpetual requestAnimationFrame loop. Scroll, resize, keyboard adjustment, changed data or loaded textures can request a frame. Identical state skips rendering. Hidden tabs and offscreen canvases stop. Device pixel ratio is capped at 1 on narrow screens and 1.5 elsewhere. Geometry/materials/textures are disposed on unmount. No postprocessing, external models or network textures are required; OCR uses the source image from the supplied adapter.

Genuine WebGL (Three.js, lazy-loaded, `src/operations/WorldScene.jsx`) is used for the case route and audit worlds
(the document-inspection scene needs page images, which the backend does not serve yet, so fact review uses
a 2D register). The case
route, document review and audit. The other screens use a labelled 2D register with CSS depth. The case
route also has the CSS 3D stage planes in `RouteJourney.jsx`.
Reduced motion and Pause animations stop automatic camera/focus changes. Manual controls remain available. Standard view persists and removes the renderer. Missing or lost WebGL falls back to labelled evidence diagrams and the same record/action interface. All information remains readable.

Record counts and states remain stable during forward/reverse scroll. The browser report verifies idle redraws, reversal, reduced motion, keyboard exploration and fallback behaviour. Performance measurements are local sanity checks, not a universal frame-rate guarantee.
