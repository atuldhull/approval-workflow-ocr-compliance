import { useState } from "react";
import { api } from "../api.js";
import { Badge, Card, Empty, ErrorBox, Loading, StatTile, useApi, useSingleFlight, when } from "../components/ui.jsx";
import { STATUS, errorText, outcomeText } from "../deliveryText.js";

const pct = (r) => (r == null ? "—" : `${Math.round(r * 100)}%`);

export default function DeliveryView({ who, me }) {
  const [status, setStatus] = useState("");
  const health = useApi(who, "/notifications/health");
  const outbox = useApi(who, `/notifications/outbox${status ? `?status=${status}` : ""}`);
  const [attempts, setAttempts] = useState(null);
  const [error, setError] = useState(null);
  const [confirming, setConfirming] = useState(null);   // id awaiting a second click
  const [retrying, setRetrying] = useState(null);
  const [notice, setNotice] = useState(null);
  const once = useSingleFlight();
  const canRequeue = me.role === "BUREAU_HEAD";

  async function showAttempts(id) {
    try {
      setAttempts({ id, rows: await api(who, `/notifications/outbox/${id}/attempts`) });
    } catch (e) {
      setError(e);
    }
  }

  const requeue = (id) => once(async () => {
    setRetrying(id);
    setError(null);
    try {
      await api(who, `/notifications/outbox/${id}/retry`, { method: "POST" });
      setNotice("Requeued. The worker will try again; recipients already reached will not get it twice.");
      setConfirming(null);
      refresh();
    } catch (e) {
      setError(e);
    } finally {
      setRetrying(null);
    }
  });

  function refresh() {
    outbox.reload();
    health.reload();
    if (attempts) showAttempts(attempts.id);
  }

  const h = health.data;
  return (
    <div>
      <Card title="Delivery health" actions={<button className="secondary small" onClick={refresh}>Refresh</button>}>
        {health.loading && !h && <Loading />}
        <ErrorBox error={health.error} onRetry={health.reload} />
        {h && (
          <>
            <Pipeline counts={h.by_status} />
            <div className="stats">
              <StatTile
                label="Oldest undelivered"
                value={h.oldest_undelivered_age_seconds == null ? "—" : `${Math.round(h.oldest_undelivered_age_seconds / 60)} min`}
              />
              <StatTile label="First-try success (24 h)" value={pct(h.first_try_success_rate_24h)}
                hint={h.first_tries_24h ? `of ${h.first_tries_24h} first attempts` : "no first attempts yet"} />
              <StatTile label="Delivered after a retry (24 h)" value={h.delivered_after_retry_24h ?? 0} />
            </div>
            {h.providers?.email === "not_configured" && (
              <div className="alert preview" role="note">
                Email is not configured in this deployment, so email messages end as dead letters ({errorText("NOT_CONFIGURED")}).
                In-app delivery still works. SMS here is a mock and sends nothing.
              </div>
            )}
            {h.stalled_sending > 0 && (
              <div className="alert preview" role="note">
                {h.stalled_sending} message(s) were being sent by a worker that stopped. Another worker picks them up
                automatically; a message may reach a recipient twice.
              </div>
            )}
            {h.lease_lost_24h > 0 && (
              <p className="muted small">{h.lease_lost_24h} attempt(s) in the last 24 h were superseded by another worker.</p>
            )}
          </>
        )}
        <p className="muted small">Each recipient gets a separate message, so no one sees another recipient's address. Email and SMS are delivered at least once: a retry after an unclear provider failure can repeat a message to that recipient.</p>
      </Card>

      <Card
        title="Outbox"
        actions={
          <label className="inline">
            Status
            <select value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">All</option>
              {Object.keys(STATUS).map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>
        }
      >
        <dl className="legend">
          {Object.entries(STATUS).map(([k, v]) => (
            <div key={k}>
              <dt><Badge tone={v.tone}>{k}</Badge></dt>
              <dd>{v.text}</dd>
            </div>
          ))}
        </dl>
        <ErrorBox error={error || outbox.error} onRetry={error ? undefined : outbox.reload} />
        {notice && <p className="ok" role="status">{notice}</p>}
        {outbox.loading && !outbox.data && <Loading />}
        {outbox.data?.length === 0 && <Empty>{status ? `No ${status.toLowerCase()} messages.` : "No messages yet."}</Empty>}
        {outbox.data?.length > 0 && (
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Queued</th>
                <th scope="col">Channel</th>
                <th scope="col">Template</th>
                <th scope="col">Status</th>
                <th scope="col">Attempts</th>
                <th scope="col">Last problem</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {outbox.data.map((o) => {
                const name = `${o.template} by ${o.channel}, queued ${when(o.created_at)}`;
                return (
                  <tr key={o.id}>
                    <td>{when(o.created_at)}</td>
                    <td>{o.channel}</td>
                    <td>{o.template}</td>
                    <td><Badge tone={STATUS[o.status]?.tone}>{o.status}</Badge></td>
                    <td>{o.attempts}</td>
                    <td>{errorText(o.last_error) ?? "—"}</td>
                    <td className="actions">
                      <button className="secondary small" aria-label={`Attempts for ${name}`} onClick={() => showAttempts(o.id)}>
                        Attempts
                      </button>
                      {o.status === "DEAD" && canRequeue && confirming !== o.id && (
                        <button className="small" aria-label={`Requeue ${name}`} disabled={retrying !== null}
                          onClick={() => { setNotice(null); setConfirming(o.id); }}>
                          Requeue…
                        </button>
                      )}
                      {confirming === o.id && (
                        <span className="confirm" role="group" aria-label="Confirm requeue">
                          <span className="small">Try again with a fresh set of attempts? Recipients already reached are skipped.</span>
                          <button className="small" disabled={retrying !== null} onClick={() => requeue(o.id)}>
                            {retrying === o.id ? "Requeueing…" : "Yes, requeue"}
                          </button>
                          <button className="secondary small" disabled={retrying !== null} onClick={() => setConfirming(null)}>Cancel</button>
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        {!canRequeue && <p className="muted small">Only the bureau head can requeue dead letters.</p>}
      </Card>

      {attempts && (
        <Card title={`Attempts for message ${attempts.id.slice(0, 8)}`}>
          {attempts.rows.length === 0 && <Empty>No attempts yet.</Empty>}
          <ol className="timeline">
            {attempts.rows.map((a) => (
              <li key={`${a.attempt_no}-${a.finished_at}`}>
                #{a.attempt_no}{" "}
                <Badge tone={a.outcome === "DELIVERED" ? "ok" : a.outcome === "PERMANENT" ? "bad" : "warn"}>{outcomeText(a.outcome)}</Badge>{" "}
                via {a.provider}
                {a.error_category && <span className="muted"> · {errorText(a.error_category)}</span>}
                <span className="muted"> · {when(a.finished_at)}</span>
              </li>
            ))}
          </ol>
        </Card>
      )}
    </div>
  );
}

// 2D: messages flow from pending through sending to delivered; dead letters branch off. Packets move on a
// lane only while that lane has messages in it, so motion means traffic.
function Pipeline({ counts }) {
  const lanes = [["PENDING", "Pending"], ["SENDING", "Sending"], ["DELIVERED", "Delivered"]];
  const flowing = (counts.PENDING ?? 0) + (counts.SENDING ?? 0) > 0;
  return (
    <ol className={`pipeline${flowing ? " flowing" : ""}`} aria-label="Messages by state">
      {lanes.map(([k, label], i) => (
        <li key={k} className={`pl-node ${k.toLowerCase()}`}>
          <span className="pl-count num">{counts[k] ?? 0}</span>
          <span className="pl-label">{label}{k === "PENDING" ? " (waiting or between retries)" : ""}</span>
          {i < lanes.length - 1 && <span className="pl-lane" aria-hidden="true"><i /><i /><i /></span>}
        </li>
      ))}
      <li className="pl-node dead">
        <span className="pl-count num">{counts.DEAD ?? 0}</span>
        <span className="pl-label">Dead letters</span>
      </li>
    </ol>
  );
}
