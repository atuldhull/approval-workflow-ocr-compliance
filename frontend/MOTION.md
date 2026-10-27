# Motion

Native scroll is preserved. Navigation leaves after a short departure and arrives in 550–650 ms with the
controls already usable. A new navigation cancels a pending one. Back and forward restore the screen and
its scroll position without the departure delay. Screens have deep links (`#inbox`,
`#applications?case=<id>`); a link to a screen the role cannot see opens the role's first screen instead.

## Transitions

Set per screen in `WORLDS` (`src/motion.js`), styled in `src/nebula/nebula.css`.

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

## Scenes

Genuine WebGL (Three.js, lazy-loaded, `src/nebula/WorldScene.jsx`) is used for the case route and audit worlds
(the document-inspection scene needs page images, which the backend does not serve yet, so fact review uses
a 2D register). The case
route, document review and audit. The other screens use a labelled 2D register with CSS depth. The case
route also has the CSS 3D stage planes in `RouteJourney.jsx`.

- Drag or arrow keys orbit; plus and minus move the camera; Home resets. Every 3D object has an
  equivalent record button in the register.
- Scroll moves the camera and the focused record. It only inspects: it never changes a status, marks a
  message read, commits a reading, runs replay or retries a delivery.
- Rendering stops off-screen and in hidden tabs, is capped at 30 fps and redraws only when input
  changes. Unmount cancels the frame loop, disconnects observers and disposes geometry, materials,
  textures and the WebGL context.
- No WebGL, a renderer failure, a lost context or a failed lazy import all fall back to the standard view
  with the same records.

## Controls and preferences

- **Standard view** switches rendering off per browser (`nebula.flat` in localStorage).
- **Pause animations** in the navigation, and the OS reduced-motion setting, stop automatic motion and
  scroll choreography. Explicit camera controls still respond.
- Content is visible by default; reveals never keep data hidden.
