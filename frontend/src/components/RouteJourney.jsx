// Plain names for the stages of an approval route (APH 2024-27 routes).
export const STAGE_LABEL = {
  SELF_DISCLOSURE: "Self-disclosure",
  SCRUTINY: "Scrutiny",
  RESCRUTINY: "Re-scrutiny",
  DEFICIENT: "Deficiency reply",
  EVC: "Expert visit",
  SHC: "Standing hearing",
  EC: "Executive committee",
  COUNCIL: "Council",
};

export const stageLabel = (s) => STAGE_LABEL[s] ?? s?.replaceAll("_", " ").toLowerCase() ?? "—";

// Route position only. A stage before the current one is "before current", never "done": the API does not
// report per-stage completion, and a conditional stage may have been skipped.
function positionOf(route, current, status) {
  const at = route.findIndex((s) => s.stage === current);
  return (i) => (status === "DRAFT" || at < 0 ? "ahead" : i < at ? "done" : i === at ? "current" : "ahead");
}

const WORD = { done: "Before current (completion not supplied)", current: "Here now", ahead: "Ahead" };

// The case's prescribed route as a stepper: exactly one step per stage the API returned, the current one marked,
// conditional stages drawn with a dashed outline. It is an ordered list, so it reads the same to screen readers,
// and it wraps to a vertical list on narrow screens.
export default function RouteJourney({ route, current, status }) {
  if (!route?.length) return null;
  const state = positionOf(route, current, status);
  return (
    <div className="journey">
      <ol className="journey-list" style={{ "--n": route.length }}>
        {route.map((s, i) => (
          <li key={s.stage} className={`${state(i)}${s.when === "as_applicable" ? " conditional" : ""}`}
            aria-current={state(i) === "current" ? "step" : undefined}>
            <span className="stage-dot" aria-hidden="true">{i + 1}</span>
            <span className="stage-name">{stageLabel(s.stage)}</span>
            <span className="stage-state">
              {WORD[state(i)]}
              {s.when === "as_applicable" ? " · if applicable" : ""}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

// A one-line version for lists: one segment per returned stage, the current one named.
export function RouteTrack({ route, current, status }) {
  const state = positionOf(route, current, status);
  return (
    <ol className="route-track" aria-label={`Route: ${route.map((s) => stageLabel(s.stage)).join(", ")}${current ? `; now at ${stageLabel(current)}` : ""}`}>
      {route.map((s, i) => (
        <li key={s.stage} className={`${state(i)}${s.when === "as_applicable" ? " conditional" : ""}`}>
          <span className="track-seg" aria-hidden="true" />
          <span className="track-name">{stageLabel(s.stage)}</span>
        </li>
      ))}
    </ol>
  );
}
