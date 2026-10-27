// Scroll plumbing for the showcase. Native scrolling only: nothing intercepts wheel or touch.
//
// One passive listener per section, coalesced into one requestAnimationFrame. Continuous progress goes straight to
// a CSS custom property (--p) and to an optional callback; React state changes only when a discrete step changes.
import { useEffect, useRef, useState } from "react";

export const clamp01 = (v) => (v < 0 ? 0 : v > 1 ? 1 : v);
export const smooth = (v) => { const t = clamp01(v); return t * t * (3 - 2 * t); };
// Progress of `p` through the window [a, b], eased.
export const span = (p, a, b) => smooth((p - a) / (b - a));

// 0 when the section's top reaches the top of the viewport, 1 when its bottom reaches the bottom.
export function sectionProgress(el) {
  const r = el.getBoundingClientRect();
  const travel = r.height - (window.innerHeight || 1);
  if (travel <= 0) return r.top <= 0 ? 1 : 0;
  return clamp01(-r.top / travel);
}

export function useSectionProgress(ref, { steps = 0, onProgress, enabled = true } = {}) {
  const [step, setStep] = useState(0);
  const stepRef = useRef(0);
  const cb = useRef(onProgress);
  cb.current = onProgress;
  useEffect(() => {
    const el = ref.current;
    if (!el || !enabled) {
      el?.style.setProperty("--p", "1");
      return undefined;
    }
    let frame = 0;
    const update = () => {
      frame = 0;
      const p = sectionProgress(el);
      el.style.setProperty("--p", p.toFixed(4));
      el.dataset.progress = p.toFixed(3);
      cb.current?.(p);
      if (steps) {
        const s = Math.min(steps - 1, Math.floor(p * steps));
        if (s !== stepRef.current) { stepRef.current = s; setStep(s); }
      }
    };
    const on = () => { if (!frame) frame = requestAnimationFrame(update); };
    update();
    window.addEventListener("scroll", on, { passive: true });
    window.addEventListener("resize", on);
    return () => {
      window.removeEventListener("scroll", on);
      window.removeEventListener("resize", on);
      cancelAnimationFrame(frame);
    };
  }, [ref, steps, enabled]);
  return step;
}

// WebGL2 present and not switched off by the visitor.
export function webglAvailable() {
  if (typeof window === "undefined" || typeof window.WebGL2RenderingContext === "undefined") return false;
  try {
    const c = document.createElement("canvas");
    const gl = c.getContext("webgl2");
    gl?.getExtension("WEBGL_lose_context")?.loseContext();
    return Boolean(gl);
  } catch {
    return false;
  }
}

const FLAT_KEY = "showcase.flat";
export const rememberedFlat = () => { try { return localStorage.getItem(FLAT_KEY) === "true"; } catch { return false; } };
export const rememberFlat = (v) => { try { localStorage.setItem(FLAT_KEY, String(v)); } catch { /* this page view only */ } };

// Phones, and portrait tablets, get the portrait compositions.
export const isNarrow = () => {
  if (typeof window === "undefined") return false;
  const w = window.innerWidth || 1024, h = window.innerHeight || 768;
  return w < 760 || (w < 1100 && w / h < 0.95);
};
