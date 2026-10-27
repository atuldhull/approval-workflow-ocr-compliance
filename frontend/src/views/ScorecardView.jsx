import { Badge, ErrorBox, Kpis, Loading, useApi, when } from "../components/ui.jsx";


// How each line was measured (the method badge, always neutral) is kept apart from what was found (the verdict
// badge and the card colour, from outcomeTone), so a check that ran and failed is never shown green.
const KIND = {
  VERIFIED_NOW: ["ok", "Checked now"],
  EVALUATED_ON_ANSWER_KEY: ["ok", "Evaluated on answer key"],
  MEASURED_ON_DEMO_TRAFFIC: ["warn", "Measured on synthetic demo traffic"],
  NOT_EVALUATED: ["neutral", "Not evaluated yet"],
};

const OUTCOME = { PASS: ["ok", "Pass"], ATTENTION: ["warn", "Needs attention"], FAIL: ["bad", "Fail"] };

// result keys shown with plain labels; a result with none of these is shown as raw figures
const LABELS = {
  entries_checked: "Entries checked", assurance: "Assurance", verdict: "Verdict", gaps: "Gaps",
  attempts: "Attempts", first_try_success_rate: "First-try success", delivered_after_retry: "Delivered after retry",
  dead_letters: "Dead letters", stalled_sending: "Stalled", levels_due: "Levels due", raised: "Raised",
  missed: "Missed", duplicates: "Duplicates", early: "Raised early", max_lag_hours: "Longest lag (hours)",
  versions: "Versions", clean: "Clean", infected: "Infected", scan_pending: "Waiting for scan",
  oldest_pending_minutes: "Oldest wait (minutes)", used_while_not_clean: "Used before a clean scan",
  confirmed_facts: "Confirmed facts", confirmed_by_own_reviewer: "Confirmed by own reviewer",
  confirmed_without_review: "Confirmed without review", evidence_decisions: "Evidence decisions",
  evidence_decided_by_system: "Decided by an automated actor", reviewed: "Reviewed", accepted: "Accepted",
  corrected: "Corrected", rejected: "Rejected", blind_entry_agreement: "Blind entry agrees with OCR",
};

export function figure(key, value) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number" && /rate|agreement/.test(key)) return `${Math.round(value * 100)}%`;
  if (typeof value === "object") {
    const parts = Object.entries(value).map(([k, v]) => `${k} ${typeof v === "object" ? JSON.stringify(v) : v}`);
    return parts.join(", ") || "none";
  }
  return String(value);
}

function Figures({ result }) {
  const rows = Object.entries(result).filter(([k]) => LABELS[k]);
  if (!rows.length) return <pre className="result">{JSON.stringify(result, null, 2)}</pre>;
  return (
    <dl className="figures">
      {rows.map(([k, v]) => (
        <div key={k}>
          <dt>{LABELS[k]}</dt>
          <dd>{figure(k, v)}</dd>
        </div>
      ))}
    </dl>
  );
}

function Result({ item }) {
  const r = item.result;
  if (!r) return <p className="muted">{item.note}</p>;
  if (item.key === "routing") {
    return (
      <>
        <p>
          {r.correct} of {r.cases} categories routed as expected ({Math.round(r.accuracy * 100)}%), ruleset {item.ruleset}.
        </p>
        {r.mismatches.length > 0 && (
          <ul>
            {r.mismatches.map((m) => (
              <li key={m.category}>
                {m.category}: expected {m.expected.join(" → ")}, got {m.got ? m.got.join(" → ") : "no route"}
              </li>
            ))}
          </ul>
        )}
      </>
    );
  }
  return (
    <>
      {item.finding && <p>{item.finding}</p>}
      <Figures result={r} />
    </>
  );
}

export function outcomeTone(item) {
  if (item.outcome) return OUTCOME[item.outcome]?.[0] ?? null;
  const r = item.result;
  if (item.key === "ledger_integrity" && r) return !r.ok ? "bad" : r.assurance === "CHECKPOINTED" ? "ok" : "warn";
  if (item.key === "replay_consistency" && r) return r.verdict === "VERIFIED_COMPLETE" ? "ok" : r.verdict === "MISMATCH" ? "bad" : "warn";
  if (item.key === "routing" && r) return r.mismatches.length ? "warn" : "ok";
  return null;
}

// The answer key says when its own source is unverified (routing.json: DEMO ASSUMPTION ACCEPTANCE_SOURCE_UNVERIFIED,
// PRIMARY_SOURCE_UNAVAILABLE). A pass against such a key is a pass against a transcription, so it is labelled.
export const sourceUnverified = (item) => item.source_status === "DEMO_ASSUMPTION"
  || /ACCEPTANCE_SOURCE_UNVERIFIED|PRIMARY_SOURCE_UNAVAILABLE/.test(item.source ?? "");

const TONE_WORD = { ok: "Pass", warn: "Needs attention", bad: "Fail" };

// The scorecard as an evaluation instrument: one row per check, read left to right as
// check → how it was measured → what was found → outcome. Each column keeps one kind of statement, so a method
// is never read as a result and a measurement without a verdict is never coloured as one.
export default function ScorecardView({ who }) {
  const { data, error, loading, reload } = useApi(who, "/analytics/scorecard");
  if (loading && !data) return <Loading what="Computing scorecard" />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  const tally = (pred) => data.items.filter(pred).length;
  return (
    <div className="scorecard">
      <div className="freshness">
        <span className="muted small">
          Generated {when(data.generated_at)}. Each line says how it was measured; nothing is shown for parts not yet evaluated.
        </span>
        <button className="ghost small" onClick={reload}>Refresh</button>
      </div>
      <Kpis label="Scorecard summary" items={[
        { label: "Checks", value: data.items.length },
        { label: "Pass", value: tally((i) => outcomeTone(i) === "ok"), tone: tally((i) => outcomeTone(i) === "ok") ? "ok" : undefined },
        { label: "Needs attention", value: tally((i) => outcomeTone(i) === "warn"), tone: tally((i) => outcomeTone(i) === "warn") ? "attention" : undefined },
        { label: "Fail", value: tally((i) => outcomeTone(i) === "bad"), tone: tally((i) => outcomeTone(i) === "bad") ? "bad" : undefined },
        { label: "Measured, no verdict", value: tally((i) => i.result && !outcomeTone(i)) },
        { label: "Not evaluated", value: tally((i) => i.kind === "NOT_EVALUATED") },
      ]} />
      <div className="instrument" role="list" aria-label="Evaluation checks">
        <div className="instrument-head" aria-hidden="true">
          <span>Check</span><span>How it was measured</span><span>What was found</span><span>Outcome</span>
        </div>
        {data.items.map((item) => {
          const [kindTone, label] = KIND[item.kind] ?? ["neutral", item.kind];
          const tone = outcomeTone(item) ?? (item.kind === "NOT_EVALUATED" ? "neutral" : kindTone);
          const verdict = OUTCOME[item.outcome];
          const measuredTone = outcomeTone(item);
          return (
            <article key={item.key} className={`score tone-${tone}`} role="listitem" aria-labelledby={`score-${item.key}`}>
              <div className="score-check">
                <h2 id={`score-${item.key}`}>{item.title}</h2>
                <p className="badges"><Badge tone="neutral">{label}</Badge></p>
              </div>
              <div className="score-method">
                {item.method ? (
                  <p className="method"><strong>How it was measured:</strong> {item.method}</p>
                ) : <p className="muted small">Method not supplied.</p>}
                {item.source && <p className="source">Answer key: {item.source}</p>}
                {sourceUnverified(item) && (
                  <p className="badges"><Badge tone="sample">Acceptance source unverified</Badge></p>
                )}
                {item.ruleset && <p className="source">Ruleset <code>{item.ruleset}</code></p>}
              </div>
              <div className="found">
                <strong>{item.result ? "What was found:" : "Why it is not evaluated:"}</strong>
                <Result item={item} />
              </div>
              <div className="score-outcome">
                {verdict ? <Badge tone={verdict[0]}>{verdict[1]}</Badge>
                  : measuredTone ? <span className={`derived tone-${measuredTone}`}>{TONE_WORD[measuredTone]} <span className="muted small">(from the result)</span></span>
                    : <span className="muted small">{item.result ? "No verdict: a measurement" : "Not evaluated"}</span>}
                {sourceUnverified(item) && <p className="muted small">Against an unverified transcription, not the official handbook.</p>}
              </div>
            </article>
          );
        })}
      </div>
    </div>
  );
}
