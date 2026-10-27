// Canvas-drawn textures for the hero dossier. Everything is procedural: no images are downloaded, and every
// identifier printed here is visibly a sample. Field rectangles are returned in UV space so the scene can place
// review markers exactly over the printed fields.

const SERIF = 'Georgia, "Times New Roman", serif';
const SANS = '"Hanken Grotesk Variable", "Hanken Grotesk", system-ui, sans-serif';
const MONO = '"JetBrains Mono", ui-monospace, monospace';

// Small deterministic generator so every page view prints the same sheets.
function rng(seed) {
  let s = seed >>> 0;
  return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
}

function canvas(w, h) {
  const c = document.createElement("canvas");
  c.width = w; c.height = h;
  return [c, c.getContext("2d")];
}

// Paper tooth and board fibre: one small noise tile, written once through ImageData and repeated as a pattern.
// (Thousands of individual fillRect calls per sheet cost hundreds of milliseconds on load.)
const tiles = {};
function noiseTile(light) {
  const key = light ? "light" : "dark";
  if (tiles[key]) return tiles[key];
  const [c, ctx] = canvas(192, 192);
  const img = ctx.createImageData(192, 192);
  const rand = rng(light ? 11 : 23);
  const v = light ? 255 : 0;
  for (let i = 0; i < img.data.length; i += 4) {
    const r = rand();
    img.data[i] = img.data[i + 1] = img.data[i + 2] = v;
    img.data[i + 3] = r > 0.82 ? Math.floor((r - 0.82) * 1400) : 0; // sparse specks, varied strength
  }
  ctx.putImageData(img, 0, 0);
  tiles[key] = c;
  return c;
}
function grain(ctx, w, h, rand, alpha, count, light = false) {
  ctx.save();
  ctx.globalAlpha = Math.min(1, alpha * (count / 6000));
  ctx.fillStyle = ctx.createPattern(noiseTile(light), "repeat");
  ctx.fillRect(0, 0, w, h);
  ctx.restore();
}

// Grey "printed text" bars: reads as type at product-shot distance without inventing content.
function bars(ctx, x, y, w, rand, lines = 1, h = 7, gap = 14, tone = "rgba(40,34,26,0.55)") {
  ctx.fillStyle = tone;
  for (let i = 0; i < lines; i++) {
    const lw = i === lines - 1 && lines > 1 ? w * (0.35 + rand() * 0.4) : w * (0.82 + rand() * 0.18);
    let cx = x;
    while (cx < x + lw) {
      const word = 10 + rand() * 46;
      ctx.fillRect(cx, y + i * gap, Math.min(word, x + lw - cx), h);
      cx += word + 5 + rand() * 3;
    }
  }
}

const SHEETS = [
  { title: "Application particulars", form: "FORM A" },
  { title: "Land and building", form: "FORM B" },
  { title: "Faculty and staff", form: "FORM C" },
  { title: "Fee and finance", form: "FORM D" },
  { title: "Document checklist", form: "FORM E" },
  { title: "Affidavit", form: "FORM F" },
];
export const SHEET_COUNT = SHEETS.length;

// Returns { canvas, fields: [{u,v,w,h}] } with fields in 0..1 page space (origin top-left).
export function drawSheet(index, W = 896) {
  const H = Math.round(W * 1.414);
  const [c, ctx] = canvas(W, H);
  const rand = rng(91 + index * 7);
  const k = W / 896;
  const sheet = SHEETS[index % SHEETS.length];
  const fields = [];
  const mark = (x, y, w, h) => fields.push({ u: x / W, v: y / H, w: w / W, h: h / H });

  // paper: warm ivory, a faint tooth, slightly darker edges
  ctx.fillStyle = "#efe6d3"; ctx.fillRect(0, 0, W, H);
  const edge = ctx.createRadialGradient(W / 2, H / 2, W * 0.3, W / 2, H / 2, W * 0.95);
  edge.addColorStop(0, "rgba(0,0,0,0)"); edge.addColorStop(1, "rgba(92,70,40,0.10)");
  ctx.fillStyle = edge; ctx.fillRect(0, 0, W, H);
  grain(ctx, W, H, rand, 0.05, 9000);

  const m = 64 * k;
  // header
  ctx.fillStyle = "#2a231a";
  ctx.font = `600 ${15 * k}px ${MONO}`;
  ctx.fillText(`${sheet.form} · ILLUSTRATIVE SAMPLE`, m, m + 6 * k);
  ctx.textAlign = "right";
  ctx.fillText(`SHEET ${index + 1} / ${SHEETS.length}`, W - m, m + 6 * k);
  ctx.textAlign = "left";
  ctx.font = `${44 * k}px ${SERIF}`;
  ctx.fillText(sheet.title, m, m + 70 * k);
  ctx.fillStyle = "#5B4632"; ctx.fillRect(m, m + 96 * k, W - 2 * m, 3 * k);
  ctx.fillStyle = "rgba(42,35,26,0.35)"; ctx.fillRect(m, m + 104 * k, W - 2 * m, 1 * k);

  let y = m + 150 * k;
  const label = (t, x, yy) => { ctx.fillStyle = "#6b5a44"; ctx.font = `600 ${12 * k}px ${MONO}`; ctx.fillText(t.toUpperCase(), x, yy); };
  const field = (t, x, yy, w, value, review = false) => {
    label(t, x, yy);
    ctx.strokeStyle = "rgba(42,35,26,0.45)"; ctx.lineWidth = 1.2 * k;
    ctx.strokeRect(x, yy + 10 * k, w, 44 * k);
    if (value) { ctx.fillStyle = "#1f1a13"; ctx.font = `${22 * k}px ${SANS}`; ctx.fillText(value, x + 14 * k, yy + 41 * k); }
    else bars(ctx, x + 14 * k, yy + 28 * k, w * 0.6, rand);
    if (review) mark(x - 6 * k, yy - 18 * k, w + 12 * k, 78 * k);
  };

  if (index === 0) {
    field("Name of institution", m, y, W - 2 * m, "Sample Institute of Technology", true); y += 100 * k;
    field("Category", m, y, (W - 2 * m) * 0.62, "New programme"); field("Academic year", m + (W - 2 * m) * 0.66, y, (W - 2 * m) * 0.34, "2027–28"); y += 100 * k;
    field("Address", m, y, W - 2 * m); y += 100 * k;
    field("Region", m, y, (W - 2 * m) * 0.48, "Southern"); field("Reference", m + (W - 2 * m) * 0.52, y, (W - 2 * m) * 0.48, "SAMPLE-0000", true); y += 120 * k;
    label("Programmes applied for", m, y); y += 22 * k;
    for (let i = 0; i < 5; i++) { ctx.strokeStyle = "rgba(42,35,26,0.5)"; ctx.strokeRect(m, y + i * 40 * k, 20 * k, 20 * k); bars(ctx, m + 36 * k, y + 6 * k + i * 40 * k, W * 0.5, rand); }
    y += 230 * k;
  } else if (index === 1) {
    const cols = [0, 0.34, 0.62, 1];
    const tw = W - 2 * m;
    label("Land and built-up area", m, y); y += 20 * k;
    ctx.strokeStyle = "rgba(42,35,26,0.55)"; ctx.lineWidth = 1.2 * k;
    for (let r = 0; r <= 6; r++) { ctx.beginPath(); ctx.moveTo(m, y + r * 52 * k); ctx.lineTo(m + tw, y + r * 52 * k); ctx.stroke(); }
    cols.forEach((cx) => { ctx.beginPath(); ctx.moveTo(m + cx * tw, y); ctx.lineTo(m + cx * tw, y + 6 * 52 * k); ctx.stroke(); });
    ctx.fillStyle = "#2a231a"; ctx.font = `600 ${13 * k}px ${MONO}`;
    ["PARCEL", "AREA (SQ M)", "DOCUMENT"].forEach((t, i) => ctx.fillText(t, m + cols[i] * tw + 12 * k, y + 32 * k));
    for (let r = 1; r < 6; r++) {
      bars(ctx, m + 12 * k, y + r * 52 * k + 22 * k, tw * 0.22, rand);
      ctx.fillStyle = "#1f1a13"; ctx.font = `${20 * k}px ${SANS}`;
      ctx.fillText(r === 3 ? "4,820" : String(800 + Math.floor(rand() * 2400)), m + cols[1] * tw + 12 * k, y + r * 52 * k + 34 * k);
      bars(ctx, m + cols[2] * tw + 12 * k, y + r * 52 * k + 22 * k, tw * 0.25, rand);
    }
    mark(m + cols[1] * tw - 4 * k, y + 3 * 52 * k - 4 * k, (cols[2] - cols[1]) * tw + 8 * k, 60 * k);
    y += 6 * 52 * k + 60 * k;
    field("Total built-up area (sq m)", m, y, (W - 2 * m) * 0.5, "4,820", true); y += 110 * k;
  } else if (index === 4) {
    label("Documents enclosed", m, y); y += 26 * k;
    for (let i = 0; i < 9; i++) {
      ctx.strokeStyle = "rgba(42,35,26,0.55)"; ctx.lineWidth = 1.4 * k;
      ctx.strokeRect(m, y + i * 54 * k, 24 * k, 24 * k);
      if (i % 3 !== 2) { ctx.beginPath(); ctx.moveTo(m + 5 * k, y + i * 54 * k + 13 * k); ctx.lineTo(m + 11 * k, y + i * 54 * k + 19 * k); ctx.lineTo(m + 20 * k, y + i * 54 * k + 5 * k); ctx.stroke(); }
      bars(ctx, m + 44 * k, y + i * 54 * k + 8 * k, W * 0.55, rand);
    }
    mark(m - 8 * k, y + 2 * 54 * k - 10 * k, W * 0.66, 46 * k);
    y += 9 * 54 * k + 20 * k;
  } else {
    for (let p = 0; p < 4; p++) { bars(ctx, m, y, W - 2 * m, rand, 4 + (p % 2), 7 * k, 16 * k); y += (5 + (p % 2)) * 16 * k + 22 * k; }
    if (index === 3) { field("Annual fee (illustrative)", m, y, (W - 2 * m) * 0.5, "₹ —", true); y += 100 * k; }
  }

  // signature block and a generic, clearly-sample stamp ring
  const sy = H - m - 150 * k;
  ctx.strokeStyle = "rgba(42,35,26,0.55)"; ctx.lineWidth = 1.2 * k;
  ctx.beginPath(); ctx.moveTo(m, sy + 80 * k); ctx.lineTo(m + 300 * k, sy + 80 * k); ctx.stroke();
  label("Signature of authorised signatory", m, sy + 104 * k);
  if (index === 5 || index === 0) {
    ctx.save(); ctx.translate(W - m - 110 * k, sy + 40 * k); ctx.rotate(-0.18);
    ctx.strokeStyle = "rgba(91,70,50,0.55)"; ctx.lineWidth = 3 * k;
    ctx.beginPath(); ctx.arc(0, 0, 70 * k, 0, Math.PI * 2); ctx.stroke();
    ctx.beginPath(); ctx.arc(0, 0, 56 * k, 0, Math.PI * 2); ctx.stroke();
    ctx.fillStyle = "rgba(91,70,50,0.6)"; ctx.font = `700 ${18 * k}px ${MONO}`; ctx.textAlign = "center";
    ctx.fillText("SAMPLE", 0, 7 * k); ctx.restore(); ctx.textAlign = "left";
    if (index === 5) mark(W - m - 190 * k, sy - 40 * k, 160 * k, 160 * k);
  }
  ctx.fillStyle = "#6b5a44"; ctx.font = `${12 * k}px ${MONO}`;
  ctx.fillText("Illustrative sample · not an AICTE form · aph-2024-27 r1", m, H - m + 24 * k);
  return { canvas: c, fields };
}

// The cover: mocha board with a printed file label, in the manner of an institutional file cover.
export function drawCover(W = 896) {
  const H = Math.round(W * 1.37);
  const [c, ctx] = canvas(W, H);
  const rand = rng(7);
  const k = W / 896;
  const g = ctx.createLinearGradient(0, 0, W, H);
  g.addColorStop(0, "#6a523a"); g.addColorStop(1, "#4e3b29");
  ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
  // board weave
  ctx.globalAlpha = 0.06;
  for (let x = 0; x < W; x += 3) { ctx.fillStyle = x % 6 ? "#000" : "#fff"; ctx.fillRect(x, 0, 1, H); }
  for (let y = 0; y < H; y += 3) { ctx.fillStyle = y % 6 ? "#000" : "#fff"; ctx.fillRect(0, y, W, 1); }
  ctx.globalAlpha = 1;
  grain(ctx, W, H, rand, 0.08, 14000, true);
  grain(ctx, W, H, rand, 0.12, 9000);

  const m = 70 * k;
  // printed label panel
  ctx.fillStyle = "rgba(244,217,160,0.92)";
  ctx.fillRect(m, 170 * k, W - 2 * m, 520 * k);
  ctx.strokeStyle = "#3b2c1e"; ctx.lineWidth = 2 * k; ctx.strokeRect(m + 12 * k, 182 * k, W - 2 * m - 24 * k, 496 * k);
  ctx.fillStyle = "#2b2016"; ctx.font = `${50 * k}px ${SERIF}`;
  ctx.fillText("Application Dossier", m + 40 * k, 262 * k);
  ctx.font = `600 ${14 * k}px ${MONO}`; ctx.fillStyle = "#5B4632";
  ctx.fillText("ILLUSTRATIVE SAMPLE · INDEPENDENT PROTOTYPE", m + 40 * k, 298 * k);
  const rows = [["File no.", "SAMPLE-0000 · not an AICTE file number"], ["Subject", "New programme / level"], ["Institution", "Sample Institute of Technology"], ["Year", "2027–28"]];
  rows.forEach(([a, b], i) => {
    const yy = 370 * k + i * 76 * k;
    ctx.fillStyle = "#5B4632"; ctx.font = `600 ${13 * k}px ${MONO}`; ctx.fillText(a.toUpperCase(), m + 40 * k, yy);
    ctx.fillStyle = "#1f1710"; ctx.font = `${24 * k}px ${SANS}`; ctx.fillText(b, m + 200 * k, yy + 2 * k);
    ctx.fillStyle = "rgba(59,44,30,0.45)"; ctx.fillRect(m + 200 * k, yy + 16 * k, W - 2 * m - 250 * k, 1.5 * k);
  });
  // corner mark: concentric route arcs (the product's own mark, not a seal)
  ctx.save(); ctx.translate(W - m - 60 * k, H - m - 80 * k);
  ctx.strokeStyle = "rgba(244,217,160,0.55)"; ctx.lineWidth = 3 * k;
  for (let r = 18; r <= 54; r += 18) { ctx.beginPath(); ctx.arc(0, 0, r * k, Math.PI * 0.9, Math.PI * 2.1); ctx.stroke(); }
  ctx.restore();
  ctx.fillStyle = "rgba(244,217,160,0.7)"; ctx.font = `600 ${14 * k}px ${MONO}`;
  ctx.fillText("AICTE APPROVAL OPERATIONS · WORKFLOW · OCR · COMPLIANCE", m, H - m - 10 * k);
  return c;
}

export function drawBoard(W = 512) {
  const [c, ctx] = canvas(W, W);
  const rand = rng(3);
  ctx.fillStyle = "#57432f"; ctx.fillRect(0, 0, W, W);
  grain(ctx, W, W, rand, 0.08, 6000, true);
  grain(ctx, W, W, rand, 0.12, 6000);
  return c;
}

// Section divider card with a printed tab.
export function drawDivider(text, color, W = 512) {
  const H = Math.round(W * 1.414);
  const [c, ctx] = canvas(W, H);
  const rand = rng(text.length * 13);
  ctx.fillStyle = color; ctx.fillRect(0, 0, W, H);
  grain(ctx, W, H, rand, 0.07, 4000, true);
  grain(ctx, W, H, rand, 0.08, 4000);
  ctx.save(); ctx.translate(W - 26, H * 0.2); ctx.rotate(Math.PI / 2);
  ctx.fillStyle = "rgba(20,19,16,0.75)"; ctx.font = `700 22px ${MONO}`; ctx.fillText(text, 0, 0);
  ctx.restore();
  return c;
}

// A printed label for a milestone or a role marker.
export function drawLabel(title, caption = "", { W = 640, color = "#F4D9A0", sub = "#c5bba9" } = {}) {
  const H = Math.round(W / 4);
  const [c, ctx] = canvas(W, H);
  ctx.fillStyle = color; ctx.font = `${Math.round(H * 0.34)}px ${SERIF}`;
  ctx.fillText(title, 8, H * 0.46);
  if (caption) { ctx.fillStyle = sub; ctx.font = `600 ${Math.round(H * 0.17)}px ${MONO}`; ctx.fillText(caption.toUpperCase(), 10, H * 0.82); }
  return c;
}

export function drawContactShadow(W = 256) {
  const [c, ctx] = canvas(W, W);
  const g = ctx.createRadialGradient(W / 2, W / 2, 0, W / 2, W / 2, W / 2);
  g.addColorStop(0, "rgba(0,0,0,0.62)"); g.addColorStop(0.55, "rgba(0,0,0,0.28)"); g.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = g; ctx.fillRect(0, 0, W, W);
  return c;
}
