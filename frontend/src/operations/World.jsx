import { Component, Suspense, lazy, useState } from "react";
import { useReducedMotion } from "../motion.js";
import { datePositions } from "./semanticData.js";
import { when } from "../components/ui.jsx";
import { sentence } from "../nav.js";

// Due dates arrive as plain dates; recorded moments (submission) as full timestamps, shown in IST like everywhere else.
const showDate = (d) => (/^\d{4}-\d{2}-\d{2}$/.test(String(d)) || Number.isNaN(Date.parse(d)) ? String(d ?? "") : when(d));
const Scene = lazy(() => import("./WorldScene.jsx"));
const FLAT_KEY = "operations.flat";

class SceneBoundary extends Component {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch() { this.props.onFailure?.(); }
  render() { return this.state.failed ? null : this.props.children; }
}

const hasWebGL = () => typeof window !== "undefined" && typeof window.WebGL2RenderingContext !== "undefined";
const readFlat = () => { try { return localStorage.getItem(FLAT_KEY) === "true"; } catch { return false; } };

// The audit's spatial figure: one object per assurance layer, coloured by that layer's recorded state.
// It complements the console beside it and never carries information the console does not: the canvas is
// aria-hidden and ignores the pointer. Standard view (remembered) and browsers without WebGL get the same three
// glyphs drawn in SVG. Only one canvas exists at a time and it is lazy-loaded.
export default function SpatialFigure({ records = [], selected = 0, caption }) {
  const reduced = useReducedMotion();
  const [flat, setFlat] = useState(readFlat);
  const [failed, setFailed] = useState(false);
  const use3d = hasWebGL() && !flat && !failed && records.length > 0;
  const toggle = () => {
    setFlat(!flat);
    try { localStorage.setItem(FLAT_KEY, String(!flat)); } catch { /* preference only */ }
  };
  return (
    <figure className="spatial-figure" data-mode={use3d ? "spatial" : "standard"}>
      <div className="spatial-stage" aria-hidden="true">
        {use3d ? (
          <SceneBoundary onFailure={() => setFailed(true)}>
            <Suspense fallback={<FlatFigure records={records} selected={selected} />}>
              <Scene records={records} selected={selected} reduced={reduced} onFailure={() => setFailed(true)} />
            </Suspense>
          </SceneBoundary>
        ) : (
          <FlatFigure records={records} selected={selected} />
        )}
      </div>
      <figcaption>
        <span>{caption}{!use3d && <span className="muted"> · {flat ? "Standard view" : failed ? "3D unavailable, drawn flat" : "Flat drawing"}</span>}</span>
        <button className="ghost small" onClick={toggle}>{flat ? "Spatial view" : "Standard view"}</button>
      </figcaption>
    </figure>
  );
}

// The same three layers in SVG: chain links for continuity, a seal for the witness, a loop for replay.
const TONE = { checked: "var(--teal)", anchored: "var(--brass-strong)", recorded: "var(--amber)", broken: "var(--bad)", unknown: "var(--text-3)" };
function FlatFigure({ records, selected }) {
  const [c, w, r] = records;
  const tone = (rec) => TONE[rec?.state] ?? TONE.unknown;
  const sel = (i) => (i === selected ? "flat-layer is-selected" : "flat-layer");
  const broken = c?.state === "broken";
  return (
    <svg className="flat-figure" viewBox="0 0 360 120">
      <g className={sel(0)} stroke={tone(c)} fill="none" strokeWidth="2.5">
        {[0, 1, 2, 3].map((i) => (
          <rect key={i} x={20 + i * 22} y={broken && i === 2 ? 54 : 46} width="30" height="18" rx="9" opacity={broken && i > 2 ? 0.35 : 1} />
        ))}
      </g>
      <g className={sel(1)} stroke={tone(w)} fill="none" strokeWidth="2.5">
        <circle cx="180" cy="52" r="22" strokeDasharray={w?.state === "recorded" ? "5 4" : undefined} />
        <circle cx="180" cy="52" r="11" />
        <path d="M170 72l-6 24 16-8 16 8-6-24" />
      </g>
      <g className={sel(2)} stroke={tone(r)} fill="none" strokeWidth="2.5">
        <path d="M297 31a23 23 0 1 1-21 13" />
        <path d="M270 37l6 8 9-4" />
      </g>
    </svg>
  );
}

// Recorded dates on one axis. Spacing follows the dates; nothing is placed for a date that cannot be read.
export function DeadlineTimeline({ deadlines = [], submittedAt }) {
  const records = [
    ...(submittedAt ? [{ id: "submitted", date: submittedAt, label: "Submitted", status: "Recorded timestamp", kind: "event" }] : []),
    ...deadlines.map((d) => ({ id: d.id, date: d.due_date, label: d.rule_id, status: d.status, kind: "due" })),
  ];
  const positions = datePositions(records);
  if (!records.length) return null;
  return (
    <figure className="responsibility-timeline">
      <figcaption>Recorded dates · spacing follows the dates</figcaption>
      <div className="date-axis" aria-hidden="true">
        {records.map((r, i) => positions[i] !== null && <i key={r.id} className={`axis-${r.kind}`} style={{ left: `${positions[i]}%` }} />)}
      </div>
      <ol>
        {records.map((r, i) => (
          <li key={r.id} className={`axis-${r.kind}`}>
            <strong>{showDate(r.date)}</strong>
            <span>{r.kind === "due" ? sentence(r.label) : r.label} · {r.kind === "due" ? sentence(r.status) : r.status}</span>
            {positions[i] === null && <em>Date could not be placed on the axis</em>}
          </li>
        ))}
      </ol>
    </figure>
  );
}
