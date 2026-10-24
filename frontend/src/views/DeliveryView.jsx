import { useState } from "react";
import { api } from "../api.js";
import { Badge, Card, Empty, ErrorBox, Loading, StatTile, useApi, when } from "../components/ui.jsx";

const TONE = { DELIVERED: "ok", PENDING: "warn", SENDING: "warn", DEAD: "bad" };

export default function DeliveryView({ who, me }) {
  const [status, setStatus] = useState("");
  const health = useApi(who, "/notifications/health");
  const outbox = useApi(who, `/notifications/outbox${status ? `?status=${status}` : ""}`);
  const [attempts, setAttempts] = useState(null);
  const [error, setError] = useState(null);

  async function showAttempts(id) {
    try {
      setAttempts({ id, rows: await api(who, `/notifications/outbox/${id}/attempts`) });
    } catch (e) {
      setError(e);
    }
  }

  async function retry(id) {
    try {
      await api(who, `/notifications/outbox/${id}/retry`, { method: "POST" });
      outbox.reload();
      health.reload();
    } catch (e) {
      setError(e);
    }
  }

  const h = health.data;
  return (
    <div>
      <Card title="Delivery health">
        {health.loading && !h && <Loading />}
        <ErrorBox error={health.error} />
        {h && (
          <div className="stats">
            <StatTile label="Delivered" value={h.by_status.DELIVERED} />
            <StatTile label="Waiting" value={h.by_status.PENDING + h.by_status.SENDING} />
            <StatTile label="Dead letters" value={h.by_status.DEAD} />
            <StatTile
              label="Oldest undelivered"
              value={h.oldest_undelivered_age_seconds == null ? "—" : `${Math.round(h.oldest_undelivered_age_seconds / 60)} min`}
            />
            <StatTile
              label="First-try success (24 h)"
              value={h.first_try_success_rate_24h == null ? "—" : `${Math.round(h.first_try_success_rate_24h * 100)}%`}
              hint={h.first_tries_24h ? `of ${h.first_tries_24h} first attempts` : "no first attempts yet"}
            />
            <StatTile label="Delivered after a retry (24 h)" value={h.delivered_after_retry_24h ?? 0} />
          </div>
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
              {["PENDING", "SENDING", "DELIVERED", "DEAD"].map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>
        }
      >
        <ErrorBox error={error || outbox.error} />
        {outbox.data?.length === 0 && <Empty>No messages.</Empty>}
        {outbox.data?.length > 0 && (
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Queued</th>
                <th scope="col">Channel</th>
                <th scope="col">Template</th>
                <th scope="col">Status</th>
                <th scope="col">Attempts</th>
                <th scope="col">Last error</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {outbox.data.map((o) => (
                <tr key={o.id}>
                  <td>{when(o.created_at)}</td>
                  <td>{o.channel}</td>
                  <td>{o.template}</td>
                  <td><Badge tone={TONE[o.status]}>{o.status}</Badge></td>
                  <td>{o.attempts}</td>
                  <td>{o.last_error ?? "—"}</td>
                  <td className="actions">
                    <button className="secondary small" onClick={() => showAttempts(o.id)}>Attempts</button>
                    {o.status === "DEAD" && me.role === "BUREAU_HEAD" && (
                      <button className="small" onClick={() => retry(o.id)}>Retry</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {attempts && (
        <Card title={`Attempts for ${attempts.id.slice(0, 8)}`}>
          {attempts.rows.length === 0 && <Empty>No attempts yet.</Empty>}
          <ol className="timeline">
            {attempts.rows.map((a) => (
              <li key={a.attempt_no + a.finished_at}>
                #{a.attempt_no} <Badge tone={a.outcome === "DELIVERED" ? "ok" : "warn"}>{a.outcome}</Badge> via {a.provider}{" "}
                {a.error_category && <code>{a.error_category}</code>} <span className="muted">{when(a.finished_at)} · {a.worker}</span>
              </li>
            ))}
          </ol>
        </Card>
      )}
    </div>
  );
}
