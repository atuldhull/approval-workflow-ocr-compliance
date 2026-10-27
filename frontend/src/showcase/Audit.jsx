import { useEffect, useRef, useState } from "react";
import { ChapterHead } from "./parts.jsx";
import { useSectionProgress } from "./scroll.js";

// Five illustrative events. Their hashes are real SHA-256 digests of the canonical text shown, computed in the
// browser, so the links can be checked by hand. They are not records from any running system.
const EVENTS = [
  { seq: 41, type: "application.submitted", by: "Institution" },
  { seq: 42, type: "document.scanned_clean", by: "Scanner service" },
  { seq: 43, type: "deficiency.recorded", by: "Scrutiny committee" },
  { seq: 44, type: "compliance.submitted", by: "Institution" },
  { seq: 45, type: "deadline.alert_raised", by: "Timer worker" },
];
const GENESIS = "0".repeat(64);

async function sha256(text) {
  const bytes = new TextEncoder().encode(text);
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function useChain() {
  const [chain, setChain] = useState(() => EVENTS.map((e) => ({ ...e, prev: null, hash: null })));
  useEffect(() => {
    if (!globalThis.crypto?.subtle || typeof TextEncoder === "undefined") return undefined;
    let live = true;
    (async () => {
      let prev = GENESIS.slice(0, 16) + "…";
      let prevFull = "(earlier entries)";
      const out = [];
      for (const e of EVENTS) {
        const canonical = JSON.stringify({ seq: e.seq, type: e.type, prev: prevFull });
        const hash = await sha256(canonical);
        out.push({ ...e, prev, prevFull, canonical, hash });
        prev = hash; prevFull = hash;
      }
      if (live) setChain(out);
    })().catch(() => {});
    return () => { live = false; };
  }, []);
  return chain;
}

const short = (h) => (h ? `${h.slice(0, 8)}…${h.slice(-4)}` : "computing…");

const STEPS = [
  ["One event", "An action is written as an event: what happened, in which order, by which role."],
  ["A chain of events", "Each new event is appended after the last. Nothing is updated in place."],
  ["Hash links", "Each event carries the hash of the one before it. Edit, remove or reorder any earlier event and every later link stops matching."],
  ["Checkpoint evidence", "Periodically the head of the chain is signed and a copy is handed to a witness outside the database."],
  ["Replay consistency", "The screens' read models are rebuilt from the events and compared with what is stored."],
  ["The whole structure", "Three checks that answer three different questions. None of them substitutes for another."],
];

export default function Audit({ reduced }) {
  const section = useRef(null);
  const scrolled = useSectionProgress(section, { steps: STEPS.length, enabled: !reduced });
  const step = reduced ? STEPS.length - 1 : scrolled;
  const chain = useChain();
  const show = (k) => step >= k;

  return (
    <section ref={section} id="audit" className={`sc-chapter sc-audit${reduced ? " is-static" : ""}`} aria-labelledby="audit-title" data-step={step}>
      <div className="sc-sticky">
        <div className="sc-audit-grid">
          <div className="sc-audit-copy">
            <ChapterHead n="05" id="audit-title" title="Trust Through Audit">
              Every action lands on an append-only record that can be checked three ways.
            </ChapterHead>
            <ol className="sc-audit-steps">
              {STEPS.map(([t, d], k) => (
                <li key={t} className={k === step ? "is-current" : k < step ? "is-done" : ""} aria-current={k === step ? "step" : undefined}>
                  <strong>{t}</strong><span>{d}</span>
                </li>
              ))}
            </ol>
          </div>

          <div className={`sc-audit-stage${step === STEPS.length - 1 ? " is-whole" : ""}`}>
            <div className="sc-layer sc-layer-chain" data-layer="continuity">
              <p className="sc-layer-name"><span>Layer 1</span> Event continuity · hash chain</p>
              <ol className="sc-chain" aria-label="Illustrative event chain">
                {chain.map((e, i) => (
                  <li key={e.seq} className={`sc-event${show(i === 0 ? 0 : 1) ? " is-in" : ""}${i === 4 && show(3) ? " is-after" : ""}`}>
                    <span className="sc-event-seq">#{e.seq}</span>
                    <strong>{e.type.split(".").map((part, k) => <span key={part}>{k ? <>.<wbr /></> : null}{part}</span>)}</strong>
                    <span className="sc-event-by">{e.by}</span>
                    <span className={`sc-event-hash${show(2) ? " is-in" : ""}`}>
                      <span>prev {i === 0 ? "…" : short(e.prev)}</span>
                      <span>hash {short(e.hash)}</span>
                    </span>
                    {i > 0 && <i className={`sc-link${show(2) ? " is-in" : ""}`} aria-hidden="true" />}
                  </li>
                ))}
              </ol>
            </div>

            <div className={`sc-layer sc-layer-checkpoint${show(3) ? " is-in" : ""}`} data-layer="checkpoint">
              <p className="sc-layer-name"><span>Layer 2</span> Checkpoint evidence · signed head + witness</p>
              <div className="sc-checkpoint-row">
                <div className="sc-checkpoint">
                  <strong>Signed checkpoint</strong>
                  <span>head #44 · {short(chain[3]?.hash)} · Ed25519</span>
                  <span>covers #41–#44</span>
                </div>
                <div className="sc-witness">
                  <strong>Witness copy</strong>
                  <span>Local file witness · <em>demo only</em></span>
                  <span>Same machine. Not an authority.</span>
                </div>
                <div className="sc-after">
                  <strong>#45 after the checkpoint</strong>
                  <span>Relies on the chain alone until the next checkpoint.</span>
                </div>
              </div>
            </div>

            <div className={`sc-layer sc-layer-replay${show(4) ? " is-in" : ""}`} data-layer="replay">
              <p className="sc-layer-name"><span>Layer 3</span> Replay consistency · rebuilt vs recorded</p>
              <table className="sc-replay">
                <caption className="sc-visually-hidden">Illustrative replay comparison</caption>
                <thead><tr><th scope="col">Read model</th><th scope="col">Recorded</th><th scope="col">Rebuilt from events</th><th scope="col">Result</th></tr></thead>
                <tbody>
                  <tr><th scope="row">Case stage</th><td>Re-scrutiny</td><td>Re-scrutiny</td><td>match</td></tr>
                  <tr><th scope="row">Open deficiencies</th><td>0</td><td>0</td><td>match</td></tr>
                  <tr><th scope="row">Alerts raised</th><td>1</td><td>1</td><td>match</td></tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
        <div className={`sc-audit-truth${show(5) ? " is-in" : ""}`}>
          <p><strong>What a chain shows:</strong> records were not altered after they were recorded. Not that they were true when recorded.</p>
          <p><strong>What a checkpoint adds:</strong> a rebuilt or cut-off chain is detected, up to the checkpoint. The demo witness is a file on the same machine, not an authority.</p>
          <p><strong>What replay adds:</strong> the screens agree with the events. It cannot see anything the events do not describe.</p>
          <p className="sc-provenance">Illustrative events. Hashes are SHA-256 of the canonical text, computed in your browser. A checkpoint is integrity evidence for this system, not a legal or digital signature on any approval.</p>
        </div>
      </div>
    </section>
  );
}
