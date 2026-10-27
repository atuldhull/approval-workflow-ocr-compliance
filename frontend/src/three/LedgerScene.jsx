// 3D (WebGL, Three.js): the audit ledger as a helix of linked blocks. Loaded lazily, only on the audit
// screen, and only when the browser has WebGL. Every block is one ledger entry from the real verification
// results: anchored by the trusted checkpoint (teal), newer and not yet anchored (amber), the first broken
// link (red) and everything after it (grey). Drag or use the arrow keys to turn; hover names the entry.
import { useEffect, useRef } from "react";
import * as THREE from "three";

const COLOURS = { anchored: 0x35d0c0, newer: 0xf2b552, broken: 0xf06b7c, after: 0x3a4658, chain: 0x7cb4ff };
export const MAX_BLOCKS = 160;

export function blockState(i, { total, anchored, brokenAt }) {
  const seq = i + 1;
  if (brokenAt && seq === brokenAt) return "broken";
  if (brokenAt && seq > brokenAt) return "after";
  if (seq <= anchored) return "anchored";
  return anchored ? "newer" : "chain";
}

export default function LedgerScene({ total, anchored, brokenAt, reduced, onHover }) {
  const mount = useRef(null);
  const hoverRef = useRef(onHover);
  hoverRef.current = onHover;

  useEffect(() => {
    const host = mount.current;
    if (!host) return undefined;
    const n = Math.min(total, MAX_BLOCKS);
    const first = total - n; // when capped, show the newest entries

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "low-power" });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    host.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100);
    camera.position.set(0, 0.6, 15);
    scene.add(new THREE.AmbientLight(0xffffff, 0.55));
    const key = new THREE.DirectionalLight(0xffffff, 1.1);
    key.position.set(4, 6, 8);
    scene.add(key);
    const rim = new THREE.DirectionalLight(0x7cb4ff, 0.6);
    rim.position.set(-6, -2, -4);
    scene.add(rim);

    const group = new THREE.Group();
    scene.add(group);
    const geo = new THREE.BoxGeometry(0.95, 0.42, 0.42);
    const materials = {};
    const mat = (state) => (materials[state] ??= new THREE.MeshStandardMaterial({
      color: COLOURS[state], roughness: 0.42, metalness: 0.15,
      emissive: COLOURS[state], emissiveIntensity: state === "after" ? 0.02 : 0.12,
    }));
    const height = Math.max(4, n * 0.2);
    const blocks = [];
    const points = [];
    for (let i = 0; i < n; i += 1) {
      const a = i * 0.52;
      const p = new THREE.Vector3(Math.cos(a) * 3.1, (i / Math.max(1, n - 1)) * height - height / 2, Math.sin(a) * 3.1);
      const state = blockState(first + i, { total, anchored, brokenAt });
      const m = new THREE.Mesh(geo, mat(state));
      m.position.copy(p);
      m.rotation.y = -a;
      m.userData = { seq: first + i + 1, state };
      group.add(m);
      blocks.push(m);
      points.push(p);
    }
    const linkGeo = new THREE.BufferGeometry().setFromPoints(points);
    const link = new THREE.Line(linkGeo, new THREE.LineBasicMaterial({ color: 0x5b6b80, transparent: true, opacity: 0.7 }));
    group.add(link);
    group.rotation.x = 0.18;

    let w = 0;
    let h = 0;
    const fit = () => {
      w = host.clientWidth || 600;
      h = host.clientHeight || 360;
      renderer.setSize(w, h, false);
      renderer.domElement.style.width = "100%";
      renderer.domElement.style.height = "100%";
      camera.aspect = w / h;
      camera.position.z = Math.max(14, height * 1.75 + (w < 520 ? 9 : 5));
      camera.updateProjectionMatrix();
    };
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(host);

    // interaction
    const ray = new THREE.Raycaster();
    const ndc = new THREE.Vector2();
    let drag = null;
    let hovered = null;
    let spinVel = reduced ? 0 : 0.0028;
    const setHover = (m) => {
      if (hovered === m) return;
      if (hovered) hovered.scale.setScalar(1);
      hovered = m;
      if (m) m.scale.setScalar(1.35);
      hoverRef.current?.(m ? m.userData : null);
    };
    const onDown = (e) => {
      drag = { x: e.clientX, y: e.clientY, ry: group.rotation.y, rx: group.rotation.x };
      host.setPointerCapture?.(e.pointerId);
    };
    const onMove = (e) => {
      const r = host.getBoundingClientRect();
      if (drag) {
        group.rotation.y = drag.ry + (e.clientX - drag.x) * 0.008;
        group.rotation.x = Math.max(-0.6, Math.min(0.8, drag.rx + (e.clientY - drag.y) * 0.005));
        return;
      }
      ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
      ray.setFromCamera(ndc, camera);
      setHover(ray.intersectObjects(blocks, false)[0]?.object ?? null);
    };
    const onUp = () => {
      drag = null;
    };
    const onLeave = () => {
      drag = null;
      setHover(null);
    };
    const onKey = (e) => {
      if (e.key === "ArrowLeft") group.rotation.y -= 0.25;
      else if (e.key === "ArrowRight") group.rotation.y += 0.25;
      else if (e.key === "ArrowUp") group.rotation.x = Math.max(-0.6, group.rotation.x - 0.15);
      else if (e.key === "ArrowDown") group.rotation.x = Math.min(0.8, group.rotation.x + 0.15);
      else return;
      e.preventDefault();
      spinVel = 0;
    };
    host.addEventListener("pointerdown", onDown);
    host.addEventListener("pointermove", onMove);
    host.addEventListener("pointerup", onUp);
    host.addEventListener("pointerleave", onLeave);
    host.addEventListener("keydown", onKey);

    // render only while visible
    let visible = true;
    const io = new IntersectionObserver(([e]) => {
      visible = e.isIntersecting;
    });
    io.observe(host);
    let frame = 0;
    const tick = () => {
      frame = requestAnimationFrame(tick);
      if (!visible || document.hidden) return;
      if (!drag) group.rotation.y += spinVel;
      renderer.render(scene, camera);
    };
    tick();

    return () => {
      cancelAnimationFrame(frame);
      io.disconnect();
      ro.disconnect();
      host.removeEventListener("pointerdown", onDown);
      host.removeEventListener("pointermove", onMove);
      host.removeEventListener("pointerup", onUp);
      host.removeEventListener("pointerleave", onLeave);
      host.removeEventListener("keydown", onKey);
      geo.dispose();
      linkGeo.dispose();
      link.material.dispose();
      Object.values(materials).forEach((m) => m.dispose());
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [total, anchored, brokenAt, reduced]);

  return <div className="ledger-canvas" ref={mount} />;
}
