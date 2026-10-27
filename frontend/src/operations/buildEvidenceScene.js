import * as THREE from "three";

// The three assurance layers as three different objects, because they answer three different questions:
//   continuity - a run of interlocking links (a hash chain); a broken chain shows one link pulled out of line,
//   witness    - a seal on a plinth; a same-machine demo witness is drawn as an open (ring) seal,
//   replay     - a loop that returns to its start (events replayed into the read models).
// Colour is the recorded state only: teal checked, brass anchored, amber recorded-not-independent,
// red broken, stone not run / unknown. The figure is fixed; nothing moves unless the selection changes.
// The link count is a fixed motif, not the number of ledger entries: no event sequence is drawn from a count.
const STATE = { checked: 0x6fb5ab, anchored: 0xe2c88f, recorded: 0xe7a04a, broken: 0xec8170, pending: 0xe7a04a, unknown: 0x6d6a64 };
const PLINTH = 0x26282d;

export function buildEvidenceScene({ root, records }) {
  const textures = [];
  const stations = [];
  const metal = (color, emissive = 0) => new THREE.MeshStandardMaterial({ color, metalness: 0.55, roughness: 0.38, emissive });
  const label = (text, y) => {
    const c = document.createElement("canvas");
    c.width = 512; c.height = 96;
    const ctx = c.getContext("2d");
    ctx.fillStyle = "#bdb7ac";
    ctx.font = "500 40px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(text, 256, 60);
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    textures.push(t);
    const m = new THREE.Mesh(new THREE.PlaneGeometry(2.2, 0.41), new THREE.MeshBasicMaterial({ map: t, transparent: true, depthWrite: false }));
    m.position.set(0, y, 0.9);
    return m;
  };

  const layers = records.slice(0, 3);
  layers.forEach((r, i) => {
    const g = new THREE.Group();
    g.position.x = (i - 1) * 2.7;
    root.add(g);
    const color = STATE[r.state] ?? STATE.unknown;
    const base = new THREE.Mesh(new THREE.CylinderGeometry(1.05, 1.15, 0.18, 48), metal(PLINTH));
    base.position.y = -1.05;
    g.add(base);
    const body = new THREE.Group();
    g.add(body);
    if (i === 0) {
      for (let k = 0; k < 4; k++) {
        const link = new THREE.Mesh(new THREE.TorusGeometry(0.32, 0.075, 12, 36), metal(color));
        link.scale.set(1, 1.55, 1);
        link.position.set(0, -0.55 + k * 0.42, 0);
        link.rotation.y = k % 2 ? Math.PI / 2 : 0;
        if (r.state === "broken" && k === 2) { link.position.x = 0.38; link.rotation.z = 0.5; }
        body.add(link);
      }
    } else if (i === 1) {
      const demo = r.state === "recorded";
      const seal = new THREE.Mesh(demo ? new THREE.TorusGeometry(0.62, 0.11, 16, 64) : new THREE.CylinderGeometry(0.66, 0.66, 0.16, 64), metal(color));
      if (!demo) seal.rotation.x = Math.PI / 2;
      seal.position.y = 0.25;
      body.add(seal);
      const boss = new THREE.Mesh(new THREE.CylinderGeometry(0.28, 0.28, 0.24, 48), metal(color));
      boss.rotation.x = Math.PI / 2;
      boss.position.set(0, 0.25, 0.04);
      body.add(boss);
      const stem = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.9, 0.16), metal(PLINTH));
      stem.position.y = -0.55;
      body.add(stem);
    } else {
      const loop = new THREE.Mesh(new THREE.TorusGeometry(0.62, 0.09, 16, 72, Math.PI * 1.72), metal(color));
      loop.position.y = 0.2;
      loop.rotation.z = 0.5;
      body.add(loop);
      const head = new THREE.Mesh(new THREE.ConeGeometry(0.18, 0.34, 24), metal(color));
      head.position.set(0.62 * Math.cos(0.5 + Math.PI * 1.72), 0.2 + 0.62 * Math.sin(0.5 + Math.PI * 1.72), 0);
      head.rotation.z = 0.5 + Math.PI * 1.72;
      body.add(head);
    }
    g.add(label(r.label, -1.55));
    stations.push({ g, body });
  });

  return {
    textures,
    update(selected, camera, aspect) {
      const wide = aspect < 2.3 ? 2.3 / aspect : 1;
      camera.position.set(0.6, 1.5, 8.6 * wide);
      camera.lookAt(0, -0.2, 0);
      stations.forEach(({ g, body }, i) => {
        const on = i === selected;
        body.position.y = on ? 0.18 : 0;
        g.traverse((o) => { if (o.material?.emissive) { o.material.emissive.setHex(on ? 0x2a2214 : 0); } });
      });
    },
  };
}
