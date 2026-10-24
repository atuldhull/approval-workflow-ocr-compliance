import { useState } from "react";
import { api } from "../api.js";
import { Badge, Card, Empty, ErrorBox, Loading, useApi, when } from "../components/ui.jsx";

// Each layer reports what it actually proves. Green appears only for a layer that is fully verified; the headline
// is green only when every layer is.
export function checkpointState(v) {
  if (!v) return ["neutral", "Not checked"];
  if (!v.ok) return ["bad", v.status.replaceAll("_", " ")];
  if (v.assurance === "CHECKPOINTED") return ["ok", "Matches trusted checkpoint"];
  return ["warn", "No trusted checkpoint to compare with"];
}

export function replayState(r) {
  if (!r) return ["neutral", "Not run"];
  if (r.verdict === "VERIFIED_COMPLETE") return ["ok", "All events replayed and matched"];
  if (r.verdict === "CONSISTENT_SUBSET") return ["warn", "Consistent for the covered part only"];
  return ["bad", "Differences found"];
}

export function headline(chainOk, v, r) {
  if (chainOk === false || (v && !v.ok) || r?.verdict === "MISMATCH") return ["bad", "Integrity problem found"];
  const full = chainOk && v?.assurance === "CHECKPOINTED" && r?.verdict === "VERIFIED_COMPLETE";
  return full ? ["ok", "Fully verified"] : ["warn", "Partially verified - see each check below"];
}

const GAP_TEXT = {
  UNHANDLED_EVENT_TYPE: (g) => `${g.events} stored ${g.event_type} event(s) have no projector, so they were not checked`,
  UNKNOWN_EVENT_VERSION: (g) => `${g.projection}: ${g.events} event(s) of ${g.event} use a version it does not understand`,
  NO_LIVE_MODEL: (g) => `${g.projection} has no live model to compare against`,
};

export default function AuditView({ who, me }) {
  const verify = useApi(who, "/audit/verify");
  const chain = useApi(who, "/ledger/verify");
  const checkpoints = useApi(who, "/audit/checkpoints");
  const [replay, setReplay] = useState(null);
  const [busy, setBusy] = useState(null);
  const [actionError, setActionError] = useState(null);
  const canSign = ["AUDITOR", "BUREAU_HEAD"].includes(me.role);

  async function run(name, fn) {
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

  return (
    <div>
      <div className={`alert summary ${headTone}`} role="status">
        <Badge tone={headTone}>{headText}</Badge>
        {!replay && <span className="muted"> Run the replay check to complete the picture.</span>}
      </div>
      <ErrorBox error={actionError} />

      <div className="grid cards">
        <Card title="1. Hash chain" actions={<button className="secondary small" onClick={() => { chain.reload(); verify.reload(); }}>Re-check</button>}>
          {chain.loading && !chain.data && <Loading />}
          <ErrorBox error={chain.error} />
          {chain.data && (
            <p>
              <Badge tone={chain.data.ok ? "ok" : "bad"}>{chain.data.ok ? "Intact" : "Broken"}</Badge>{" "}
              {chain.data.ok ? `${chain.data.checked} entries link correctly.` : `At entry #${chain.data.first_bad_seq}: ${chain.data.detail}`}
            </p>
          )}
          <p className="muted small">Proves no entry changed after the one that follows it. On its own it cannot detect a rebuilt chain or deleted newest entries.</p>
        </Card>

        <Card title="2. Trusted checkpoint">
          {verify.loading && !v && <Loading />}
          <ErrorBox error={verify.error} />
          {v && (
            <>
              <p>
                <Badge tone={cpTone}>{cpText}</Badge>
              </p>
              <p>{v.detail}</p>
              <dl className="facts">
                <dt>Covers</dt>
                <dd>{v.checkpoint_seq ? `entries up to #${v.checkpoint_seq} (signed ${when(v.checkpoint_at)}, key ${v.checkpoint_key_id})` : "nothing yet"}</dd>
                {v.entries_after_checkpoint > 0 && (
                  <>
                    <dt>Not yet covered</dt>
                    <dd>{v.entries_after_checkpoint} newer entries (chain only, until the next checkpoint)</dd>
                  </>
                )}
                <dt>Witness</dt>
                <dd>{v.witness_kind ?? "not configured"}</dd>
                {v.unpublished_checkpoints > 0 && (
                  <>
                    <dt>Unpublished</dt>
                    <dd>{v.unpublished_checkpoints} checkpoint(s) signed but not yet handed to the witness</dd>
                  </>
                )}
              </dl>
            </>
          )}
          <p className="muted small">Checkpoints are integrity evidence for this system, not legal signatures on decisions.</p>
        </Card>

        <Card
          title="3. Replay consistency"
          actions={canSign && (
            <button className="secondary small" disabled={busy === "replay"}
              onClick={() => run("replay", async () => setReplay(await api(who, "/audit/replay", { method: "POST" })))}>
              {busy === "replay" ? "Running…" : "Run replay"}
            </button>
          )}
        >
          <p>
            <Badge tone={rpTone}>{rpText}</Badge>
          </p>
          {!replay && <p className="muted">Rebuilds the read models from the event log (read-only) and compares them with the live tables.</p>}
          {replay && (
            <>
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">Projection</th>
                    <th scope="col">Status</th>
                    <th scope="col">Events</th>
                    <th scope="col">Differences</th>
                  </tr>
                </thead>
                <tbody>
                  {replay.projections.map((p) => (
                    <tr key={p.name}>
                      <td>{p.name}</td>
                      <td><Badge tone={p.status === "MATCH" ? "ok" : p.status === "MISMATCH" ? "bad" : "warn"}>{p.status}</Badge></td>
                      <td>{p.events_applied}</td>
                      <td>{p.differences.length}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {replay.gaps.length > 0 && (
                <>
                  <h3>Not covered</h3>
                  <ul>{replay.gaps.map((g, i) => <li key={i}>{GAP_TEXT[g.kind]?.(g) ?? g.kind}</li>)}</ul>
                </>
              )}
            </>
          )}
          {!canSign && <p className="muted small">Running replay is limited to auditors and the bureau head.</p>}
        </Card>

        <Card
          title="Checkpoints"
          actions={canSign && (
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
          )}
        >
          <ErrorBox error={checkpoints.error} />
          {checkpoints.data?.length === 0 && <Empty>No checkpoints signed yet.</Empty>}
          {checkpoints.data?.length > 0 && (
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Signed</th>
                  <th scope="col">Head entry</th>
                  <th scope="col">Key</th>
                  <th scope="col">Witness</th>
                </tr>
              </thead>
              <tbody>
                {checkpoints.data.map((c) => (
                  <tr key={c.id}>
                    <td>{when(c.created_at)}</td>
                    <td>#{c.head_seq}</td>
                    <td><code>{c.key_id}</code></td>
                    <td>
                      <Badge tone={c.status === "PUBLISHED" ? "ok" : "warn"}>{c.status}</Badge>
                      {c.publish_error && <div className="muted small">{c.publish_error}</div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>

        <Card title="Waiting on other modules">
          <ul>
            <li>Person 1: events for stage transitions, deficiencies, decisions and EVC, so replay covers the whole case lifecycle.</li>
            <li>Person 2: events for deadline closure, pause and extension, obligations and letters.</li>
          </ul>
          {replay?.schemas_without_projector?.length > 0 && (
            <p className="muted small">Event schemas with no projector yet: {replay.schemas_without_projector.join(", ")}</p>
          )}
        </Card>
      </div>
    </div>
  );
}
