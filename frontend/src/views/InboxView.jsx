import World from '../nebula/World.jsx';
import { useMemo, useState } from "react";
import { api } from "../api.js";
import { Icon } from "../components/Icons.jsx";
import { Card, Empty, ErrorBox, Loading, dateIST, useApi, useSingleFlight, when } from "../components/ui.jsx";

// Templates the alerts module marks as needing action soon; the rest are informational.
const URGENT = new Set(["deadline.breached", "deadline.escalated"]);
const MEANING = {
  "deadline.reminder": "A deadline on a case you handle is approaching.",
  "deadline.breached": "A deadline on a case you handle has passed.",
  "deadline.escalated": "An overdue case has been escalated to you.",
  "obligation.due": "A compliance item for your institution is due.",
  "case.update": "A case you follow has changed.",
};
const FILTERS = [["all", "All"], ["unread", "Unread"], ["urgent", "Urgent"]];

// The inbox as a signal stream: grouped by day (IST), unread signals pulse softly, urgent ones carry the
// warning mark, and choosing one opens its detail beside the stream.
export default function InboxView({ who, onNavigate }) {
  const { data, error, loading, reload } = useApi(who, "/notifications/inbox");
  const [busy, setBusy] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [filter, setFilter] = useState("all");
  const [openId, setOpenId] = useState(null);
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

  const keep = (n) => filter === "all" || (filter === "unread" ? !n.read_at : URGENT.has(n.template));
  const count = (f) => (data ?? []).filter((n) => f === "all" || (f === "unread" ? !n.read_at : URGENT.has(n.template))).length;
  const groups = useMemo(() => {
    const today = dateIST(new Date().toISOString());
    const out = [];
    for (const n of (data ?? []).filter(keep)) {
      const day = dateIST(n.created_at);
      const label = day === today ? "Today" : day;
      if (out.at(-1)?.label !== label) out.push({ label, items: [] });
      out.at(-1).items.push(n);
    }
    return out;
  }, [data, filter]); // eslint-disable-line react-hooks/exhaustive-deps
  const open = data?.find((n) => n.id === openId);

  return (
    <div className={`stream-layout${open ? " has-detail" : ""}`}>
      <World kind="inbox" records={(data ?? []).map(n=>({id:n.id,label:n.id.slice(0,8),category:n.template,state:n.read_at?'read':'unread',detail:n.read_at?'Read':'Unread',facts:[['Category',n.template],['Created',n.created_at],['Application',n.subject_id||'Linkage not supplied'],['Triggering event','Specific event linkage not supplied']]}))} onSelect={id=>setOpenId(id)} actionLabel="Inspect notification" />
      <Card title="Inbox" actions={<button className="secondary small" onClick={reload}><Icon name="refresh" /> Refresh</button>}>
        <div className="chips" role="group" aria-label="Show">
          {FILTERS.map(([key, label]) => (
            <button key={key} className={`chip${filter === key ? " on" : ""}`} aria-pressed={filter === key} onClick={() => setFilter(key)}>
              {label} <span className="num">{count(key)}</span>
            </button>
          ))}
        </div>
        {loading && !data && <Loading what="Loading signals" />}
        <ErrorBox error={error} onRetry={reload} />
        <ErrorBox error={actionError} />
        {data && data.length === 0 && <Empty>No notifications.</Empty>}
        {data && data.length > 0 && groups.length === 0 && <p className="muted">Nothing matches this filter.</p>}
        {groups.map((g) => (
          <section key={g.label} className="stream-day" aria-label={g.label}>
            <h3>{g.label}</h3>
            <ul className="stream">
              {g.items.map((n, i) => (
                <li key={n.id} className={`signal${n.read_at ? "" : " unread"}${URGENT.has(n.template) ? " urgent" : ""}${openId === n.id ? " open" : ""}`}
                  style={{ "--row": i }}>
                  <span className="signal-dot" aria-hidden="true" />
                  <button className="signal-main" onClick={() => setOpenId(n.id === openId ? null : n.id)} aria-expanded={openId === n.id}>
                    <span className="signal-subject">{n.subject}</span>
                    <span className="signal-meta muted">
                      {when(n.created_at)} · ref <code>{n.alert_id.slice(0, 8)}</code>
                      {!n.read_at && <span className="sr-only"> · unread</span>}
                    </span>
                  </button>
                  <span className="actions">
                    {URGENT.has(n.template) && <span className="badge warn">Urgent</span>}
                    {!n.read_at && (
                      <button className="secondary small" disabled={busy !== null} onClick={() => markRead(n.id)}
                        aria-label={`Mark "${n.subject}" from ${when(n.created_at)} as read`}>
                        {busy === n.id ? "Marking…" : "Mark read"}
                      </button>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        ))}
        <p className="muted small">Deadline alerts are acknowledged on the Alerts screen, by the role they are addressed to.</p>
      </Card>

      {open && (
        <aside className="card signal-detail" aria-label="Notification detail">
          <header className="card-head">
            <h2>{open.subject}</h2>
            <button className="ghost icon-only" aria-label="Close detail" onClick={() => setOpenId(null)}><Icon name="close" /></button>
          </header>
          <p>{MEANING[open.template] ?? "A notification from the approval system."}</p>
          <dl className="facts">
            <dt>Received</dt><dd>{when(open.created_at)}</dd>
            <dt>Reference</dt><dd><code>{open.alert_id}</code></dd>
            <dt>Read</dt><dd>{open.read_at ? when(open.read_at) : "Not yet"}</dd>
          </dl>
          <p className="muted small">Messages carry no case details by design; sign-in is how the details are seen.</p>
          {onNavigate && (
            <button className="secondary small" onClick={() => onNavigate("alerts")}>Open alerts to acknowledge</button>
          )}
        </aside>
      )}
    </div>
  );
}
