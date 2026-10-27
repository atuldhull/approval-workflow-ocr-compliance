import { useEffect, useRef } from "react";
import * as THREE from "three";
import { buildEvidenceScene } from "./buildEvidenceScene.js";

// A demand-rendered scene: it draws only when its input changes (selection, size, visibility, loaded data).
// There is no animation loop and no scroll listener. Everything it allocates is disposed on unmount.
export default function WorldScene({ records, selected, reduced, onFailure }) {
  const host = useRef(null);
  const invalidate = useRef(() => {});
  const live = useRef({});
  live.current = { selected, reduced };
  const signature = JSON.stringify(records.map((r) => [r.id, r.state]));
  useEffect(() => invalidate.current(), [selected, reduced]);

  useEffect(() => {
    const el = host.current;
    let renderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "low-power" });
    } catch {
      onFailure();
      return undefined;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, window.innerWidth < 700 ? 1 : 1.5));
    renderer.setClearColor(0, 0);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.05;
    el.appendChild(renderer.domElement);
    renderer.domElement.setAttribute("aria-hidden", "true");

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 100);
    const root = new THREE.Group();
    scene.add(root);
    scene.add(new THREE.HemisphereLight(0xf3eee4, 0x0d0e10, 1.1));
    const key = new THREE.DirectionalLight(0xffffff, 2.4);
    key.position.set(-4, 6, 6);
    scene.add(key);
    const rim = new THREE.DirectionalLight(0xc9ab72, 1.4);
    rim.position.set(5, 2, -4);
    scene.add(rim);

    let disposed = false, visible = true, raf = 0, lastState = "", frames = 0;
    const evidence = buildEvidenceScene({ root, records });

    function draw() {
      raf = 0;
      if (disposed || !visible || document.hidden) return;
      const { selected: sel, reduced: still } = live.current;
      const state = [sel, still, el.clientWidth, el.clientHeight].join(",");
      if (state === lastState) return;
      lastState = state;
      evidence.update(sel, camera, el.clientWidth / Math.max(1, el.clientHeight));
      renderer.render(scene, camera);
      frames += 1;
      el.dataset.rendered = "true";
      el.dataset.frames = String(frames);
    }
    const schedule = () => { if (!raf && !disposed && visible && !document.hidden) raf = requestAnimationFrame(draw); };
    invalidate.current = schedule;

    el.dataset.recordStates = JSON.stringify(records.map((r) => r.state));
    const resize = () => {
      const w = el.clientWidth, h = el.clientHeight;
      renderer.setSize(w, h, false);
      camera.aspect = w / Math.max(1, h);
      camera.updateProjectionMatrix();
      lastState = "";
      schedule();
    };
    const ro = new ResizeObserver(resize);
    ro.observe(el);
    resize();
    const io = new IntersectionObserver(([e]) => {
      visible = e.isIntersecting;
      if (visible) schedule(); else { cancelAnimationFrame(raf); raf = 0; }
    }, { rootMargin: "60px" });
    io.observe(el);
    const visibility = () => { if (document.hidden) { cancelAnimationFrame(raf); raf = 0; } else { lastState = ""; schedule(); } };
    const lost = (e) => { e.preventDefault(); onFailure(); };
    document.addEventListener("visibilitychange", visibility);
    renderer.domElement.addEventListener("webglcontextlost", lost);
    schedule();

    return () => {
      disposed = true;
      invalidate.current = () => {};
      cancelAnimationFrame(raf);
      io.disconnect();
      ro.disconnect();
      document.removeEventListener("visibilitychange", visibility);
      renderer.domElement.removeEventListener("webglcontextlost", lost);
      scene.traverse((o) => {
        o.geometry?.dispose();
        if (o.material) (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => { m.map?.dispose(); m.dispose(); });
      });
      evidence.textures.forEach((t) => t.dispose());
      renderer.dispose();
      renderer.forceContextLoss();
      renderer.domElement.remove();
    };
  }, [signature]); // eslint-disable-line react-hooks/exhaustive-deps

  return <div className="operations-canvas" ref={host} data-scene="audit" />;
}
