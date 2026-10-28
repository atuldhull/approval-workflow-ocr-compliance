import { useCallback, useEffect, useRef, useState } from "react";
import { useReducedMotion } from "../motion.js";
import { CHAPTERS, TOUR } from "./data.js";
import { SHOWCASE_HASH, enterWorkspace } from "./entry.jsx";
import Hero from "./Hero.jsx";
import Journey from "./Journey.jsx";
import Audit from "./Audit.jsx";
import Tour from "./Tour.jsx";
import { Challenge, Deadlines, Evidence, WorkspaceReveal } from "./Chapters.jsx";
import { isNarrow, rememberFlat, rememberedFlat, webglAvailable } from "./scroll.js";
import "./showcase.css";
import "./luxury.css";

// #showcase                → top
// #showcase/<chapter>      → that chapter (challenge, route, evidence, deadlines, audit, workspace)
// #showcase/tour/<n>       → the guided tour, paused at step n (1-based)
export function parseShowcaseHash(hash) {
  const rest = hash.slice(SHOWCASE_HASH.length).replace(/^\//, "").split("?")[0];
  const [a, b] = rest.split("/");
  if (a === "tour") {
    const n = Number.parseInt(b, 10);
    return { tour: Number.isFinite(n) ? Math.min(TOUR.length, Math.max(1, n)) - 1 : 0 };
  }
  return { chapter: CHAPTERS.some((c) => c.id === a) ? a : null };
}

const replaceHash = (h) => history.replaceState(history.state, "", `${window.location.pathname}${window.location.search}${h}`);

export default function Showcase() {
  const reduced = useReducedMotion();
  const [spatial, setSpatial] = useState(() => webglAvailable() && !rememberedFlat());
  const [vertical, setVertical] = useState(isNarrow);
  const [tour, setTour] = useState(() => {
    const t = parseShowcaseHash(window.location.hash).tour;
    return t === undefined ? null : { step: t, playing: false };
  });
  const [current, setCurrent] = useState(null);
  const startButton = useRef(null);

  const go = useCallback((target, focus = true) => {
    const behavior = reduced ? "auto" : "smooth";
    let heading = null;
    if (target === "top") {
      window.scrollTo?.({ top: 0, behavior });
      heading = document.getElementById("sc-title");
    } else if (target === "hero-open") {
      const hero = document.getElementById("top");
      const travel = hero ? hero.offsetHeight - window.innerHeight : 0;
      window.scrollTo?.({ top: Math.max(0, (hero?.offsetTop || 0) + travel * 0.5), behavior });
      heading = document.getElementById("sc-title");
    } else {
      const el = document.getElementById(target);
      if (el) window.scrollTo?.({ top: el.offsetTop, behavior });
      heading = document.getElementById(`${target}-title`);
    }
    if (focus) heading?.focus({ preventScroll: true });
  }, [reduced]);

  // Title, initial position and chapter deep links.
  useEffect(() => {
    const before = document.title;
    document.title = "How it works · AICTE Approval Operations";
    const { chapter, tour: t } = parseShowcaseHash(window.location.hash);
    const first = requestAnimationFrame(() => {
      if (chapter) go(chapter);
      else if (t !== undefined) go(TOUR[t].target);
      else window.scrollTo?.({ top: 0 });
    });
    const onHash = () => {
      const p = parseShowcaseHash(window.location.hash);
      if (p.chapter) go(p.chapter);
    };
    window.addEventListener("hashchange", onHash);
    return () => { cancelAnimationFrame(first); window.removeEventListener("hashchange", onHash); document.title = before; };
  }, [go]);

  useEffect(() => {
    const on = () => setVertical((v) => (isNarrow() !== v ? !v : v));
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);

  // Which chapter is on screen, for the chapter index (aria-current).
  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return undefined;
    const io = new IntersectionObserver((entries) => {
      entries.forEach((e) => { if (e.isIntersecting) setCurrent(e.target.id); });
    }, { rootMargin: "-45% 0px -50% 0px" });
    CHAPTERS.forEach((c) => { const el = document.getElementById(c.id); if (el) io.observe(el); });
    return () => io.disconnect();
  }, []);

  const startTour = () => { setTour({ step: 0, playing: true }); replaceHash(`${SHOWCASE_HASH}/tour/1`); go(TOUR[0].target); };
  const stepTour = useCallback((i) => {
    const step = Math.max(0, Math.min(TOUR.length - 1, i));
    setTour((t) => (t ? { ...t, step } : t));
    replaceHash(`${SHOWCASE_HASH}/tour/${step + 1}`);
    go(TOUR[step].target);
  }, [go]);
  const playTour = useCallback((playing) => setTour((t) => (t ? { ...t, playing } : t)), []);
  const exitTour = useCallback(() => {
    setTour(null);
    replaceHash(SHOWCASE_HASH);
    requestAnimationFrame(() => startButton.current?.focus({ preventScroll: true }));
  }, []);
  const finishTour = useCallback(() => enterWorkspace(), []);

  const toggleSpatial = () => {
    const next = !spatial;
    rememberFlat(!next);
    setSpatial(next && webglAvailable());
  };
  const onFailure = useCallback(() => setSpatial(false), []);

  return (
    <div className={`sc-root${tour ? " has-tour" : ""}`} data-motion={reduced ? "reduced" : "full"} data-render={spatial ? "spatial" : "standard"}>
      <header className="sc-bar">
        <a className="sc-skip" href="#showcase-main" onClick={(e) => { e.preventDefault(); enterWorkspace(); }}>Skip to the workspace</a>
        <a className="sc-brand" href={SHOWCASE_HASH} onClick={(e) => { e.preventDefault(); go("top"); replaceHash(SHOWCASE_HASH); }}>
          <img src="/approval-mark.svg" alt="" width="22" height="26" />
          <span><strong>AICTE Approval Operations</strong><small>Workflow · OCR · Compliance</small></span>
        </a>
        <nav className="sc-index" aria-label="Chapters">
          <ol>
            {CHAPTERS.map((c) => (
              <li key={c.id}>
                <a href={`${SHOWCASE_HASH}/${c.id}`} aria-current={current === c.id ? "true" : undefined}>
                  <span className="sc-mono">{c.n}</span><span className="sc-index-title">{c.title}</span>
                </a>
              </li>
            ))}
          </ol>
        </nav>
        <div className="sc-bar-actions">
          <button ref={startButton} type="button" className="sc-button small" onClick={startTour} disabled={Boolean(tour)}><span className="sc-long">Guided </span>tour</button>
          <button type="button" className="sc-button small primary" onClick={() => enterWorkspace()}><span className="sc-long">Open </span>workspace</button>
        </div>
        <p className="sc-disclosure"><span className="sc-long">Independent SIH 2026 prototype · illustrative sample material · not the AICTE portal and not connected to it</span><span className="sc-short">Independent SIH prototype · sample material · not the AICTE portal</span></p>
      </header>

      <main className="sc-main" id="showcase-main">
        <Hero reduced={reduced} spatial={spatial} onToggleSpatial={toggleSpatial} onFailure={onFailure}
          onExplore={() => go("challenge")} onWorkspace={() => enterWorkspace()} />
        <Challenge reduced={reduced} />
        <Journey reduced={reduced} vertical={vertical} onInspect={() => enterWorkspace("applications")} />
        <Evidence reduced={reduced} />
        <Deadlines reduced={reduced} />
        <Audit reduced={reduced} />
        <WorkspaceReveal reduced={reduced} onEnter={() => enterWorkspace()} onInspect={() => enterWorkspace("applications")} />
      </main>

      <footer className="sc-footer">
        <p>AICTE Approval Operations is an independent prototype built for Smart India Hackathon 2026 (problem statement 26262).
          It is not the AICTE portal, issues no approvals, and holds no AICTE records. Every name, number and document on this
          page is illustrative sample material.</p>
      </footer>

      {tour && <Tour step={tour.step} playing={tour.playing} onStep={stepTour} onPlay={playTour} onExit={exitTour} onFinish={finishTour} />}
    </div>
  );
}
