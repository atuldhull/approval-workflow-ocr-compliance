import { useId, useState } from "react";
import { CLOCKS, LADDER, ROUTES, SOURCE_LABEL } from "./data.js";
import { ChapterHead, Tag, useInView } from "./parts.jsx";

const routeShapes = () => {
  const shapes = new Map();
  ROUTES.forEach((r) => { const k = r.stages.join(" → "); shapes.set(k, (shapes.get(k) || 0) + 1); });
  return shapes.size;
};

export function Challenge({ reduced }) {
  const [ref, seen] = useInView(reduced);
  const stats = [
    [String(ROUTES.length), "application categories in the rule set, each with its own route"],
    [String(routeShapes()), "distinct route shapes, from self-disclosure alone to a five-stage new-institution route"],
    ["3", "kinds of clock: handbook deadlines, internal processing clocks, and demo assumptions"],
    ["6", "roles in this prototype, from the institution and scrutiny committee to the bureau head and the auditor"],
  ];
  return (
    <section id="challenge" className="sc-chapter sc-challenge" aria-labelledby="challenge-title">
      <div ref={ref} className={`sc-wrap sc-reveal${seen ? " is-in" : ""}`}>
        <ChapterHead n="01" id="challenge-title" title="The Challenge">
          Approval work is not hard because of paperwork. It is hard because many people, rules and clocks have to agree
          about one file, and later, someone has to be able to show that they did.
        </ChapterHead>
        <dl className="sc-stats">
          {stats.map(([v, d]) => <div key={d}><dt>{v}</dt><dd>{d}</dd></div>)}
        </dl>
        <ul className="sc-questions">
          <li><span>Where is this application,</span> and which stage comes next for its category?</li>
          <li><span>What does this document actually say,</span> and who confirmed it?</li>
          <li><span>Whose move is it,</span> and when is it due, by which rule?</li>
          <li><span>Can we show</span> that the record has not been changed since?</li>
        </ul>
        <p className="sc-provenance">Counts are taken from rule set aph-2024-27 r1 and this prototype's role list.</p>
      </div>
    </section>
  );
}

// Commit before reveal, in miniature. Everything happens in this component's state: nothing is sent anywhere.
export function Evidence({ reduced }) {
  const [ref, seen] = useInView(reduced);
  const inputId = useId();
  const [reading, setReading] = useState("");
  const [committed, setCommitted] = useState(null);
  const [confirmed, setConfirmed] = useState(false);
  const MACHINE = "4,320";
  const SOURCE = "4,820";
  const norm = (s) => s.replace(/[^\d]/g, "");
  const agrees = committed !== null && norm(committed) === norm(MACHINE);
  const reset = () => { setReading(""); setCommitted(null); setConfirmed(false); };

  return (
    <section id="evidence" className="sc-chapter sc-evidence" aria-labelledby="evidence-title">
      <div ref={ref} className={`sc-wrap sc-reveal${seen ? " is-in" : ""}`}>
        <ChapterHead n="03" id="evidence-title" title="Documents into Evidence">
          A scanned page is not yet a fact. A person reads it first; only then is the machine's proposal shown; a second
          officer confirms. Try it with the sample field below.
        </ChapterHead>
        <ol className="sc-evidence-row">
          <li className="sc-ev sc-ev-source">
            <p className="sc-ev-n">1 · Original document</p>
            <div className="sc-paper" aria-label="Sample page excerpt">
              <span className="sc-paper-label">FORM B · Land and building · illustrative</span>
              <span className="sc-paper-field">Total built-up area (sq m)</span>
              <span className="sc-paper-value">{SOURCE}</span>
            </div>
            <p className="sc-ev-note">Scanned clean before anyone may use it. Every version stays on record.</p>
          </li>
          <li className="sc-ev sc-ev-human">
            <p className="sc-ev-n">2 · Your reading, typed first</p>
            {committed === null ? (
              <form onSubmit={(e) => { e.preventDefault(); if (reading.trim()) setCommitted(reading.trim()); }}>
                <label htmlFor={inputId}>Total built-up area (sq m)</label>
                <input id={inputId} inputMode="numeric" autoComplete="off" value={reading} onChange={(e) => setReading(e.target.value)} placeholder="Read it from the page" />
                <button type="submit" className="sc-button small primary" disabled={!reading.trim()}>Commit my reading</button>
              </form>
            ) : (
              <p className="sc-ev-value">{committed} <Tag kind="ok">committed</Tag></p>
            )}
            <p className="sc-ev-note">In the workspace the server records this before it answers with anything.</p>
          </li>
          <li className={`sc-ev sc-ev-machine${committed !== null ? " is-open" : ""}`} aria-live="polite">
            <p className="sc-ev-n">3 · Machine-proposed reading</p>
            {committed === null ? (
              <p className="sc-ev-sealed">Sealed until you commit your reading.</p>
            ) : (
              <>
                <p className="sc-ev-value">{MACHINE} <Tag kind="warn">proposal</Tag></p>
                <p className="sc-ev-note">{agrees ? "Your reading matches the proposal." : "Your reading differs from the proposal. Neither wins automatically: the page decides."} A proposal is never a decision.</p>
              </>
            )}
          </li>
          <li className={`sc-ev sc-ev-fact${confirmed ? " is-open" : ""}`}>
            <p className="sc-ev-n">4 · Confirmed fact</p>
            {confirmed ? (
              <p className="sc-ev-value">{SOURCE} <Tag kind="ok">confirmed by a second officer</Tag></p>
            ) : (
              <>
                <p className="sc-ev-sealed">Needs a second officer. The person who read it cannot confirm their own entry.</p>
                <button type="button" className="sc-button small" disabled={committed === null} onClick={() => setConfirmed(true)}>Show a second officer's confirmation</button>
              </>
            )}
          </li>
        </ol>
        <div className="sc-evidence-foot">
          <p className="sc-provenance">Sample values. Nothing here is sent anywhere; the workspace's fact review runs this on the real API.</p>
          {committed !== null && <button type="button" className="sc-text-button" onClick={reset}>Start again</button>}
        </div>
      </div>
    </section>
  );
}

// Time axis: 0–45 days, one illustrative case. The pause/resume behaviour follows deadlines.yaml and the deadline
// service (an internal clock's due date moves by the time it was held; legal clocks are never paused).
const X = (d) => 40 + d * 18;
export function Deadlines({ reduced }) {
  const [ref, seen] = useInView(reduced);
  const [aicte, inst] = CLOCKS;
  return (
    <section id="deadlines" className="sc-chapter sc-deadlines" aria-labelledby="deadlines-title">
      <div ref={ref} className={`sc-wrap sc-reveal${seen ? " is-in" : ""}`}>
        <ChapterHead n="04" id="deadlines-title" title="Deadlines and Responsibility">
          Every clock answers three questions: what started it, who owns it, and where its length comes from.
        </ChapterHead>
        <ul className="sc-legend" aria-label="Kinds of time limit">
          <li><Tag kind="ok">Handbook clause</Tag> a figure from the Approval Process Handbook, with its clause</li>
          <li><Tag kind="neutral">Internal clock</Tag> this system's processing timer; it can pause</li>
          <li><Tag kind="warn">Demo assumption</Tag> no handbook figure exists; configurable, not an AICTE date</li>
        </ul>
        <figure className="sc-timeline">
          <svg viewBox="0 0 900 300" role="img" aria-labelledby="sc-timeline-title">
            <title id="sc-timeline-title">
              Illustrative case. Day 0 the application is submitted and the 30-day internal processing clock starts. Day 12 a
              deficiency is recorded: the processing clock pauses and the institution's 15-day response clock starts. Day 20
              the institution responds: its clock stops and processing resumes, its due date moved by the 8 days it was held.
            </title>
            {Array.from({ length: 46 }, (_, d) => (
              <path key={d} d={`M${X(d)} 250 V ${d % 5 ? 256 : 262}`} className="sc-tick" />
            ))}
            {[0, 10, 20, 30, 40].map((d) => <text key={d} x={X(d)} y="280" className="sc-svg-caption" textAnchor="middle">day {d}</text>)}
            <path d={`M${X(0)} 250 H ${X(45)}`} className="sc-axis" />

            <text x={X(0)} y="34" className="sc-svg-label">Processing · {aicte.days} days · owner: AICTE side, alerts to regional officer</text>
            <rect x={X(0)} y="46" width={X(12) - X(0)} height="18" className="sc-bar-internal" />
            <rect x={X(12)} y="46" width={X(20) - X(12)} height="18" className="sc-bar-paused" />
            <rect x={X(20)} y="46" width={X(38) - X(20)} height="18" className="sc-bar-internal" />
            <text x={X(16)} y="80" className="sc-svg-caption" textAnchor="middle">paused</text>
            <path d={`M${X(30)} 40 V 70`} className="sc-due-old" /><text x={X(30)} y="90" className="sc-svg-caption" textAnchor="middle">was due</text>
            <path d={`M${X(38)} 40 V 70`} className="sc-due" /><text x={X(38)} y="90" className="sc-svg-caption" textAnchor="middle">due · day 38</text>

            <text x={X(12)} y="126" className="sc-svg-label">Response · {inst.days} days · owner: institution</text>
            <rect x={X(12)} y="138" width={X(20) - X(12)} height="18" className="sc-bar-institution" />
            <rect x={X(20)} y="138" width={X(27) - X(20)} height="18" className="sc-bar-unused" />
            <text x={X(23.5)} y="172" className="sc-svg-caption" textAnchor="middle">stopped · responded day 20</text>

            {[[0, "Submitted", 232], [12, "Deficiency recorded", 212], [20, "Compliance submitted", 240]].map(([d, t, ty]) => (
              <g key={t}><circle cx={X(d)} cy="228" r="6" className="sc-event-dot" /><text x={X(d) + 10} y={ty} className="sc-svg-caption">{t}</text></g>
            ))}
          </svg>
        </figure>
        <div className="sc-clock-cards">
          {CLOCKS.map((c) => (
            <article key={c.id} className="sc-clock">
              <p className="sc-mono">{c.id}</p>
              <h3>{c.days} days after “{c.anchor.toLowerCase()}”</h3>
              <p><Tag kind={c.kind === "Legal deadline" ? "ok" : "neutral"}>{c.kind}</Tag> <Tag kind={c.source === "verified" ? "ok" : "warn"}>{SOURCE_LABEL[c.source]}{c.clause ? ` ${c.clause}` : ""}</Tag></p>
              <p>Owner: {c.owner}. {c.note}</p>
            </article>
          ))}
        </div>
        <Notifications />
      </div>
    </section>
  );
}

function Notifications() {
  return (
    <section className="sc-notify" aria-labelledby="notify-title">
      <h3 id="notify-title">From obligation to alert to delivery</h3>
      <ol className="sc-notify-flow">
        <li><strong>Obligation</strong><span>A deadline with an owner exists on the record.</span></li>
        <li><strong>Alert</strong><span>As the due instant nears or passes, a level of the ladder is raised.</span></li>
        <li><strong>Delivery</strong><span>Each message is sent in-app and by email; every attempt is recorded, retried after 15 minutes.</span></li>
        <li><strong>Acknowledgement</strong><span>Stops the ladder for that due date. Silence moves it up.</span></li>
      </ol>
      <ol className="sc-ladder" aria-label="Standard alert ladder">
        {LADDER.map((l) => (
          <li key={l.level} style={{ "--level": l.level }}>
            <span className="sc-mono">L{l.level}</span><strong>{l.to}</strong><span>{l.at} · {l.template}</span>
          </li>
        ))}
      </ol>
      <p className="sc-provenance">Illustrative. The handbook sets no reminder or escalation schedule: every offset, role and channel in this ladder is a configurable demo assumption from deadlines.yaml. The appeal window is reminder-only and never escalates.</p>
    </section>
  );
}

export function WorkspaceReveal({ reduced, onEnter, onInspect }) {
  const [ref, seen] = useInView(reduced);
  const screens = [
    ["Overview & cases", "Each application on its prescribed route: checklist, guarded actions, committees, deficiencies.", "Built"],
    ["Documents", "Checklist uploads, versions and their malware-scan result.", "Built"],
    ["Fact review", "Type first, then see the machine reading; a second officer confirms.", "Built"],
    ["Alerts & delivery", "Who was told, by which ladder level, and what happened to each message.", "Built"],
    ["Compliance", "Approval letters, the obligations they create, and the evidence that meets them.", "Built"],
    ["Audit", "Chain, checkpoint and replay results, each shown separately.", "Built"],
    ["EVC scheduling", "Visit queue, expert pool, EDF or CP-SAT proposals and publication; panels from a simulated selector stand-in.", "Built"],
  ];
  return (
    <section id="workspace" className="sc-chapter sc-workspace" aria-labelledby="workspace-title">
      <div ref={ref} className={`sc-wrap sc-reveal${seen ? " is-in" : ""}`}>
        <ChapterHead n="06" id="workspace-title" title="Enter the Workspace">
          Everything above is a walk-through. The workspace is the working system: it runs on the API with synthetic data,
          and each role sees only its own screens.
        </ChapterHead>
        <ul className="sc-screens">
          {screens.map(([t, d, s]) => <li key={t}><strong>{t}</strong><span>{d}</span><Tag kind={s === "Built" ? "ok" : "warn"}>{s}</Tag></li>)}
        </ul>
        <div className="sc-actions">
          <button type="button" className="sc-button primary" onClick={onEnter}>Open workspace</button>
          <button type="button" className="sc-button" onClick={onInspect}>Inspect a case</button>
        </div>
        <p className="sc-provenance">If the API is not running, the workspace says so instead of showing sample results.</p>
      </div>
    </section>
  );
}
