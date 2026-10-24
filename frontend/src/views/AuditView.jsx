import { useState } from "react";
import { api } from "../api.js";
import { Badge, Card, Empty, ErrorBox, Loading, useApi, when } from "../components/ui.jsx";

const TONE = { VERIFIED: "ok", NO_TRUSTED_CHECKPOINT: "warn" };

export default function AuditView({ who, me }) {
  const verify = useApi(who, "/audit/verify");
  const chain = useApi(who, "/ledger/verify");
  const checkpoints = useApi(who, "/audit/checkpoints");
  const [replay, setReplay] = useState(null);
  const [actionError, setActionError] = useState(null);
  const canSign = ["AUDITOR", "BUREAU_HEAD"].includes(me.role);

  async function run(fn) {
    setActionError(null);
    try {
      await fn();
    } catch (e) {
      setActionError(e);
    }
  }

  const v = verify.data;
  return (
    <div className="grid cards">
      <Card
        title="Ledger integrity"
        actions={<button className="secondary small" onClick={() => { verify.reload(); chain.reload(); }}>Re-check</button>}
      >
        {verify.loading && !v && <Loading />}
        <ErrorBox error={verify.error} />
        {v && (
          <>
            <p>
              <Badge tone={TONE[v.status] ?? "bad"}>{v.status.replaceAll("_", " ")}</Badge>
            </p>
            <p>{v.detail}</p>
            <dl className="facts">
              <dt>Entries checked</dt>
              <dd>{v.checked}</dd>
              <dt>Latest trusted checkpoint</dt>
              <dd>{v.checkpoint_seq ? `entry #${v.checkpoint_seq}, ${when(v.checkpoint_at)}, key ${v.checkpoint_key_id}` : "none"}</dd>
              {v.entries_after_checkpoint != null && (
                <>
                  <dt>Entries since checkpoint</dt>
                  <dd>{v.entries_after_checkpoint}</dd>
                </>
              )}
              {v.first_bad_seq && (
                <>
                  <dt>First bad entry</dt>
                  <dd>#{v.first_bad_seq}</dd>
                </>
              )}
              <dt>Independent witness</dt>
              <dd>{v.witness_configured ? "configured" : "not configured"}</dd>
            </dl>
          </>
        )}
        <p className="muted small">
          Checkpoints are integrity evidence for this system, not legal signatures on decisions.
        </p>
      </Card>

      <Card
        title="Checkpoints"
        actions={
          canSign && (
            <button className="small" onClick={() => run(async () => {
              await api(who, "/audit/checkpoints", { method: "POST" });
              checkpoints.reload();
              verify.reload();
            })}>
              Sign checkpoint now
            </button>
          )
        }
      >
        <ErrorBox error={actionError || checkpoints.error} />
        {checkpoints.data?.length === 0 && <Empty>No checkpoints signed yet.</Empty>}
        {checkpoints.data?.length > 0 && (
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Signed</th>
                <th scope="col">Head entry</th>
                <th scope="col">Entries</th>
                <th scope="col">Key</th>
              </tr>
            </thead>
            <tbody>
              {checkpoints.data.map((c) => (
                <tr key={c.id}>
                  <td>{when(c.created_at)}</td>
                  <td>#{c.head_seq}</td>
                  <td>{c.entry_count}</td>
                  <td><code>{c.key_id}</code></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <Card
        title="Replay consistency"
        actions={canSign && (
          <button className="secondary small" onClick={() => run(async () => setReplay(await api(who, "/audit/replay", { method: "POST" })))}>
            Run replay
          </button>
        )}
      >
        {!replay && <p className="muted">Rebuilds the read models from the event log (read-only) and compares them with the live tables.</p>}
        {replay && (
          <>
            <p>
              <Badge tone={replay.ok ? "ok" : "bad"}>{replay.ok ? "CONSISTENT" : "DIFFERENCES FOUND"}</Badge>
            </p>
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Projection</th>
                  <th scope="col">Status</th>
                  <th scope="col">Events</th>
                  <th scope="col">Records</th>
                  <th scope="col">Differences</th>
                </tr>
              </thead>
              <tbody>
                {replay.projections.map((p) => (
                  <tr key={p.name}>
                    <td>{p.name}</td>
                    <td><Badge tone={p.status === "MATCH" ? "ok" : "bad"}>{p.status}</Badge></td>
                    <td>{p.events_applied}</td>
                    <td>{p.records}</td>
                    <td>{p.differences.length}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {Object.keys(replay.unhandled_event_types).length > 0 && (
              <p className="muted small">Not replayed (no projector yet): {Object.keys(replay.unhandled_event_types).join(", ")}</p>
            )}
          </>
        )}
      </Card>

      <Card title="Hash chain only">
        {chain.data && (
          <p className={chain.data.ok ? "ok" : "error"}>
            {chain.data.ok ? `Intact (${chain.data.checked} entries)` : `Broken at entry #${chain.data.first_bad_seq}: ${chain.data.detail}`}
          </p>
        )}
        <ErrorBox error={chain.error} />
      </Card>
    </div>
  );
}
