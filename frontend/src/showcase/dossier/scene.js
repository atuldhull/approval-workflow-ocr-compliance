// The hero: an institutional application dossier, lit like a product shot, that opens as the page scrolls.
//
// Semantics (see SHOWCASE_REPORT.md, truth table):
//   cover opening          → an application being opened for review
//   sheets lifting apart   → documents becoming separately reviewable evidence
//   amber frames on fields → fields a person must check (not a machine verdict)
//   brass rail + plinths   → the prescribed route's milestones (an illustrative New programme route)
//   hollow ring            → a stage the rule set marks "as applicable"
//   tick marks             → elapsed time along the route
//   role plates            → who is responsible at a milestone, only where the rule set names one
//   teal threads           → which document a milestone relies on (a technical relation, not a decision)
//
// Rendering is on demand: update(p) poses everything as a pure function of progress p ∈ [0, 1], so reverse scroll
// restores every earlier frame exactly. There is no animation loop in here.
import * as THREE from "three";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { SHEET_COUNT, drawBoard, drawContactShadow, drawCover, drawDivider, drawLabel, drawSheet } from "./textures.js";

const C = {
  mocha: 0x5b4632, champagne: 0xf4d9a0, amber: 0xcb792c, ink: 0x141310,
  paper: 0xe9dfca, brass: 0xb8925a, stone: 0x2c2823, teal: 0x5aa39b, graphite: 0x23211d,
};

const smooth = (t) => (t <= 0 ? 0 : t >= 1 ? 1 : t * t * (3 - 2 * t));
const span = (p, a, b) => smooth((p - a) / (b - a));
const mix = (a, b, t) => a + (b - a) * t;

// Board and sheet sizes (scene units ≈ decimetres). Sheets keep the A4 ratio.
const BW = 2.2, BD = 3.0, BT = 0.03;
const SW = 2.0, SH = SW * 1.414, ST = 0.008;
const COVER_Z = 0.125; // the cover rests just above the sheet stack

// Milestones of the illustrative route (New programme, aph-2024-27 r1). Roles only where the rule set names one.
const MILESTONES = [
  { title: "Submitted", caption: "Built · institution files", role: "Institution" },
  { title: "Scrutiny", caption: "Built · deficiencies, re-scrutiny", role: "Scrutiny committee" },
  { title: "Expert visit", caption: "EVC · preview, sample slots", role: "Regional officer constitutes" },
  { title: "SHC", caption: "As applicable · conditional", role: "Not named in rule set", conditional: true },
  { title: "Outcome recorded", caption: "Here · AICTE decides on its portal", role: "Officers record" },
];

// Camera keyframes: [p, position, target]. Desktop composes the dossier right of the copy; narrow screens centre it.
const SHOTS = {
  wide: [
    [0.0, [2.9, 4.7, 5.5], [-1.25, -0.1, 0.05]],
    [0.28, [2.4, 6.6, 6.2], [-1.5, 0.0, -0.2]],
    [0.52, [3.7, 4.9, 8.8], [-0.55, 0.7, -0.3]],
    [0.76, [6.6, 6.0, 11.2], [2.4, 0.4, -0.1]],
    [1.0, [5.9, 8.4, 10.4], [2.2, 0.25, -0.1]],
  ],
  narrow: [
    [0.0, [0.6, 9.4, 9.0], [0.0, -0.4, -3.3]],
    [0.28, [-0.6, 9.6, 8.0], [-1.1, -0.3, -1.5]],
    [0.52, [1.2, 6.4, 9.8], [0.2, 0.5, -1.4]],
    [0.76, [1.5, 10.5, 11.8], [0.45, 0, 2.2]],
    [1.0, [1.0, 14.0, 10.8], [0.45, 0, 2.3]],
  ],
};

function shot(keys, p, pos, target) {
  let i = 0;
  while (i < keys.length - 2 && p > keys[i + 1][0]) i++;
  const [p0, a0, t0] = keys[i], [p1, a1, t1] = keys[i + 1];
  const t = smooth((p - p0) / (p1 - p0));
  pos.set(mix(a0[0], a1[0], t), mix(a0[1], a1[1], t), mix(a0[2], a1[2], t));
  target.set(mix(t0[0], t1[0], t), mix(t0[1], t1[1], t), mix(t0[2], t1[2], t));
}

function roundedRect(w, h, r, tab) {
  const s = new THREE.Shape();
  const x0 = -w / 2, y0 = -h / 2, x1 = w / 2, y1 = h / 2;
  s.moveTo(x0 + r, y0);
  s.lineTo(x1 - r, y0); s.quadraticCurveTo(x1, y0, x1, y0 + r);
  if (tab && tab.side === "right") {
    s.lineTo(x1, tab.a); s.lineTo(x1 + tab.d * 0.6, tab.a + 0.04); s.lineTo(x1 + tab.d, tab.a + 0.08);
    s.lineTo(x1 + tab.d, tab.b - 0.08); s.lineTo(x1 + tab.d * 0.6, tab.b - 0.04); s.lineTo(x1, tab.b);
  }
  s.lineTo(x1, y1 - r); s.quadraticCurveTo(x1, y1, x1 - r, y1);
  if (tab && tab.side === "top") {
    s.lineTo(tab.b, y1); s.lineTo(tab.b - 0.06, y1 + tab.d); s.lineTo(tab.a + 0.06, y1 + tab.d); s.lineTo(tab.a, y1);
  }
  s.lineTo(x0 + r, y1); s.quadraticCurveTo(x0, y1, x0, y1 - r);
  s.lineTo(x0, y0 + r); s.quadraticCurveTo(x0, y0, x0 + r, y0);
  return s;
}

// A flat rectangular frame (outline with real width), used for review markers.
function frameGeometry(w, h, t) {
  const s = new THREE.Shape();
  s.moveTo(-w / 2, -h / 2); s.lineTo(w / 2, -h / 2); s.lineTo(w / 2, h / 2); s.lineTo(-w / 2, h / 2); s.closePath();
  const hole = new THREE.Path();
  hole.moveTo(-w / 2 + t, -h / 2 + t); hole.lineTo(-w / 2 + t, h / 2 - t); hole.lineTo(w / 2 - t, h / 2 - t); hole.lineTo(w / 2 - t, -h / 2 + t); hole.closePath();
  s.holes.push(hole);
  return new THREE.ShapeGeometry(s);
}

export function buildDossierScene(renderer, { narrow = false } = {}) {
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(narrow ? 34 : 27, 1, 0.1, 80);
  const textures = [], geometries = [], materials = [];
  const own = (x, list) => { list.push(x); return x; };
  const tex = (canvas, { srgb = true, repeat } = {}) => {
    const t = own(new THREE.CanvasTexture(canvas), textures);
    if (srgb) t.colorSpace = THREE.SRGBColorSpace;
    t.anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy());
    if (repeat) { t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(repeat, repeat); }
    return t;
  };
  const mat = (o) => own(new THREE.MeshStandardMaterial(o), materials);
  const geo = (g) => own(g, geometries);

  // ── light: warm key with soft shadow, low cool-neutral fill, amber rim; a dim room for speculars ──
  const pmrem = new THREE.PMREMGenerator(renderer);
  const envRT = pmrem.fromScene(new RoomEnvironment(), 0.04);
  pmrem.dispose();
  scene.environment = envRT.texture;
  scene.environmentIntensity = 0.32;

  // a soft spot pool over the dossier gives the product-shot falloff; the directional key carries the shadows
  const pool = new THREE.SpotLight(0xffe0b0, 26, 0, 0.42, 0.95, 1.1);
  pool.position.set(-2.4, 9.5, 4.2);
  pool.target.position.set(0.2, 0, 0.1);
  scene.add(pool, pool.target);
  const key = new THREE.DirectionalLight(0xffe2b8, 1.6);
  key.position.set(-4.2, 8.5, 5.2);
  key.castShadow = true;
  key.shadow.mapSize.set(narrow ? 1024 : 2048, narrow ? 1024 : 2048);
  key.shadow.radius = 5;
  key.shadow.bias = -0.0004;
  key.shadow.normalBias = 0.02;
  Object.assign(key.shadow.camera, { left: -5, right: 9, top: 6, bottom: -6, near: 1, far: 30 });
  scene.add(key, key.target);
  key.target.position.set(1.5, 0, 0);
  const fill = new THREE.HemisphereLight(0xcfd6d2, 0x1b1712, 0.35);
  const rim = new THREE.DirectionalLight(C.amber, 2.4);
  rim.position.set(5, 2.4, -6);
  scene.add(fill, rim);

  // ── desk: receives shadow only; the page's ink background shows through ──
  const desk = new THREE.Mesh(geo(new THREE.PlaneGeometry(40, 40)), own(new THREE.ShadowMaterial({ opacity: 0.42 }), materials));
  desk.rotation.x = -Math.PI / 2;
  desk.receiveShadow = true;
  scene.add(desk);
  const contact = new THREE.Mesh(geo(new THREE.PlaneGeometry(BW * 1.55, BD * 1.45)),
    own(new THREE.MeshBasicMaterial({ map: tex(drawContactShadow(), { srgb: false }), transparent: true, depthWrite: false, opacity: 0.85 }), materials));
  contact.rotation.x = -Math.PI / 2;
  contact.position.set(0.04, 0.002, 0.06);
  scene.add(contact);

  // ── folder: back board with tab, hinged front cover with printed file label ──
  const boardMap = tex(drawBoard(), { repeat: 0.45 });
  const board = mat({ color: 0xffffff, map: boardMap, roughness: 0.84, metalness: 0 });
  const dossier = new THREE.Group();
  dossier.rotation.x = -Math.PI / 2;
  scene.add(dossier);

  const extrude = { depth: BT, bevelEnabled: true, bevelThickness: 0.006, bevelSize: 0.006, bevelSegments: 2, curveSegments: 6 };
  const back = new THREE.Mesh(geo(new THREE.ExtrudeGeometry(roundedRect(BW, BD, 0.05, { side: "top", a: 0.15, b: 0.95, d: 0.2 }), extrude)), board);
  back.castShadow = back.receiveShadow = true;
  dossier.add(back);

  // dividers: section cards with side tabs, sitting in the folder between sheet groups
  const dividerMats = [
    mat({ color: 0xffffff, map: tex(drawDivider("PART B · PREMISES", "#3c5a55")), roughness: 0.8 }),
    mat({ color: 0xffffff, map: tex(drawDivider("PART D · FINANCE", "#9a7843")), roughness: 0.8 }),
  ];
  const dividers = [0.95, 0.15].map((a, i) => {
    const g = geo(new THREE.ExtrudeGeometry(roundedRect(SW + 0.04, SH + 0.02, 0.03, { side: "right", a: a - 0.42 + i * 0.1, b: a + i * 0.1, d: 0.16 }), { depth: 0.006, bevelEnabled: false, curveSegments: 4 }));
    // map the card's texture across its face rather than in world units
    g.computeBoundingBox();
    const bb = g.boundingBox, uv = g.attributes.uv, pos = g.attributes.position;
    for (let k = 0; k < uv.count; k++) uv.setXY(k, (pos.getX(k) - bb.min.x) / (bb.max.x - bb.min.x), (pos.getY(k) - bb.min.y) / (bb.max.y - bb.min.y));
    const m = new THREE.Mesh(g, dividerMats[i]);
    m.castShadow = m.receiveShadow = true;
    dossier.add(m);
    return m;
  });

  // sheets: printed face on +z, plain paper on edges and back
  const edgeMat = mat({ color: C.paper, roughness: 0.92 });
  const sheetGeo = geo(new THREE.BoxGeometry(SW, SH, ST));
  const markerMat = own(new THREE.MeshBasicMaterial({ color: C.amber, transparent: true, opacity: 0, depthWrite: false, toneMapped: false }), materials);
  const texW = narrow ? 640 : 896;
  const sheets = [];
  for (let i = 0; i < SHEET_COUNT; i++) {
    const { canvas, fields } = drawSheet(i, texW);
    const face = mat({ color: 0xffffff, map: tex(canvas), roughness: 0.74 });
    const mesh = new THREE.Mesh(sheetGeo, [edgeMat, edgeMat, edgeMat, edgeMat, face, edgeMat]);
    mesh.castShadow = mesh.receiveShadow = true;
    const group = new THREE.Group();
    group.add(mesh);
    const markers = fields.map((f) => {
      const w = f.w * SW, h = f.h * SH;
      const marker = new THREE.Mesh(geo(frameGeometry(w, h, 0.012)), markerMat);
      marker.position.set((f.u + f.w / 2 - 0.5) * SW, (0.5 - (f.v + f.h / 2)) * SH, ST / 2 + 0.002);
      group.add(marker);
      return marker;
    });
    scene.add(group);
    sheets.push({ group, markers, seed: i });
  }

  // front cover on a hinge along the left edge
  const coverPivot = new THREE.Group();
  coverPivot.position.set(-BW / 2, 0, COVER_Z);
  dossier.add(coverPivot);
  const cover = new THREE.Mesh(geo(new THREE.ExtrudeGeometry(roundedRect(BW, BD, 0.05), extrude)), board);
  cover.position.x = BW / 2;
  cover.castShadow = cover.receiveShadow = true;
  coverPivot.add(cover);
  const coverFace = new THREE.Mesh(geo(new THREE.PlaneGeometry(BW - 0.02, BD - 0.02)), mat({ color: 0xffffff, map: tex(drawCover(narrow ? 640 : 896)), roughness: 0.62 }));
  coverFace.position.set(BW / 2, 0, BT + 0.0075);
  coverFace.receiveShadow = true;
  coverPivot.add(coverFace);
  const brass = mat({ color: C.brass, metalness: 1, roughness: 0.3 });
  const eyeletGeo = geo(new THREE.TorusGeometry(0.045, 0.014, 12, 28));
  [0.7, 1.05].forEach((y) => {
    const e = new THREE.Mesh(eyeletGeo, brass);
    e.position.set(0.2, y - BD / 2 + 0.25, BT + 0.012);
    coverPivot.add(e);
  });
  // spine: the folded board that joins back and cover
  const spine = new THREE.Mesh(geo(new THREE.BoxGeometry(0.03, BD - 0.02, COVER_Z + BT)), board);
  spine.position.set(-BW / 2 - 0.006, 0, (COVER_Z + BT) / 2);
  spine.castShadow = true;
  dossier.add(spine);

  // ── route: brass rail, plinths, labels, ticks, role plates, deadline flag, threads ──
  // Wide screens run the route across the desk to the right of the file; portrait screens run it toward the
  // viewer, below the file, so the whole route fits a 390px column.
  const gap = narrow ? 0.92 : 1.12;
  const railLen = gap * (MILESTONES.length - 1) + 0.5;
  const origin = narrow ? new THREE.Vector3(-0.35, 0, 1.95) : new THREE.Vector3(1.55, 0, 0.95);
  const dir = narrow ? new THREE.Vector3(0, 0, 1) : new THREE.Vector3(1, 0, 0);
  const along = (d, x = 0, y = 0, z = 0) => origin.clone().addScaledVector(dir, d).add(new THREE.Vector3(x, y, z));
  const nodeAt = (i) => along(0.25 + i * gap);
  const railGeo = geo(new THREE.BoxGeometry(1, 0.018, 0.035));
  railGeo.translate(0.5, 0, 0);
  const rail = new THREE.Mesh(railGeo, brass);
  rail.position.copy(along(0, 0, 0.01));
  if (narrow) rail.rotation.y = -Math.PI / 2;
  rail.castShadow = true;
  scene.add(rail);

  const stone = mat({ color: C.stone, roughness: 0.55, metalness: 0.05 });
  const plinthGeo = geo(new THREE.CylinderGeometry(0.17, 0.19, 0.09, 48));
  const capGeo = geo(new THREE.CylinderGeometry(0.135, 0.135, 0.014, 48));
  const ringGeo = geo(new THREE.TorusGeometry(0.16, 0.012, 10, 48));
  const labelPlane = (canvas, w) => {
    const m = own(new THREE.MeshBasicMaterial({ map: tex(canvas), transparent: true, opacity: 0, depthWrite: false, toneMapped: false }), materials);
    return new THREE.Mesh(geo(new THREE.PlaneGeometry(w, w / 4)), m);
  };
  const nodes = MILESTONES.map((ms, i) => {
    const g = new THREE.Group();
    g.position.copy(nodeAt(i));
    if (ms.conditional) {
      const ring = new THREE.Mesh(ringGeo, brass);
      ring.rotation.x = Math.PI / 2; ring.position.y = 0.03;
      g.add(ring);
    } else {
      const plinth = new THREE.Mesh(plinthGeo, stone);
      plinth.position.y = 0.045; plinth.castShadow = plinth.receiveShadow = true;
      const cap = new THREE.Mesh(capGeo, brass);
      cap.position.y = 0.097;
      g.add(plinth, cap);
    }
    const label = labelPlane(drawLabel(ms.title, ms.caption), narrow ? 1.3 : 1.25);
    const role = labelPlane(drawLabel(ms.role, "responsible", { color: "#8fd0c8", sub: "#9fb8b4" }), narrow ? 1.1 : 0.9);
    role.rotation.x = -Math.PI / 2;
    if (narrow) {
      label.position.set(0.95, 0.06, -0.06); label.rotation.x = -Math.PI / 2;
      role.position.set(0.86, 0.01, 0.22);
    } else {
      label.position.set(0.36, 0.42, 0.02); label.rotation.x = -0.35;
      role.position.set(0.33, 0.02, 0.42);
    }
    g.add(label, role);
    scene.add(g);
    return { g, label, role };
  });

  const tickGeo = geo(new THREE.BoxGeometry(0.008, 0.006, 0.09));
  const ticks = [];
  for (let k = 0; k <= 24; k++) {
    const t = new THREE.Mesh(tickGeo, brass);
    t.position.copy(narrow ? along((k / 24) * railLen, -0.16, 0.004) : along((k / 24) * railLen, 0, 0.004, -0.16));
    if (narrow) t.rotation.y = Math.PI / 2;
    t.scale.z = k % 6 === 0 ? 1.8 : 1;
    scene.add(t);
    ticks.push(t);
  }
  const timeLabel = labelPlane(drawLabel(narrow ? "Time ↓" : "Time →", "internal clock · 30 days · demo assumption", { color: "#e9dfca" }), 1.5);
  timeLabel.rotation.x = -Math.PI / 2;
  timeLabel.position.copy(narrow ? along(railLen + 0.3, 0.55, 0.004) : along(0.75, 0, 0.004, 0.95));
  scene.add(timeLabel);

  // deadline flag at scrutiny: the 30-day internal processing clock (a demo assumption, not an AICTE date)
  const flag = new THREE.Group();
  const pole = new THREE.Mesh(geo(new THREE.CylinderGeometry(0.008, 0.008, 0.9, 8)), brass);
  pole.position.y = 0.45;
  const pennant = new THREE.Mesh(geo(new THREE.PlaneGeometry(0.22, 0.13)), own(new THREE.MeshStandardMaterial({ color: C.amber, side: THREE.DoubleSide, roughness: 0.6 }), materials));
  pennant.position.set(0.11, 0.82, 0);
  flag.add(pole, pennant);
  flag.position.copy(nodeAt(1).add(narrow ? new THREE.Vector3(-0.3, 0, -0.2) : new THREE.Vector3(-0.25, 0, -0.05)));
  scene.add(flag);

  // sheet poses: stacked in the folder, and lifted apart into a stepped stack of reviewable layers
  const stackY = (i) => BT + 0.012 + (SHEET_COUNT - 1 - i) * 0.011 + (i >= 4 ? 0 : 0.008) + (i >= 2 ? 0 : 0.008);
  const lifted = (i) => {
    const j = SHEET_COUNT - 1 - i; // bottom sheet rises least
    // higher sheets come forward, so every sheet's printed header stays visible behind the one above it
    return narrow
      ? { x: 0.55 - j * 0.2, y: 0.3 + j * 0.17, z: -0.6 + j * 0.15, tilt: 0.55, yaw: -0.16 + j * 0.03 }
      : { x: 1.05 - j * 0.34, y: 0.3 + j * 0.2, z: -0.7 + j * 0.2, tilt: 0.55, yaw: -0.2 + j * 0.035 };
  };
  dividers.forEach((d, i) => { d.position.z = BT + 0.008 + (i === 0 ? 4 : 2) * 0.011 + 0.002; });

  // teal threads: document → milestone it supports (checklist → submitted, land and building → scrutiny)
  const threadMat = own(new THREE.MeshStandardMaterial({ color: C.teal, emissive: C.teal, emissiveIntensity: 0.35, roughness: 0.5 }), materials);
  const threads = [[4, 0], [1, 1], [0, 1]].map(([s, n]) => {
    const L = lifted(s);
    const a = new THREE.Vector3(L.x + SW * 0.42, L.y - 0.1, L.z + 0.2);
    const b = nodeAt(n).setY(0.12);
    const mid = a.clone().lerp(b, 0.5); mid.y += 0.55;
    const g = geo(new THREE.TubeGeometry(new THREE.QuadraticBezierCurve3(a, mid, b), 48, 0.009, 6, false));
    const m = new THREE.Mesh(g, threadMat);
    m.geometry.setDrawRange(0, 0);
    scene.add(m);
    return m;
  });

  const tmpPos = new THREE.Vector3(), tmpTarget = new THREE.Vector3();
  const keys = narrow ? SHOTS.narrow : SHOTS.wide;

  function update(p) {
    const open = span(p, 0.08, 0.34);       // cover swings open
    const lift = span(p, 0.3, 0.56);        // sheets separate into layers
    const review = span(p, 0.44, 0.6);      // review frames on fields
    const route = span(p, 0.56, 0.8);       // rail extends, milestones rise
    const reveal = span(p, 0.78, 0.97);     // time, responsibility, relations

    coverPivot.rotation.y = -open * Math.PI * 0.955;
    coverPivot.position.z = COVER_Z + open * 0.02;

    sheets.forEach(({ group, markers }, i) => {
      const L = lifted(i);
      const delay = smooth((lift * 1.5) - i * 0.09); // the top sheet lifts first
      const t = Math.min(1, delay);
      group.position.set(mix(0.02, L.x, t), mix(stackY(i), L.y, t), mix(0.05, L.z, t));
      group.rotation.set(-Math.PI / 2 + L.tilt * t, L.yaw * t, mix(0.008 * (i - 2), 0, t));
      markers.forEach((m) => { m.visible = review > 0; });
    });
    markerMat.opacity = review * 0.95;

    rail.scale.x = Math.max(0.0001, route * railLen);
    rail.visible = route > 0;
    nodes.forEach(({ g, label, role }, i) => {
      const at = smooth((route * (MILESTONES.length + 0.6) - i) / 1.2);
      g.visible = at > 0;
      g.scale.setScalar(Math.max(0.0001, at));
      label.material.opacity = at;
      role.material.opacity = reveal;
      role.visible = reveal > 0;
    });
    ticks.forEach((t, k) => { t.visible = reveal * 26 > k; });
    timeLabel.material.opacity = reveal;
    timeLabel.visible = reveal > 0;
    flag.visible = reveal > 0.05;
    flag.scale.set(1, Math.max(0.0001, reveal), 1);
    threads.forEach((th, i) => {
      const r = smooth(reveal * 1.4 - i * 0.15);
      th.visible = r > 0;
      th.geometry.setDrawRange(0, Math.floor(th.geometry.index.count * r / 3) * 3);
    });
    contact.material.opacity = 0.85 - lift * 0.25;
    // the light pool follows the story: from the file to the route
    const follow = smooth(route * 0.7 + reveal * 0.3);
    pool.target.position.set(mix(0.2, narrow ? -0.1 : 3.0, follow), 0, mix(0.1, narrow ? 3.4 : 0.7, follow));
    pool.position.set(mix(-2.4, narrow ? -1.2 : 0.6, follow), 9.5, mix(4.2, 5.4, follow));
    pool.angle = mix(0.42, 0.62, follow);

    shot(keys, p, tmpPos, tmpTarget);
    camera.position.copy(tmpPos);
    camera.lookAt(tmpTarget);
  }

  function resize(w, h) {
    camera.aspect = w / Math.max(1, h);
    camera.updateProjectionMatrix();
  }

  function dispose() {
    textures.forEach((t) => t.dispose());
    geometries.forEach((g) => g.dispose());
    materials.forEach((m) => m.dispose());
    envRT.dispose();
    scene.clear();
  }

  return { scene, camera, update, resize, dispose };
}
