import { useEffect, useRef } from "react";
import { TOUR, TOUR_STEP_MS } from "./data.js";

// The evaluator's guided tour. A step is a place on the page plus one sentence. Moving between steps only scrolls
// and moves focus; it never calls the API. Auto-advance runs only while playing and is a single timer per step,
// so pausing, stepping back or jumping always leaves the tour in a known state.
export default function Tour({ step, playing, onStep, onPlay, onExit, onFinish }) {
  const last = TOUR.length - 1;
  const current = TOUR[step];
  const bar = useRef(null);

  useEffect(() => {
    if (!playing) return undefined;
    const t = setTimeout(() => (step >= last ? onFinish() : onStep(step + 1)), TOUR_STEP_MS);
    return () => clearTimeout(t);
  }, [playing, step, last, onStep, onFinish]);

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape" && !e.defaultPrevented) { e.preventDefault(); onExit(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onExit]);

  const arrows = (e) => {
    if (e.target.tagName === "SELECT") return;
    if (e.key === "ArrowRight" && step < last) { e.preventDefault(); onStep(step + 1); }
    if (e.key === "ArrowLeft" && step > 0) { e.preventDefault(); onStep(step - 1); }
  };

  return (
    <div className="sc-tour" role="region" aria-label="Guided tour" ref={bar} onKeyDown={arrows}>
      <div className="sc-tour-progress" aria-hidden="true">
        {TOUR.map((s, i) => <i key={s.title} className={i < step ? "is-done" : i === step ? (playing ? "is-current is-playing" : "is-current") : ""} />)}
      </div>
      <div className="sc-tour-body">
        <p className="sc-tour-count" aria-live="polite">
          <span className="sc-mono">Step {step + 1} of {TOUR.length}</span> <strong>{current.title}</strong>
        </p>
        <p className="sc-tour-say">{current.say}</p>
      </div>
      <div className="sc-tour-controls">
        <label className="sc-tour-jump">
          <span className="sc-visually-hidden">Jump to step</span>
          <select value={step} onChange={(e) => onStep(Number(e.target.value))}>
            {TOUR.map((s, i) => <option key={s.title} value={i}>{i + 1}. {s.title}</option>)}
          </select>
        </label>
        <button type="button" className="sc-button small" onClick={() => onStep(step - 1)} disabled={step === 0}>Previous</button>
        <button type="button" className="sc-button small" onClick={() => onPlay(!playing)} aria-pressed={playing}>{playing ? "Pause" : "Resume"}</button>
        {step < last
          ? <button type="button" className="sc-button small primary" onClick={() => onStep(step + 1)}>Next</button>
          : <button type="button" className="sc-button small primary" onClick={onFinish}>Enter workspace</button>}
        <button type="button" className="sc-text-button" onClick={onExit}>Exit tour <span className="sc-kbd" aria-hidden="true">Esc</span></button>
      </div>
    </div>
  );
}
