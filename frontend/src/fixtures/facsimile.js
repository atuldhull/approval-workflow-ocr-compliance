// SYNTHETIC FACSIMILE of a lease deed page, drawn as an image so the officer reads the "document" itself, not text
// produced by OCR. Everything here is invented for the demo.

const W = 640;
const H = 420;

const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
<rect width="100%" height="100%" fill="#fbf8ef"/>
<text x="20" y="28" font-family="monospace" font-size="12" fill="#b3261e">SYNTHETIC FACSIMILE - DEMO ONLY - NOT A REAL DOCUMENT</text>
<text x="320" y="70" text-anchor="middle" font-family="Georgia, serif" font-size="22" fill="#222">LEASE DEED</text>
<text x="40" y="120" font-family="Georgia, serif" font-size="15" fill="#333">Riverbend Institute of Management (DEMO), hereinafter the Lessee.</text>
<text x="40" y="160" font-family="Georgia, serif" font-size="15" fill="#333">This lease is granted for a term of thirty years</text>
<text x="40" y="190" font-family="Georgia, serif" font-size="15" fill="#333">commencing on 01-04-2001 and ending on 31-03-2031,</text>
<text x="40" y="220" font-family="Georgia, serif" font-size="15" fill="#333">in respect of the land described in Schedule A.</text>
<text x="40" y="330" font-family="Georgia, serif" font-size="13" fill="#555">Signed and sealed (specimen).</text>
<path d="M60 360 q20 -30 40 0 t40 0 t40 0" stroke="#345" fill="none" stroke-width="1.5"/>
</svg>`;

export const FACSIMILE = {
  documentId: "SAMPLE-LEASE-001",
  title: "Lease deed - Riverbend Institute of Management (DEMO)",
  page: { imageUrl: `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`, width: W, height: H },
  fields: [
    { key: "lease_start", label: "Lease start date", format: "YYYY-MM-DD", suggestion: "2001-04-01", confidence: 0.94,
      box: { page: 0, x: 148, y: 174, w: 92, h: 22 }, sourceText: "01-04-2001" },
    { key: "lease_end", label: "Lease end date", format: "YYYY-MM-DD", suggestion: "2031-03-31", confidence: 0.91,
      box: { page: 0, x: 318, y: 174, w: 92, h: 22 }, sourceText: "31-03-2031" },
  ],
};
