import { useCallback, useMemo, useRef, useState } from "react";
import { BUILT_LABEL, CLOCKS, ROUTES, ROUTE_PICKS, RULESET, routeStations } from "./data.js";
import { useSectionProgress } from "./scroll.js";
import { ChapterHead } from "./parts.jsx";

// Station geometry: horizontal on wide screens, vertical on narrow ones (both drawn from the same function).
function place(n, vertical) {
  if (vertical) return { w: 400, h: 120 + n * 130, at: (i) => [170, 80 + i * 130] };
  const gap = Math.min(200, 820 / Math.max(1, n - 1));
  return { w: 200 + (n - 1) * gap, h: 400, at: (i) => [100 + i * gap, 170] };
}

function Slab({ x, y, lifted, selected, conditional, built }) {
  const w = 92, d = 46, t = lifted ? 34 : 18;
  const top = `${x - w / 2},${y} ${x},${y - d / 2} ${x + w / 2},${y} ${x},${y + d / 2}`;
  const left = `${x - w / 2},${y} ${x},${y + d / 2} ${x},${y + d / 2 + t} ${x - w / 2},${y + t}`;
  const right = `${x + w / 2},${y} ${x},${y + d / 2} ${x},${y + d / 2 + t} ${x + w / 2},${y + t}`;
  return (
    <g className={`sc-slab${selected ? " is-selected" : ""}${conditional ? " is-conditional" : ""} built-${built}`}>
      <polygon className="sc-slab-left" points={left} />
      <polygon className="sc-slab-right" points={right} />
      <polygon className="sc-slab-top" points={top} />
    </g>
  );
}

const DocGlyph = ({ x, y }) => (
  <g className="sc-glyph-doc" transform={`translate(${x} ${y})`} aria-hidden="true">
    <path d="M-7 -9 H3 L7 -5 V9 H-7 Z" /><path d="M-4 -2 H4 M-4 2 H4 M-4 6 H1" />
  </g>
);
const ClockGlyph = ({ x, y }) => (
  <g className="sc-glyph-clock" transform={`translate(${x} ${y})`} aria-hidden="true">
    <circle r="8" /><path d="M0 -4 V0 L3 2" />
  </g>
);

export default function Journey({ reduced, vertical, onInspect }) {
  const [routeKey, setRouteKey] = useState("NEW_PROGRAMME");
  const route = ROUTES.find((r) => r.key === routeKey);
  const stations = useMemo(() => routeStations(route), [route]);
  const [selected, setSelected] = useState(0);
  const [pinned, setPinned] = useState(false);
  const pinnedRef = useRef(false);
  const section = useRef(null);
  const lastScroll = useRef(0);
  const n = stations.length;

  const onProgress = useCallback((p) => {
    lastScroll.current = p;
    if (pinnedRef.current) return;
    const i = Math.min(n - 1, Math.floor(p * n));
    setSelected((s) => (s === i ? s : i));
  }, [n]);
  useSectionProgress(section, { onProgress, enabled: !reduced });

  const pick = (i) => { pinnedRef.current = true; setPinned(true); setSelected(Math.max(0, Math.min(n - 1, i))); };
  const follow = () => { pinnedRef.current = false; setPinned(false); setSelected(Math.min(n - 1, Math.floor(lastScroll.current * n))); };
  const chooseRoute = (key) => { setRouteKey(key); setSelected((s) => Math.min(s, routeStations(ROUTES.find((r) => r.key === key)).length - 1)); };

  const index = Math.min(selected, n - 1);
  const st = stations[index];
  const geo = place(n, vertical);
  const scrutiny = stations.findIndex((s) => s.code === "SCRUTINY");

  return (
    <section ref={section} id="route" className={`sc-chapter sc-journey${reduced ? " is-static" : ""}`} aria-labelledby="route-title" style={{ "--stations": n }}>
      <div className="sc-sticky">
        <div className="sc-journey-grid">
          <div className="sc-journey-copy">
            <ChapterHead n="02" id="route-title" title="A Route for Every Application">
              The category decides the stages. Choose one: the route below is drawn from the rule set, with conditional
              stages only where the route has them.
            </ChapterHead>
            <fieldset className="sc-picks">
              <legend>Category</legend>
              <div className="sc-pick-row">
                {ROUTE_PICKS.map((k) => {
                  const r = ROUTES.find((x) => x.key === k);
                  return <button key={k} type="button" className="sc-chip" aria-pressed={routeKey === k} onClick={() => chooseRoute(k)}>{r.label.split(" / ")[0].replace("Extension of Approval based on self-disclosure", "EoA · self-disclosure")}</button>;
                })}
              </div>
              <label className="sc-select">
                <span>All {ROUTES.length} categories</span>
                <select value={routeKey} onChange={(e) => chooseRoute(e.target.value)}>
                  {ROUTES.map((r) => <option key={r.key} value={r.key}>{r.label}</option>)}
                </select>
              </label>
            </fieldset>
            <p className="sc-provenance">
              Illustrative snapshot of rule set {RULESET.id} {RULESET.revision} ({RULESET.source}). The workspace reads the
              live rule set from the API.{route.note ? ` ${route.note}.` : ""}
            </p>
          </div>

          <figure className="sc-route-figure">
            <svg viewBox={`0 0 ${geo.w} ${geo.h}`} role="img" aria-labelledby="sc-route-desc" className={vertical ? "is-vertical" : ""}>
              <title id="sc-route-desc">
                {`Route for ${route.label}: ${stations.map((s) => `${s.title}${s.conditional ? " (as applicable)" : ""}`).join(", then ")}.`}
                {scrutiny >= 0 ? " A deficiency branch returns from scrutiny to the institution and back to re-scrutiny." : " No scrutiny stage, so no deficiency branch."}
              </title>
              <defs>
                <pattern id="sc-iso-grid" width="34" height="20" patternUnits="userSpaceOnUse">
                  <path d="M0 10 L17 0 L34 10 L17 20 Z" className="sc-iso-cell" />
                </pattern>
              </defs>
              <rect x="0" y="0" width={geo.w} height={geo.h} fill="url(#sc-iso-grid)" className="sc-iso-ground" />
              {stations.slice(0, -1).map((s, i) => {
                const [x1, y1] = geo.at(i), [x2, y2] = geo.at(i + 1);
                const dashed = stations[i + 1].conditional || s.conditional;
                return <path key={`seg-${i}`} className={`sc-route-seg${dashed ? " is-conditional" : ""}${i < index ? " is-before" : ""}`} d={`M${x1} ${y1} L${x2} ${y2}`} />;
              })}
              {scrutiny >= 0 && (() => {
                const [x, y] = geo.at(scrutiny);
                // a loop below (wide) or to the left (narrow) of scrutiny: deficiency → response → re-scrutiny
                const d = vertical
                  ? `M${x - 30} ${y + 6} C ${x - 110} ${y + 10}, ${x - 120} ${y + 70}, ${x - 80} ${y + 80} C ${x - 40} ${y + 90}, ${x - 20} ${y + 50}, ${x - 8} ${y + 22}`
                  : `M${x - 24} ${y + 26} C ${x - 40} ${y + 120}, ${x + 10} ${y + 150}, ${x + 60} ${y + 150} C ${x + 120} ${y + 150}, ${x + 90} ${y + 70}, ${x + 30} ${y + 24}`;
                const lx = vertical ? x - 128 : x + 76, ly = vertical ? y + 112 : y + 152;
                return (
                  <g className="sc-branch">
                    <path className="sc-branch-path" d={d} />
                    <ClockGlyph x={vertical ? x - 80 : x + 60} y={vertical ? y + 80 : y + 150} />
                    <text x={lx} y={ly} className="sc-svg-label small">Deficiency → response</text>
                    <text x={lx} y={ly + 16} className="sc-svg-caption">re-scrutiny · institution clock 15 d</text>
                  </g>
                );
              })()}
              {(() => {
                const [x1, y1] = geo.at(0), [x2, y2] = geo.at(1);
                return <ClockGlyph x={(x1 + x2) / 2} y={(y1 + y2) / 2} />;
              })()}
              {stations.map((s, i) => {
                const [x, y] = geo.at(i);
                const sel = i === index;
                const tx = vertical ? x + 62 : x, ty = vertical ? y - 4 : y - 64;
                return (
                  <g key={`${s.code}-${i}`} className={`sc-station${sel ? " is-selected" : ""}`}>
                    <g className="sc-station-body" transform={`translate(0 ${sel && !reduced ? -12 : 0})`}>
                      <Slab x={x} y={y} lifted={sel} selected={sel} conditional={s.conditional} built={s.built} />
                    </g>
                    {s.built !== "illustrative" && <DocGlyph x={vertical ? x - 2 : x + 44} y={vertical ? y - 44 : y - 30} />}
                    <text x={tx} y={ty} textAnchor={vertical ? "start" : "middle"} className="sc-svg-label">{s.title}</text>
                    <text x={tx} y={ty + 18} textAnchor={vertical ? "start" : "middle"} className="sc-svg-caption">{BUILT_LABEL[s.built].split(" · ")[0]}</text>
                  </g>
                );
              })}
            </svg>
            <ol className="sc-station-index" aria-label="Stages in this route">
              {stations.map((s, i) => (
                <li key={`${s.code}-${i}`}>
                  <button type="button" aria-pressed={i === index} onClick={() => pick(i)}>
                    <span className="sc-mono">{String(i + 1).padStart(2, "0")}</span> {s.title}
                  </button>
                </li>
              ))}
            </ol>
            <figcaption>
              <span><i className="sc-key-doc" aria-hidden="true" /> evidence handled in the workspace</span>
              <span><i className="sc-key-clock" aria-hidden="true" /> clock: {CLOCKS[0].days}-day internal processing · demo assumption</span>
              <span><i className="sc-key-dash" aria-hidden="true" /> dashed: as applicable</span>
            </figcaption>
          </figure>

          <aside className="sc-station-detail" aria-label="Selected stage" aria-live="polite">
            <p className="sc-kicker">Stage {index + 1} of {n}{st.conditional ? " · as applicable" : ""}</p>
            <h3>{st.title}</h3>
            <p className={`sc-built built-${st.built}`}>{BUILT_LABEL[st.built]}</p>
            <dl>
              <div><dt>Purpose</dt><dd>{st.purpose}</dd></div>
              <div><dt>Evidence</dt><dd>{st.evidence}</dd></div>
              <div><dt>Responsible</dt><dd>{st.actor}</dd></div>
              <div><dt>In this prototype</dt><dd>{st.builtNote}</dd></div>
            </dl>
            <div className="sc-detail-controls">
              <button type="button" className="sc-button small" onClick={() => pick(index - 1)} disabled={index === 0}>Previous stage</button>
              <button type="button" className="sc-button small" onClick={() => pick(index + 1)} disabled={index === n - 1}>Next stage</button>
              {pinned && !reduced && <button type="button" className="sc-text-button" onClick={follow}>Follow scroll</button>}
            </div>
            <button type="button" className="sc-link-button" onClick={onInspect}>Inspect a real case in the workspace <span aria-hidden="true">↗</span></button>
          </aside>
        </div>
      </div>
    </section>
  );
}
