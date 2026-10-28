import {DossierSculpture} from '../product/DossierSculpture.jsx';
import {useInstrumentDepth} from "../product/depth.js";
import { useState } from "react";

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

  SAC: "Appellate committee (SAC)",

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

  const depth=useInstrumentDepth();
  const [selected, setSelected] = useState(null);

  const [expanded, setExpanded] = useState(false);

  if (!route?.length) return null;

  const inspected = route.find(s => s.stage === selected) ?? route.find(s => s.stage === current) ?? route[0];

  const state = positionOf(route, current, status);

  return (

    <div ref={depth} className={`journey route-instrument${expanded ? " expanded" : ""}`}>

      <div className="route-position"><span>RECORDED POSITION</span><strong>{current ? stageLabel(current) : "No current stage supplied"}</strong><small>Inspect the prescribed route below</small></div>
      <DossierSculpture route={route} current={current}/><div className="instrument-caption"><span>CASE ROUTE / {route.length} PRESCRIBED STAGES</span><button className="secondary small" onClick={() => setExpanded(v => !v)} aria-pressed={expanded}>{expanded ? "Compact route" : "Expand route"}</button></div>

      <ol className="journey-list" style={{ "--n": route.length }}>

        {route.map((s, i) => (

          <li key={s.stage} className={`${state(i)}${s.when === "as_applicable" ? " conditional" : ""}`}

            aria-current={state(i) === "current" ? "step" : undefined}>

            <button className="route-select" aria-label={`Inspect ${stageLabel(s.stage)}, stage ${i + 1}`} aria-pressed={inspected.stage === s.stage} onClick={() => setSelected(s.stage)}><span className="stage-dot" aria-hidden="true">{i + 1}</span></button>

            <span className="stage-name">{stageLabel(s.stage)}</span>

            <span className="stage-state">

              {WORD[state(i)]}

              {s.when === "as_applicable" ? " · if applicable" : ""}

            </span>

          </li>

        ))}

      </ol>

      <aside className="route-inspection" aria-live="polite"><span className="eyebrow">Selected stage</span><strong>{stageLabel(inspected.stage)}</strong><span>{inspected.when === "as_applicable" ? "Conditional · only if applicable" : "Prescribed by this case route"}</span><span className="small">{inspected.stage === current ? "Current recorded position" : "Selection is inspection only; completion is not inferred."}</span></aside>

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

