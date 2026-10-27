import { useState } from "react";
import SpatialFigure from "../operations/World.jsx";
import { auditRecords } from "../operations/semanticData.js";
import { api } from "../api.js";
import { Icon } from "../components/Icons.jsx";
import { Badge, Empty, ErrorBox, Inspector, Loading, useApi, useSingleFlight, when } from "../components/ui.jsx";

// Each layer reports what it actually proves. Green appears only for a layer that is fully verified; the headline
// is green only when every layer is.
export function checkpointState(v) {
  if (!v) return ["neutral", "Not checked"];
  if (!v.ok) return ["bad", v.status.replaceAll("_", " ")];
  if (v.assurance === "CHECKPOINTED") return ["ok", "Anchored through the latest entry"];
  if (v.assurance === "CHECKPOINTED_WITH_NEWER_ENTRIES") {
    return ["warn", `Anchored up to #${v.checkpoint_seq}; ${v.entries_after_checkpoint} newer entries not anchored yet`];
  }
  return ["warn", "No trusted checkpoint to compare with"];
}

export function replayState(r) {
  if (!r) return ["neutral", "Not run"];
  if (r.verdict === "VERIFIED_COMPLETE") return ["ok", "All events replayed and matched"];
  if (r.verdict === "CONSISTENT_SUBSET") return ["warn", "Consistent for the covered part only"];
  return ["bad", "Differences found"];
}

// Replay checks read models against events; it is not a substitute for an independent checkpoint, so it never
// lifts a chain-only or partly anchored result.
export function headline(chainOk, v, r) {
  if (chainOk === false || (v && !v.ok) || r?.verdict === "MISMATCH") return ["bad", "Integrity problem found"];
  if (!chainOk || !v) return ["neutral", "Checking…"];
  if (v.assurance === "CHAIN_ONLY") return ["warn", "Chain intact, but not anchored by a trusted checkpoint"];
  if (v.assurance === "CHECKPOINTED_WITH_NEWER_ENTRIES") {
    return ["warn", `Anchored up to entry #${v.checkpoint_seq}; the ${v.entries_after_checkpoint} newest entries are not anchored yet`];
  }
  if (r?.verdict !== "VERIFIED_COMPLETE") {
    return ["warn", r ? "History anchored through the latest entry; replay covered only part of it"
                      : "History anchored through the latest entry; replay not run"];
  }
  return ["ok", "Fully verified through the latest entry"];
}

const GAP_TEXT = {
  UNHANDLED_EVENT_TYPE: (g) => `${g.events} stored ${g.event_type} event(s) have no projector, so they were not checked`,
  UNKNOWN_EVENT_VERSION: (g) => `${g.projection}: ${g.events} event(s) of ${g.event} use a version it does not understand`,
  NO_LIVE_MODEL: (g) => `${g.projection} has no live model to compare against`,
  NO_PROJECTORS: () => "No projector ran, so nothing was replayed",
  UNKNOWN_PROJECTOR: (g) => `Projector "${g.projection}" was requested but is not registered`,
  NO_FIELDS_COMPARED: (g) => `${g.projection} compares no fields, so a match proves nothing`,
  UNREADABLE_EVENT: (g) => `Entry #${g.seq} (${g.event_type}) could not be read by ${g.projection} - possible tampering`,
};

export const gapText = (g) => GAP_TEXT[g.kind]?.(g) ?? g.kind;

// A plain-text summary for the operator to keep. Built from results already on screen: statuses, counts and entry
// numbers only - never event payloads, case notes or personal data.
export function evidenceSummary({ chain, verify, replay, checkpoints, generatedAt }) {
  const lines = [
    "Approval workflow - integrity summary",
    `Generated: ${generatedAt}`,
    "",
    `Overall: ${headline(chain?.ok, verify, replay)[1]}`,
    `1. Hash chain: ${chain ? (chain.ok ? `intact, ${chain.checked} entries` : `BROKEN at entry #${chain.first_bad_seq}`) : "not checked"}`,
  ];
  if (verify) {
    lines.push(`2. Trusted checkpoint: ${verify.status} (assurance ${verify.assurance})`);
    if (verify.checkpoint_seq) lines.push(`   covers entries up to #${verify.checkpoint_seq}, signed ${when(verify.checkpoint_at)} with key ${verify.checkpoint_key_id}`);
    if (verify.entries_after_checkpoint) lines.push(`   ${verify.entries_after_checkpoint} newer entries are not anchored yet`);
    lines.push(`   witness: ${verify.witness_kind ?? "not configured"}`);
    if (verify.unpublished_checkpoints) lines.push(`   ${verify.unpublished_checkpoints} checkpoint(s) signed but not yet published`);
  } else {
    lines.push("2. Trusted checkpoint: not checked");
  }
  if (replay) {
    lines.push(`3. Replay: ${replay.verdict}`);
    for (const p of replay.projections) lines.push(`   ${p.name}: ${p.status}, ${p.events_applied} events, ${p.differences.length} differences`);
    for (const g of replay.gaps) lines.push(`   not covered: ${gapText(g)}`);
  } else {
    lines.push("3. Replay: not run");
  }
  if (checkpoints?.length) lines.push("", `Checkpoints on record: ${checkpoints.length} (${checkpoints.filter((c) => c.status === "PENDING").length} pending)`);
  lines.push("", "A local-file witness is a demo only and not independent long-term assurance.",
    "Checkpoints are integrity evidence for this system, not legal signatures on decisions.");
  return lines.join("\n");
}

const LAYER_TONE = { checked: "ok", anchored: "ok", recorded: "warn", broken: "bad", pending: "warn", unknown: "neutral" };

// The assurance console. Three independent layers sit side by side at the top, each with its own result and its
// own action, so a reader sees all three verdicts before anything else and never mistakes one for another.
// Below: the recorded history this screen can actually read (checkpoints, replay projections) and an inspector
// for whichever layer or checkpoint is selected, with the spatial figure as a companion to it.
export default function AuditView({ who, me }) {
  const verify = useApi(who, "/audit/verify");
  const chain = useApi(who, "/ledger/verify");
  const checkpoints = useApi(who, "/audit/checkpoints");
  const [replay, setReplay] = useState(null);
  const [busy, setBusy] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [selected, setSelected] = useState(0);
  const [copied, setCopied] = useState(null);
  const canSign = ["AUDITOR", "BUREAU_HEAD"].includes(me.role);
  const once = useSingleFlight();

  const run = (name, fn) => once(() => perform(name, fn));

  async function perform(name, fn) {
    setActionError(null);
    setBusy(name);
    try {
      await fn();
    } catch (e) {
      setActionError(e);
    } finally {
      setBusy(null);
      checkpoints.reload();
      verify.reload();
    }
  }

  const v = verify.data;
  const [headTone, headText] = headline(chain.data?.ok, v, replay);
  const [cpTone, cpText] = checkpointState(v);
  const [rpTone, rpText] = replayState(replay);
  const pending = checkpoints.data?.filter((c) => c.status === "PENDING") ?? [];
  const records = auditRecords(chain.data, v, replay, checkpoints.data || []);
  const focus = records[selected] ?? records[0];
  const summary = () => evidenceSummary({ chain: chain.data, verify: v, replay, checkpoints: checkpoints.data,
    generatedAt: when(new Date().toISOString()) });

  async function copySummary() {
    try {
      await navigator.clipboard.writeText(summary());
      setCopied("Summary copied.");
    } catch {
      setCopied("Copy is not available here; use Download.");
    }
  }

  function downloadSummary() {
    const url = URL.createObjectURL(new Blob([summary()], { type: "text/plain" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "integrity-summary.txt";
    a.click();
    URL.revokeObjectURL(url);
    setCopied("Summary downloaded.");
  }

  const layer = (i) => ({ selected: selected === i, onInspect: () => setSelected(i) });

  return (
    <div className="audit">
      <section className={`assurance-head tone-${headTone}`} aria-label="Overall assurance">
        <div className="assurance-verdict" role="status">
          <span className="assurance-label">Overall</span>
          <Badge tone={headTone}>{headText}</Badge>
          {!replay && <span className="muted small">Run the replay check to complete the picture.</span>}
        </div>
        <div className="actions">
          <button className="secondary small" onClick={() => copySummary()}><Icon name="copy" /> Copy summary</button>
          <button className="secondary small" onClick={() => downloadSummary()}><Icon name="download" /> Download summary</button>
          {copied && <span className="muted small" role="status">{copied}</span>}
        </div>
      </section>
      <ErrorBox error={actionError} />

      <div className="assurance-layers">
        <Layer kind="continuity" title="1. Hash chain" icon="chain" state={records[0].state} {...layer(0)}
          question="Has any entry changed since the one after it was written?"
          action={<button className="secondary small" onClick={() => { chain.reload(); verify.reload(); }}><Icon name="refresh" /> Re-check</button>}>
          {chain.loading && !chain.data && <Loading rows={1} />}
          <ErrorBox error={chain.error} />
          {chain.data && (
            <>
              <p className="layer-result">
                <Badge tone={chain.data.ok ? "ok" : "bad"}>{chain.data.ok ? "Intact" : "Broken"}</Badge>
                <span><span className="layer-figure num">{chain.data.checked}</span> <span className="muted">entries checked</span></span>
              </p>
              <p className="small">{chain.data.ok ? `${chain.data.checked} entries link correctly.` : `At entry #${chain.data.first_bad_seq}: ${chain.data.detail}`}</p>
            </>
          )}
          <p className="layer-limit">On its own it cannot detect a rebuilt chain or deleted newest entries.</p>
        </Layer>

        <Layer kind="witness" title="2. Trusted checkpoint" icon="seal" state={records[1].state} {...layer(1)}
          question="Does a signed checkpoint, held by a witness, vouch for the chain?"
          action={canSign && (
            <span className="actions">
              {pending.length > 0 && (
                <button className="secondary small" disabled={busy !== null}
                  onClick={() => run("publish", () => api(who, "/audit/checkpoints/publish", { method: "POST" }))}>
                  Retry publication
                </button>
              )}
              <button className="small" disabled={busy !== null || pending.length > 0}
                onClick={() => run("sign", () => api(who, "/audit/checkpoints", { method: "POST" }))}>
                {busy === "sign" ? "Signing…" : "Sign checkpoint now"}
              </button>
            </span>
          )}>
          {verify.loading && !v && <Loading rows={1} />}
          <ErrorBox error={verify.error} />
          {v && (
            <>
              <p className="layer-result"><Badge tone={cpTone}>{cpText}</Badge></p>
              <dl className="facts compact">
                <dt>Covers</dt>
                <dd>{v.checkpoint_seq ? `entries up to #${v.checkpoint_seq} (signed ${when(v.checkpoint_at)}, key ${v.checkpoint_key_id})` : "nothing yet"}</dd>
                {v.entries_after_checkpoint > 0 && (<><dt>Not yet covered</dt><dd>{v.entries_after_checkpoint} newer entries (chain only, until the next checkpoint)</dd></>)}
                <dt>Witness</dt>
                <dd>
                  {v.witness_kind ?? "not configured"}{" "}
                  {v.witness_kind?.includes("DEMO ONLY") && <Badge tone="warn">DEMO ONLY - same machine, not independent</Badge>}
                </dd>
                {v.unpublished_checkpoints > 0 && (<><dt>Unpublished</dt><dd>{v.unpublished_checkpoints} checkpoint(s) signed but not yet handed to the witness</dd></>)}
              </dl>
              {v.detail && <p className="small muted">{v.detail}</p>}
            </>
          )}
          <p className="layer-limit">Integrity evidence for this system, not legal signatures on decisions.</p>
        </Layer>

        <Layer kind="replay" title="3. Replay consistency" icon="replay" state={records[2].state} {...layer(2)}
          question="Do the live tables match what the event log rebuilds?"
          action={canSign && (
            <button className="secondary small" disabled={busy === "replay"}
              onClick={() => run("replay", async () => { setReplay(await api(who, "/audit/replay", { method: "POST" })); setSelected(2); })}>
              {busy === "replay" ? "Running…" : "Run replay"}
            </button>
          )}>
          <p className="layer-result"><Badge tone={rpTone}>{rpText}</Badge></p>
          {replay ? (
            <p className="small">
              <span className="num">{replay.projections.length}</span> projections compared ·{" "}
              <span className="num">{replay.gaps.length}</span> not covered
            </p>
          ) : (
            <p className="small muted">Rebuilds the read models from the event log (read-only) and compares them with the live tables.</p>
          )}
          <p className="layer-limit">
            {canSign ? "A match is read-model consistency, not independent anchoring." : "Running replay is limited to auditors and the bureau head."}
          </p>
        </Layer>
      </div>

      <div className="audit-workspace">
        <div className="audit-history">
          {replay && (
            <section className="card" aria-labelledby="replay-title">
              <header className="card-head"><h2 id="replay-title">Replay result</h2><Badge tone={rpTone}>{rpText}</Badge></header>
              <div className="table-wrap">
                <table className="table" tabIndex={0} aria-label="Replay projections">
                  <thead><tr><th scope="col">Projection</th><th scope="col">Status</th><th scope="col" className="num">Events</th><th scope="col">Differences</th></tr></thead>
                  <tbody>
                    {replay.projections.map((p) => (
                      <tr key={p.name}>
                        <td>{p.name}</td>
                        <td><Badge tone={p.status === "MATCH" ? "ok" : p.status === "MISMATCH" ? "bad" : "warn"}>{p.status}</Badge></td>
                        <td className="num">{p.events_applied}</td>
                        <td>
                          {p.differences.length}
                          {p.differences.length > 0 && (
                            <details>
                              <summary>Show</summary>
                              <ul className="small">
                                {p.differences.map((d, i) => (
                                  <li key={i}>
                                    record <code>{String(d.key).slice(0, 8)}</code>:{" "}
                                    {d.problem ? d.problem.replaceAll("_", " ") : `${d.field} is "${d.live}" live but "${d.replayed}" from events`}
                                  </li>
                                ))}
                              </ul>
                            </details>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {replay.gaps.length > 0 && (
                <>
                  <h3>Not covered</h3>
                  <ul className="gap-list">{replay.gaps.map((g, i) => <li key={i}>{gapText(g)}</li>)}</ul>
                </>
              )}
              {replay.schemas_without_projector?.length > 0 && (
                <p className="muted small">Event schemas with no projector yet: {replay.schemas_without_projector.join(", ")}</p>
              )}
            </section>
          )}

          <section className="card" aria-labelledby="checkpoints-title">
            <header className="card-head">
              <h2 id="checkpoints-title">Checkpoint history {checkpoints.data && <span className="count num">{checkpoints.data.length}</span>}</h2>
              <button className="ghost small" onClick={checkpoints.reload}><Icon name="refresh" /> Refresh</button>
            </header>
            {pending.length > 0 && (
              <div className="alert preview" role="note">
                {pending.length} checkpoint(s) are signed but the witness has not accepted them yet, so they do not count as
                trusted evidence. {canSign ? "\"Retry publication\" hands the same signed copy over again; nothing is re-signed." : "An auditor or the bureau head can retry publication."}
              </div>
            )}
            {checkpoints.loading && !checkpoints.data && <Loading rows={2} />}
            <ErrorBox error={checkpoints.error} />
            {checkpoints.data?.length === 0 && <Empty>No checkpoints signed yet.</Empty>}
            {checkpoints.data?.length > 0 && (
              <ol className="event-history" aria-label="Signed checkpoints, newest first">
                {checkpoints.data.map((c, i) => ({ c, index: 3 + i })).reverse().map(({ c, index }) => (
                  <li key={c.id}>
                    <button className={`history-row${selected === index ? " is-selected" : ""}`} aria-pressed={selected === index}
                      onClick={() => setSelected(index)}>
                      <span className={`history-mark ${c.status === "PUBLISHED" ? "ok" : "warn"}`} aria-hidden="true" />
                      <span className="history-main">
                        <span>Checkpoint at entry <strong className="num">#{c.head_seq}</strong></span>
                        <span className="muted small">{when(c.created_at)} · key <code>{c.key_id}</code></span>
                        {c.publish_error && <span className="small error">{c.publish_error}</span>}
                      </span>
                      <Badge tone={c.status === "PUBLISHED" ? "ok" : "warn"}>{c.status}</Badge>
                    </button>
                  </li>
                ))}
              </ol>
            )}
            <p className="source">
              This screen reads verification summaries and signed checkpoints. Individual ledger events are listed per case
              (Cases, audit timeline); the API has no ledger-wide event listing to show here.
            </p>
          </section>

          <section className="card quiet" aria-labelledby="waiting-title">
            <header className="card-head"><h2 id="waiting-title">Not yet covered by replay</h2></header>
            <ul className="small muted plain-list">
              <li>Workflow: events for stage transitions, deficiencies, decisions and EVC, so replay covers the whole case lifecycle.</li>
              <li>Deadlines and compliance: events for deadline closure, pause and extension, obligations and letters.</li>
            </ul>
          </section>
        </div>

        <Inspector label="Assurance detail" eyebrow={selected < 3 ? `Layer ${selected + 1} of 3` : "Signed checkpoint"} title={focus.label}
          className="audit-inspector">
          <SpatialFigure records={records.slice(0, 3)} selected={selected < 3 ? selected : 1} caption="Continuity · witness · replay" />
          <div key={focus.id} className="inspector-swap">
            <p className="inspector-state"><Badge tone={LAYER_TONE[focus.state] ?? "neutral"}>{focus.detail}</Badge></p>
            <dl className="facts">
              {focus.facts.map(([k, val]) => <div key={k}><dt>{k}</dt><dd>{String(val ?? "Not supplied")}</dd></div>)}
            </dl>
            <p className="muted small">Selecting a layer or checkpoint only inspects it; it never signs, publishes or re-runs anything.</p>
          </div>
        </Inspector>
      </div>
    </div>
  );
}

function Layer({ kind, title, icon, question, state, selected, onInspect, action, children }) {
  return (
    <section className={`assurance-layer layer-${kind} state-${state}${selected ? " is-selected" : ""}`} aria-labelledby={`layer-${kind}`}>
      <header className="layer-head">
        <span className="layer-icon" aria-hidden="true"><Icon name={icon} size={18} /></span>
        <h2 id={`layer-${kind}`}>{title}</h2>
        <button className="ghost small layer-inspect" aria-pressed={selected} onClick={onInspect}>Inspect</button>
      </header>
      <p className="layer-question">{question}</p>
      <div className="layer-body">{children}</div>
      {action && <footer className="layer-actions">{action}</footer>}
    </section>
  );
}
