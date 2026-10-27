// The motion layer (see MOTION.md). Everything here degrades to "no motion": without matchMedia or
// IntersectionObserver (tests, old browsers) and under prefers-reduced-motion, content is simply shown.
import { useEffect, useState } from "react";

const PAUSE_KEY = "awoc.motion";
const PAUSE_EVENT = "awoc:motion-changed";

export function motionPaused() {
  try {
    return localStorage.getItem(PAUSE_KEY) === "off";
  } catch {
    return false;
  }
}

// The in-app "Pause animations" switch: stops every loop and auto-rotation, like the OS setting.
export function setMotionPaused(paused) {
  try {
    localStorage.setItem(PAUSE_KEY, paused ? "off" : "on");
  } catch {
    /* the switch still works for this page view */
  }
  window.dispatchEvent(new Event(PAUSE_EVENT));
}

export function prefersReducedMotion() {
  if (typeof window === "undefined" || !window.matchMedia) return true;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches || motionPaused();
}

export function useReducedMotion() {
  const [reduced, setReduced] = useState(prefersReducedMotion);
  useEffect(() => {
    if (!window.matchMedia) return undefined;
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const on = () => setReduced(prefersReducedMotion());
    mq.addEventListener?.("change", on);
    window.addEventListener(PAUSE_EVENT, on);
    return () => {
      mq.removeEventListener?.("change", on);
      window.removeEventListener(PAUSE_EVENT, on);
    };
  }, []);
  return reduced;
}

// html.motion switches the reveal styles on. Only set when motion is allowed, so nothing is ever hidden
// for a visitor who cannot see it arrive.
export function useMotionRoot() {
  const reduced = useReducedMotion();
  useEffect(() => {
    document.documentElement.classList.toggle("motion", !reduced);
  }, [reduced]);
  return reduced;
}

// Writes the scroll offset to --scroll on <html>, at most once per frame, for parallax backplates.
export function useScrollVar() {
  useEffect(() => {
    if (prefersReducedMotion()) return undefined;
    let frame = 0;
    const write = () => {
      frame = 0;
      document.documentElement.style.setProperty("--scroll", String(window.scrollY));
    };
    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(write);
    };
    write();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      window.removeEventListener("scroll", onScroll);
      if (frame) cancelAnimationFrame(frame);
    };
  }, []);
}

// Staggered, once-only reveal of the panels inside `root`. Re-scans when `key` changes (a new world).
export function useReveal(rootRef, key) {
  useEffect(() => {
    const root = rootRef.current;
    if (!root) return undefined;
    const targets = () => [...root.querySelectorAll("[data-reveal], .card, .not-available")];
    if (!window.IntersectionObserver || prefersReducedMotion()) {
      targets().forEach((el) => el.classList.add("is-in"));
      return undefined;
    }
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) {
            e.target.classList.add("is-in");
            io.unobserve(e.target);
          }
        });
      },
      { rootMargin: "0px 0px -6% 0px", threshold: 0.04 },
    );
    // Bindings belong to this observer instance: a DOM flag would outlive it (StrictMode runs effects
    // twice) and leave panels hidden forever.
    const bound = new WeakSet();
    const observe = () => {
      targets().forEach((el, i) => {
        if (bound.has(el) || el.classList.contains("is-in")) return;
        bound.add(el);
        el.style.setProperty("--i", String(Math.min(i, 8)));
        io.observe(el);
      });
    };
    observe();
    // panels that arrive later (after data loads) are picked up too
    const mo = new MutationObserver(observe);
    mo.observe(root, { childList: true, subtree: true });
    // Fail-safe: whatever has not been revealed after a moment is shown anyway. Motion must never hide content.
    const safety = setInterval(() => {
      targets().forEach((el) => {
        if (!el.classList.contains("is-in") && el.getBoundingClientRect().top < window.innerHeight * 1.5) el.classList.add("is-in");
      });
    }, 2500);
    return () => {
      io.disconnect();
      mo.disconnect();
      clearInterval(safety);
    };
  }, [rootRef, key]);
}

// 0 when the element's top is at the bottom of the viewport, 1 when its centre reaches the viewport's centre.
export function useScrollProgress(ref) {
  const [p, setP] = useState(1);
  useEffect(() => {
    if (prefersReducedMotion()) return undefined;
    let frame = 0;
    const measure = () => {
      frame = 0;
      const el = ref.current;
      if (!el) return;
      const r = el.getBoundingClientRect();
      const vh = window.innerHeight || 1;
      const centre = r.top + r.height / 2;
      setP(Math.max(0, Math.min(1, (vh - centre) / (vh / 2))));
    };
    const on = () => {
      if (!frame) frame = requestAnimationFrame(measure);
    };
    measure();
    window.addEventListener("scroll", on, { passive: true });
    window.addEventListener("resize", on);
    return () => {
      window.removeEventListener("scroll", on);
      window.removeEventListener("resize", on);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [ref]);
  return p;
}

// Which arrival each screen uses (MOTION.md, "World transitions").
export const WORLDS = {
  overview: { motion: "zoom", world: "mission" },
  dashboard: { motion: "pan", world: "control" },
  applications: { motion: "slide", world: "cases" },
  inbox: { motion: "drift", world: "signal" },
  alerts: { motion: "drift", world: "signal" },
  documents: { motion: "scan", world: "evidence" },
  ocr: { motion: "scan", world: "evidence" },
  evc: { motion: "rewind", world: "field" },
  compliance: { motion: "collapse", world: "field" },
  audit: { motion: "iris", world: "chamber" },
  delivery: { motion: "tunnel", world: "traffic" },
  scorecard: { motion: "rise", world: "board" },
};
