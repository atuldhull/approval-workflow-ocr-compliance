import { useEffect, useRef, useState } from "react";
import { useReducedMotion, useScrollProgress } from "../motion.js";

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

// 3D (CSS): the route as a stair of stage planes in depth. The current stage stands raised toward the
// viewer, finished stages sink behind, later stages wait ahead. The plane tilts from 46° to 10° as it
// scrolls into view (a camera descending onto the route) and follows the pointer by a few degrees.
// The same route is an ordered list underneath, which is what screen readers, phones and reduced
// motion get.
export default function RouteJourney({ route, current, status }) {
  const ref = useRef(null);
  const progress = useScrollProgress(ref);
  const reduced = useReducedMotion();
  const [pointer, setPointer] = useState({ x: 0, y: 0 });
  const [arrived, setArrived] = useState(false);   // starts high, then the camera settles onto the route
  useEffect(() => {
    const t = setTimeout(() => setArrived(true), 80);
    return () => clearTimeout(t);
  }, []);
  if (!route?.length) return null;

  const at = route.findIndex((s) => s.stage === current);
  const state = (i) => (status === "DRAFT" || at < 0 ? "ahead" : i < at ? "done" : i === at ? "current" : "ahead");
  const word = { done: "Done", current: "Here now", ahead: "Ahead" };
  const tilt = reduced ? 0 : arrived ? 46 - 36 * progress : 58;

  const onMove = (e) => {
    if (reduced) return;
    const r = e.currentTarget.getBoundingClientRect();
    setPointer({ x: (e.clientX - r.left) / r.width - 0.5, y: (e.clientY - r.top) / r.height - 0.5 });
  };

  return (
    <div className="journey" ref={ref} onPointerMove={onMove} onPointerLeave={() => setPointer({ x: 0, y: 0 })}>
      <div className="journey-stage" aria-hidden="true"
        style={{ "--tilt": `${tilt}deg`, "--py": `${pointer.x * 8}deg`, "--px": `${pointer.y * -4}deg` }}>
        <div className="journey-plane">
          <svg className="journey-path" viewBox={`0 0 ${route.length * 100} 40`} preserveAspectRatio="none">
            <line x1="50" y1="20" x2={route.length * 100 - 50} y2="20" />
            {at > 0 && <line className="walked" x1="50" y1="20" x2={at * 100 + 50} y2="20" />}
          </svg>
          {route.map((s, i) => (
            <div key={s.stage} className={`stage-plane ${state(i)}`} style={{ "--i": i, "--n": route.length }}>
              <span className="stage-dot" />
              <span className="stage-name">{stageLabel(s.stage)}</span>
              <span className="stage-state">{s.when === "as_applicable" && state(i) === "ahead" ? "If applicable" : word[state(i)]}</span>
            </div>
          ))}
        </div>
      </div>
      <ol className="journey-list">
        {route.map((s, i) => (
          <li key={s.stage} className={state(i)} aria-current={state(i) === "current" ? "step" : undefined}>
            <span className="stage-dot" aria-hidden="true" />
            <span className="stage-name">{stageLabel(s.stage)}</span>
            <span className="stage-state">
              {word[state(i)]}
              {s.when === "as_applicable" ? " · if applicable" : ""}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}
