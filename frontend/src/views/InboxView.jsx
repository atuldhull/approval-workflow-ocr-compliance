import { useState } from "react";
import { api } from "../api.js";
import { Card, Empty, ErrorBox, Loading, useApi, useSingleFlight, when } from "../components/ui.jsx";

export default function InboxView({ who }) {
  const { data, error, loading, reload } = useApi(who, "/notifications/inbox");
  const [busy, setBusy] = useState(null);
  const [actionError, setActionError] = useState(null);
  const once = useSingleFlight();

  const markRead = (id) => once(async () => {
    setBusy(id);
    setActionError(null);
    try {
      await api(who, `/notifications/inbox/${id}/read`, { method: "POST" });
      reload();
    } catch (e) {
      setActionError(e);
    } finally {
      setBusy(null);
    }
  });

  return (
    <Card title="Inbox" actions={<button className="secondary small" onClick={reload}>Refresh</button>}>
      {loading && !data && <Loading />}
      <ErrorBox error={error} onRetry={reload} />
      <ErrorBox error={actionError} />
      {data && data.length === 0 && <Empty>No notifications.</Empty>}
      {data && data.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Notification</th>
              <th scope="col">Received</th>
              <th scope="col">Reference</th>
              <th scope="col">Actions</th>
            </tr>
          </thead>
          <tbody>
            {data.map((n) => (
              <tr key={n.id} className={n.read_at ? "" : "unread"}>
                <td>{n.subject}</td>
                <td>{when(n.created_at)}</td>
                <td>
                  <code>{n.alert_id.slice(0, 8)}</code>
                </td>
                <td className="actions">
                  {!n.read_at && (
                    <button className="secondary small" disabled={busy !== null} onClick={() => markRead(n.id)}
                      aria-label={`Mark "${n.subject}" from ${when(n.created_at)} as read`}>
                      {busy === n.id ? "Marking…" : "Mark read"}
                    </button>
                  )}
                  <button className="secondary small" disabled title="Acknowledgement is recorded by the alerts module (Person 2), not built yet">
                    Acknowledge
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="muted small">Acknowledging an alert will be enabled when the alerts module provides it.</p>
    </Card>
  );
}
