# AICTE Approval Operations — redesign plan

Baseline: every frontend file in the supplied person-3 ZIP matches this local frontend. Snapshot saved in review/operations/frontend-before.zip. Backend, contracts, migrations and adapters remain unchanged.

## Reference study
Read Math Collective HomePage, HeroExperience, HeroNarrativeOverlay, MathFieldHero and scroll hooks. The current HeroExperience intentionally replaces its older expensive Three.js library with semantic SVG curves. Translate its subject-derived geometry, composed layering, direct CSS variable writes, bounded scroll progress and reduced device cost. Avoid its long empty hero spacer and perpetual loops for an operational workspace. Keep Three.js selectively for tangible document/route/assurance depth. Reference screenshot inspected from Downloads: diagonal illumination, champagne serif, rich mocha shadows; presenter/social UI excluded.

## System
Name: AICTE Approval Operations. Describes the actual work and accommodates OCR, routing, compliance and audit. No claim of official certification.
Colours: #141310 ink, #5B4632 mocha, #F4D9A0 champagne, #CB792C amber; warm ivory body text, legible muted stone. Distinct semantic success/error tones.
Typography: Georgia editorial display, locally bundled Hanken Grotesk for work, JetBrains Mono for identifiers/coordinates. No font network dependency.
Layout: 4/8/12/16/24/32/48 spacing, narrow persistent navigation, compact context bar, clear h1, one purposeful scene introduction followed by dense record selection and adjacent detail. Thin rules and restrained surfaces replace large repeated cards.
Motion: short opacity route transitions; event-driven scroll camera, direct DOM progress updates, state changes only at record boundaries. No autonomous loops. Reduced motion disables scroll changes and preserves manual controls. Render only on invalidation; cap pixel ratio; hide/idle suspension and fallback.

## Screens
Overview: application dossiers and current-stage summaries, deadlines close to the top.
Cases: portfolio index; chosen case reveals prescribed stage portals with current position, never inferred completion.
Dashboard: regional spans proportional to supplied counts. Officer: age-bucket instrument, not a fabricated assignment queue.
Inbox: template-to-message channels; read state distinct from delivery.
Delivery: recorded endpoints and attempts; no animated fake success.
Audit: separate continuity, witness and replay planes, checkpoint provenance unchanged.
OCR: real page layers; no extraction overlays before independent commit.
EVC: candidate-date grid, dated positions, explicit sample/preview labels.
Compliance: dossier compartments with file tabs only for supplied evidence.
Scorecard: evaluation matrix; missing results remain unevaluated.
Sign-in, errors, empty/loading states: same grounded typography and controls.

## Verification
Run source frontend tests and production build. Browser: role/route matrix, normal wheel scroll and reverse, responsive widths, reduced motion, no-WebGL, keyboard, console/errors, source-state stability and render idle checks. Use running backend read-only where possible; state-changing checks use fixtures. Preserve API/auth/document adapters byte-for-byte. Capture screenshots and a review gallery.
