import { Suspense, lazy, useMemo, useState } from "react";
import { useReducedMotion } from "../motion.js";

const LedgerScene = lazy(() => import("../three/LedgerScene.jsx"));
const MAX_BLOCKS = 160;

function hasWebGL() {
  if (typeof window === "undefined" || typeof window.WebGLRenderingContext === "undefined") return false;
  try {
    const c = document.createElement("canvas");
    return Boolean(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}

const STATES = [
  ["anchored", "Anchored by the trusted checkpoint"],
  ["newer", "Newer, not anchored yet"],
  ["chain", "Linked by the hash chain only"],
  ["broken", "First broken link"],
  ["after", "After the break"],
];

// The integrity chamber: every ledger entry as a block. WebGL (Three.js) when available, otherwise a CSS
// strip with the same colours. Built only from the verification results already on this screen.
export default function LedgerChamber({ chain, verify }) {
  const reduced = useReducedMotion();
  const webgl = useMemo(hasWebGL, []);
  const [hover, setHover] = useState(null);
  if (!chain) return null;
  const total = chain.checked ?? 0;
  const anchored = verify?.ok && verify.assurance?.startsWith("CHECKPOINTED") ? total - (verify.entries_after_checkpoint ?? 0) : 0;
  const brokenAt = chain.ok ? null : chain.first_bad_seq;
  const shownFrom = Math.max(0, total - MAX_BLOCKS);
  const stateOf = (i) => {
    const seq = i + 1;
    if (brokenAt && seq === brokenAt) return "broken";
    if (brokenAt && seq > brokenAt) return "after";
    if (seq <= anchored) return "anchored";
    return anchored ? "newer" : "chain";
  };
  const present = new Set(Array.from({ length: Math.min(total, MAX_BLOCKS) }, (_, i) => stateOf(shownFrom + i)));
  const summary = `${total} ledger entries: ${anchored} anchored by the trusted checkpoint`
    + (brokenAt ? `, first broken link at entry ${brokenAt}` : "") + ".";

  return (
    <section className="card chamber" aria-labelledby="chamber-title">
      <header className="card-head">
        <h2 id="chamber-title">The ledger</h2>
        <span className="muted small">{webgl ? "Drag or use arrow keys to turn" : "Each block is one entry"}</span>
      </header>
      <div className="chamber-stage">
        {total === 0 ? (
          <p className="muted">The ledger is empty.</p>
        ) : webgl ? (
          <div className="chamber-3d" tabIndex={0} role="img" aria-label={summary}>
            <Suspense fallback={<div className="chamber-wait">Building the ledger view…</div>}>
              <LedgerScene total={total} anchored={anchored} brokenAt={brokenAt} reduced={reduced} onHover={setHover} />
            </Suspense>
            <p className="chamber-readout" aria-live="polite">
              {hover ? <>Entry <span className="num">#{hover.seq}</span> · {STATES.find(([k]) => k === hover.state)?.[1]}</> : " "}
            </p>
          </div>
        ) : (
          <div className="chamber-strip" role="img" aria-label={summary}>
            {Array.from({ length: Math.min(total, MAX_BLOCKS) }, (_, i) => (
              <span key={i} className={`blk ${stateOf(shownFrom + i)}`} title={`Entry #${shownFrom + i + 1}`} />
            ))}
          </div>
        )}
      </div>
      <ul className="chamber-legend">
        {STATES.filter(([k]) => present.has(k)).map(([k, label]) => (
          <li key={k}><span className={`blk ${k}`} aria-hidden="true" /> {label}</li>
        ))}
      </ul>
      {total > MAX_BLOCKS && <p className="source">Showing the newest {MAX_BLOCKS} of {total} entries.</p>}
    </section>
  );
}
