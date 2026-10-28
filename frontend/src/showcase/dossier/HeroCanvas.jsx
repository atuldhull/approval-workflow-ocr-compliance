import { useEffect, useRef } from "react";
import * as THREE from "three";
import { buildDossierScene } from "./scene.js";

// The single WebGL canvas of the showcase. It renders only when asked: a scroll moves the target progress, a short
// damped catch-up runs until the pose settles, then the loop stops. At rest nothing is drawn (data-frames stays put).
export default function HeroCanvas({ progressRef, subscribe, reduced, narrow, onFailure }) {
  const host = useRef(null);
  useEffect(() => {
    const el = host.current;
    let renderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
    } catch {
      onFailure?.();
      return undefined;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, narrow ? 1.5 : 1.75));
    renderer.setClearColor(0x000000, 0);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.05;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.domElement.setAttribute("aria-hidden", "true");
    el.appendChild(renderer.domElement);

    const world = buildDossierScene(renderer, { narrow });
    let current = progressRef.current, raf = 0, frames = 0, visible = true, disposed = false, ready = false;

    const draw = () => {
      raf = 0;
      if (disposed || !ready || !visible || document.hidden) return;
      const target = progressRef.current;
      const diff = target - current;
      current = reduced || Math.abs(diff) < 0.0006 ? target : current + diff * 0.16;
      world.update(current);
      renderer.render(world.scene, world.camera);
      frames++;
      el.dataset.frames = String(frames);
      el.dataset.pose = current.toFixed(3);
      if (current !== target) raf = requestAnimationFrame(draw);
    };
    const invalidate = () => { if (!raf && !disposed) raf = requestAnimationFrame(draw); };

    const resize = () => {
      const w = el.clientWidth, h = el.clientHeight;
      renderer.setSize(w, h, false);
      world.resize(w, h);
      // force one frame at the settled pose
      current = progressRef.current - 1e-9;
      invalidate();
    };
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(resize) : null;
    ro?.observe(el);
    resize();

    const io = typeof IntersectionObserver !== "undefined"
      ? new IntersectionObserver(([e]) => { visible = e.isIntersecting; if (visible) invalidate(); else { cancelAnimationFrame(raf); raf = 0; } })
      : null;
    io?.observe(el);
    const onVisibility = () => { if (!document.hidden) invalidate(); };
    document.addEventListener("visibilitychange", onVisibility);
    const unsubscribe = subscribe(invalidate);
    const lost = (e) => { e.preventDefault(); onFailure?.(); };
    renderer.domElement.addEventListener("webglcontextlost", lost);
    // Compile every shader before the first frame, off the main thread where the browser supports it, so the
    // first scroll into a new phase does not stall on a shader compile.
    const start = () => { if (disposed) return; ready = true; el.dataset.ready = "true"; current = progressRef.current - 1e-9; invalidate(); };
    const compiled = Promise.resolve(renderer.compileAsync ? renderer.compileAsync(world.scene, world.camera) : null);
    compiled.then(start, start);
    el.dataset.rendered = "true";

    return () => {
      disposed = true;
      cancelAnimationFrame(raf);
      unsubscribe();
      ro?.disconnect();
      io?.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
      renderer.domElement.removeEventListener("webglcontextlost", lost);
      renderer.domElement.remove();
      // Three r170 polls material programs during compileAsync. Releasing them before that
      // promise settles can make its timer dereference a disposed program on rapid unmount.
      // Detach immediately; finish releasing GPU resources when the compiler is done.
      const release = () => { world.dispose(); renderer.dispose(); renderer.forceContextLoss(); };
      compiled.then(release, release);
    };
  }, [progressRef, subscribe, reduced, narrow, onFailure]);
  return <div className="sc-canvas" ref={host} />;
}
