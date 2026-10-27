import { Component, Suspense, lazy, useCallback, useEffect, useRef, useState } from "react";
import { isNarrow, useSectionProgress } from "./scroll.js";

const HeroCanvas = lazy(() => import("./dossier/HeroCanvas.jsx"));

class CanvasBoundary extends Component {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch() { this.props.onFailure?.(); }
  render() { return this.state.failed ? null : this.props.children; }
}

// Progress thresholds at which the copy changes. They follow the scene's phases (dossier/scene.js).
const BEATS = [0, 0.14, 0.36, 0.58, 0.8];
const beatAt = (p) => BEATS.reduce((b, t, i) => (p >= t ? i : b), 0);
const STATIC_POSE = 0.9;

export default function Hero({ reduced, spatial, onToggleSpatial, onFailure, onExplore, onWorkspace }) {
  const section = useRef(null);
  const progressRef = useRef(reduced ? STATIC_POSE : 0);
  const listeners = useRef(new Set());
  const [beat, setBeat] = useState(0);
  const beatRef = useRef(0);
  const [narrow, setNarrow] = useState(isNarrow);

  const subscribe = useCallback((fn) => { listeners.current.add(fn); return () => listeners.current.delete(fn); }, []);
  const onProgress = useCallback((p) => {
    progressRef.current = reduced ? STATIC_POSE : p;
    listeners.current.forEach((fn) => fn());
    const b = beatAt(p);
    if (b !== beatRef.current) { beatRef.current = b; setBeat(b); }
  }, [reduced]);
  useSectionProgress(section, { onProgress, enabled: !reduced });

  useEffect(() => {
    if (reduced) { progressRef.current = STATIC_POSE; listeners.current.forEach((fn) => fn()); }
  }, [reduced]);
  useEffect(() => {
    const on = () => setNarrow((n) => (isNarrow() !== n ? !n : n));
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);

  return (
    <section ref={section} data-pose={reduced ? STATIC_POSE : undefined} id="top" className={`sc-hero${reduced ? " is-static" : ""}`} aria-labelledby="sc-title" data-beat={beat}>
      <div className="sc-hero-stage">
        <div className="sc-hero-visual">
          {spatial ? (
            <CanvasBoundary onFailure={onFailure}>
              <Suspense fallback={<DossierFigure />}>
                <HeroCanvas key={narrow ? "narrow" : "wide"} progressRef={progressRef} subscribe={subscribe} reduced={reduced} narrow={narrow} onFailure={onFailure} />
              </Suspense>
            </CanvasBoundary>
          ) : (
            <DossierFigure />
          )}
        </div>
        <div className="sc-hero-copy">
          <Beat i={0} beat={beat} reduced={reduced}>
            <p className="sc-eyebrow">AICTE Approval Operations · Workflow · OCR · Compliance</p>
            <h1 id="sc-title" tabIndex={-1}>Every approval has a path. <span>Every decision needs evidence.</span></h1>
            <p className="sc-lede">
              This prototype routes each application along the stages its category prescribes, turns uploaded documents into
              facts two people confirm, and keeps every deadline and action on an audit record that can be checked.
            </p>
            <div className="sc-actions">
              <button type="button" className="sc-button primary" onClick={onExplore}>Explore how it works</button>
              <button type="button" className="sc-button" onClick={onWorkspace}>Open workspace</button>
            </div>
          </Beat>
          <Beat i={1} beat={beat} reduced={reduced} title="An application is a bundle of evidence.">
            Forms, plans, affidavits and checklists arrive together in one file. The folder opens; nothing has been judged yet.
          </Beat>
          <Beat i={2} beat={beat} reduced={reduced} title="Each sheet becomes reviewable.">
            Fields that need a person's reading are framed. A frame is a request to check, never a verdict.
          </Beat>
          <Beat i={3} beat={beat} reduced={reduced} title="Milestones extend from the file.">
            The prescribed route for one category, New programme: scrutiny, an expert visit, a stage that applies only
            where the rule set says so, and an outcome this system records.
          </Beat>
          <Beat i={4} beat={beat} reduced={reduced} title="Evidence, responsibility and time, in one view.">
            Each milestone shows who the rule set makes responsible, which document it relies on, and the clock that runs
            beside it. Below, each of these is taken apart.
          </Beat>
        </div>
        <div className="sc-hero-foot">
          <span className="sc-scrollcue" aria-hidden="true">{reduced ? "Motion paused · composed view" : "Scroll to open the dossier"}</span>
          <button type="button" className="sc-text-button" onClick={onToggleSpatial}>{spatial ? "Standard view" : "Spatial view"}</button>
        </div>
      </div>
    </section>
  );
}

function Beat({ i, beat, reduced, title, children }) {
  const active = reduced || beat === i;
  return (
    <div className={`sc-beat${active ? " is-active" : ""}${i === 0 ? " sc-beat-hero" : ""}`} data-beat-index={i}>
      {title ? (<><h2 className="sc-beat-title">{title}</h2><p>{children}</p></>) : children}
    </div>
  );
}

// The same dossier drawn in SVG, for no-WebGL, standard view and while the 3D chunk loads. It carries the same
// information as the 3D scene: sheets with review frames, the route's milestones, roles and the time axis.
// Sheet offsets follow the section's --p custom property; nothing here needs JavaScript per frame.
export function DossierFigure() {
  const sheets = [0, 1, 2, 3, 4];
  const milestones = [
    ["Submitted", "Institution", false],
    ["Scrutiny", "Scrutiny committee", false],
    ["Expert visit", "Regional officer constitutes", false],
    ["SHC", "As applicable", true],
    ["Recorded", "Officers record", false],
  ];
  return (
    <figure className="sc-dossier-figure">
      <svg viewBox="0 0 960 640" role="img" aria-labelledby="sc-dossier-figure-title">
        <title id="sc-dossier-figure-title">
          Illustrative dossier: five sheets lifted into reviewable layers with fields framed for checking, and a route of
          five milestones (Submitted, Scrutiny, Expert visit, SHC as applicable, Outcome recorded) with the responsible
          role under each and a time axis.
        </title>
        <defs>
          <linearGradient id="sc-board" x1="0" x2="1" y1="0" y2="1"><stop offset="0" stopColor="#6a523a" /><stop offset="1" stopColor="#4a3827" /></linearGradient>
          <linearGradient id="sc-paper" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor="#f1e8d6" /><stop offset="1" stopColor="#ddd1b8" /></linearGradient>
        </defs>
        <ellipse cx="300" cy="520" rx="250" ry="38" fill="#000" opacity="0.35" />
        <path d="M70 470 L330 540 L560 450 L300 390 Z" fill="url(#sc-board)" />
        <path d="M70 470 L300 390 L250 230 L30 300 Z" fill="#4e3b29" opacity="0.9" />
        <g className="sc-fig-sheets">
          {sheets.map((i) => (
            <g key={i} className="sc-fig-sheet" style={{ "--i": i }}>
              <path d="M110 455 L330 515 L520 440 L300 385 Z" fill="url(#sc-paper)" stroke="#bfae8d" strokeWidth="1" />
              <path d="M150 452 L300 492" stroke="#5B4632" strokeWidth="3" opacity="0.6" />
              {[0, 1, 2].map((r) => <path key={r} d={`M${190 + r * 24} ${440 - r * 8} L${330 + r * 24} ${478 - r * 8}`} stroke="#5b4a35" strokeWidth="3" opacity="0.35" />)}
              {i < 3 && <rect x="0" y="0" width="70" height="22" transform={`translate(${330 - i * 20} ${438 - i * 4}) skewY(-22) skewX(28)`} fill="none" stroke="#CB792C" strokeWidth="2.5" />}
            </g>
          ))}
        </g>
        <g className="sc-fig-route">
          <path d="M540 560 L930 560" stroke="#b8925a" strokeWidth="3" />
          {Array.from({ length: 25 }, (_, k) => <path key={k} d={`M${540 + k * 16} 572 L${540 + k * 16} ${k % 6 ? 578 : 586}`} stroke="#b8925a" strokeWidth="1.2" opacity="0.7" />)}
          {milestones.map(([t, role, cond], i) => (
            <g key={t} transform={`translate(${560 + i * 88} 560)`}>
              <circle r="11" fill={cond ? "none" : "#2c2823"} stroke="#b8925a" strokeWidth={cond ? 2 : 3} strokeDasharray={cond ? "4 3" : undefined} />
              <text y="-44" className="sc-fig-label" textAnchor="middle">{t}</text>
              <text y="44" className="sc-fig-role" textAnchor="middle">{role}</text>
            </g>
          ))}
          <path d="M470 330 C 560 330, 600 420, 648 548" fill="none" stroke="#5aa39b" strokeWidth="2" />
          <text x="930" y="612" className="sc-fig-role" textAnchor="end">time · internal clock · demo assumption</text>
        </g>
      </svg>
    </figure>
  );
}


