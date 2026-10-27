# Design: NEBULA

The approval route becomes architecture: a case passes through gates, the ledger is a linked structure, a
document separates into inspection layers. Every visual is drawn from what the API returns; nothing is
added to make a scene look fuller.

## Tokens

Defined on `:root` in `src/nebula/golden.css` (which overrides the base tokens in `src/styles.css`).

| Role | Value | Use |
|---|---|---|
| Mocha brown | `#5B4632` | active surfaces, pending or unknown state |
| Champagne gold | `#F4D9A0` | text, primary buttons, available evidence |
| Burnt amber | `#CB792C` | current stage, attention, rim light in 3D |
| Ground | `#211810` | page background (also `theme-color`) |
| Surface / raised | `#2b2019` / `#493525` | panels, controls |
| Positive / negative | `#b9d4a6` / `#ffb1a0` | verified / failed outcomes only |

Colour encodes recorded state, never scroll progress. Focus is an outline, not a success colour.

## Type

- Georgia for display headings and the brand mark.
- Hanken Grotesk (bundled locally) for interface text.
- JetBrains Mono (bundled locally) for identifiers, hashes and sequence numbers.

No remote fonts and no downloaded images: the 3D scenes are procedural.

## Layout

A horizontal, labelled navigation bar replaces the sidebar; on phones it opens as a menu sheet. Each
screen opens with its world (`src/nebula/World.jsx`): a heading, a register of the real records as
buttons, and an inspection panel for the selected record. The working surfaces (forms, tables,
verification cards) follow below, unchanged in behaviour.

## Data rules

1. Applications, routes, deadlines, dashboard counts, notifications, delivery and audit results come from
   the backend. Route stages are only those returned for the case.
2. Position on a route is not proof of completion: earlier stages read "Before current (completion not
   supplied)" unless the API supplies a status.
3. The dashboard draws only regions present in the response; nothing is added for absent regions.
4. Audit shows three separate assurance layers (continuity, independent witness, replay). A broken chain
   is never combined into a stronger claim.
5. Fact review keeps type-before-reveal: a reviewer's machine reading is rendered only from the server's
   answer to their own entry, and a second officer confirms (the reviewer is told up front they cannot).
   Who acted is shown only as "you" or "another officer" with their role (`is_you`), never a user id, and the
   reviewer's own entry (`my_entry`) is restored after a reload.
6. EVC scheduling is labelled **PREVIEW · SAMPLE** until its API exists. Documents, fact review,
   compliance and alerts run on the real APIs.
7. Missing data produces an explicit empty or unavailable state, never filler.
8. All data in this project is synthetic; the top bar always says so.
9. Scan states, fact states, obligation and alert states, and deadline rules are shown in words
   (`src/recordText.js`), never as raw codes. What a version may be used for follows its `status`
   (only `AVAILABLE` versions are viewed, reviewed or offered as evidence). A 503 is explained per service
   (scanner, storage, text reader), not as a security outage.
10. Every write that the server makes idempotent sends an Idempotency-Key, created once per user action
    and reused when that same action is retried after a lost answer or a server error.

See `MOTION.md` for transitions and scenes, and `SEMANTIC_MOTION_MAP.md` for the per-screen mapping from
API fields to visuals.
