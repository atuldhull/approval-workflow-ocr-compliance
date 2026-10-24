import { useEffect, useRef, useState } from "react";
import { useReducedMotion } from "../motion.js";
import { Icon } from "./Icons.jsx";

// 3D (CSS): each regional office with applications is a column extruded from a tilted plane; height is
// the office's application count. Drag (or the Turn buttons, for keyboards) to turn the plane. Only regions
// that have data are drawn; nothing is invented. The figures are also listed beside the scene in text.
export default function RegionColumns({ byRegion }) {
  const entries = Object.entries(byRegion ?? {}).sort((a, b) => b[1] - a[1]);
  const reduced = useReducedMotion();
  const [spin, setSpin] = useState(-28);
  const drag = useRef(null);
  const max = Math.max(1, ...entries.map(([, n]) => n));

  // A slow settle-in turn when the scene first appears; none for reduced motion.
  useEffect(() => {
    if (reduced) return undefined;
    setSpin(-62);
    const t = setTimeout(() => setSpin(-28), 60);
    return () => clearTimeout(t);
  }, [reduced]);

  if (entries.length === 0) return null;
  const onDown = (e) => {
    drag.current = { x: e.clientX, spin };
    e.currentTarget.setPointerCapture?.(e.pointerId);
  };
  const onMove = (e) => {
    if (!drag.current) return;
    setSpin(drag.current.spin + (e.clientX - drag.current.x) * 0.4);
  };
  const onUp = () => {
    drag.current = null;
  };
  const cols = entries.length;

  return (
    <div className="regions3d">
      <div className="r3-viewport" onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp}
        aria-hidden="true">
        <div className="r3-plane" style={{ "--spin": `${spin}deg`, "--cols": cols }}>
          {entries.map(([region, n], i) => {
            const h = 24 + 116 * (n / max);
            return (
              <div key={region} className="r3-cell" style={{ "--c": i - (cols - 1) / 2, "--h": `${h}px` }}>
                <div className={`r3-col${i === 0 ? " lead" : ""}`}>
                  <span className="f top" />
                  <span className="f front" />
                  <span className="f back" />
                  <span className="f left" />
                  <span className="f right" />
                </div>
                <span className="r3-label"><strong className="num">{n}</strong> {region}</span>
              </div>
            );
          })}
        </div>
      </div>
      <div className="r3-controls">
        <button className="ghost small" onClick={() => setSpin((s) => s - 30)}><Icon name="turnLeft" /> Turn left</button>
        <button className="ghost small" onClick={() => setSpin((s) => s + 30)}>Turn right <Icon name="turnRight" /></button>
      </div>
    </div>
  );
}

// 2D: ageing buckets of a region's cases in process, as rings - the oldest ring outermost.
export function AgeingRadar({ buckets }) {
  const rows = Object.entries(buckets ?? {});
  const total = rows.reduce((a, [, n]) => a + n, 0);
  return (
    <div className="radar">
      <svg viewBox="0 0 240 240" role="img" aria-label={rows.map(([k, n]) => `${k}: ${n}`).join(", ")}>
        {rows.map(([k, n], i) => {
          const r = 34 + i * 24;
          const c = 2 * Math.PI * r;
          const share = total ? n / total : 0;
          return (
            <g key={k}>
              <circle className="radar-track" cx="120" cy="120" r={r} />
              <circle className={`radar-arc${i >= 2 && n > 0 ? " old" : ""}`} cx="120" cy="120" r={r}
                strokeDasharray={`${c * share} ${c}`} transform="rotate(-90 120 120)" />
            </g>
          );
        })}
        <g className="radar-sweep"><line x1="120" y1="120" x2="120" y2="18" /></g>
        <text x="120" y="116" className="radar-total num">{total}</text>
        <text x="120" y="136" className="radar-caption">in process</text>
      </svg>
    </div>
  );
}
