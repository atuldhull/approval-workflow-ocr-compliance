import { useMemo, useState } from "react";
import { api } from "../api.js";
import { Icon } from "../components/Icons.jsx";
import { Card, Empty, ErrorBox, Inspector, Loading, dateIST, useApi, useSingleFlight, when } from "../components/ui.jsx";
import Lifecycle from "../components/Lifecycle.jsx";

// Templates that need action soon; the rest are informational.
const URGENT = new Set(["deadline.breached", "deadline.escalated", "deadline.missed", "compliance.evidence_rejected"]);
// Fallback wording for messages delivered before the server described them (text and action come with each item).
const MEANING = {
  "deadline.reminder": "A deadline on a case you handle is approaching.",
  "deadline.breached": "A deadline on a case you handle has passed.",
  "deadline.escalated": "An overdue case has been escalated to you.",
  "obligation.due": "A compliance item for your institution is due.",
  "case.update": "A case you follow has changed.",
};
const reference = (n) => n.case_ref ? `case ${n.case_ref}` : `ref ${String(n.alert_id ?? n.source_event_id ?? "").slice(0, 8)}`;
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
    <div className="inbox">
    <Lifecycle here="inbox" />
    <div className={`split stream-layout${open ? " has-detail" : ""}`}>
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
                      {when(n.created_at)} · <code>{reference(n)}</code>
                      {!n.read_at && <span className="sr-only"> · unread</span>}
                    </span>
                  </button>
                  <span className="actions">
                    {URGENT.has(n.template) && <span className="badge warn">Urgent</span>}
                    {!n.read_at && (
                      <button className="secondary small" disabled={busy !== null} onClick={() => markRead(n.id)}
                        aria-label={`Mark read: "${n.subject}" from ${when(n.created_at)} as read`}>
                        {busy === n.id ? "Marking…" : "Mark read"}
                      </button>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        ))}
        <p className="muted small">Deadline alerts are acknowledged on the Alerts screen, by the role they are addressed to. Other notices tell you that something was recorded on a case.</p>
      </Card>

      <div className="split-detail">
        {open ? (
          <Inspector label="Notification detail" eyebrow={open.read_at ? "Read" : "Unread"} title={open.subject} onClose={() => setOpenId(null)}>
            <div key={open.id} className="inspector-swap">
              <p>{open.text ?? MEANING[open.template] ?? "A notification from the approval system."}</p>
              {open.action && <p className="small"><strong>What to do:</strong> {open.action}</p>}
              <dl className="facts">
                <dt>Received</dt><dd>{when(open.created_at)}</dd>
                {open.case_ref && <><dt>Case</dt><dd><code>{open.case_ref}</code></dd></>}
                {open.alert_id
                  ? <><dt>Alert reference</dt><dd><code>{open.alert_id}</code></dd></>
                  : open.source_event_id && <><dt>Recorded event</dt><dd><code>{open.source_event_id}</code></dd></>}
                <dt>Read</dt><dd>{open.read_at ? when(open.read_at) : "Not yet"}</dd>
              </dl>
              <p className="muted small">Messages name a case by its short reference, the rule and the due date; never a person, an address or free text.</p>
              <div className="actions">
                {!open.read_at && (
                  <button className="secondary small" disabled={busy !== null} onClick={() => markRead(open.id)}>
                    {busy === open.id ? "Marking…" : "Mark read"}
                  </button>
                )}
                {onNavigate && <Links n={open} onNavigate={onNavigate} />}
              </div>
            </div>
          </Inspector>
        ) : (
          <div className="card placeholder-case"><Empty>Choose a notice to see what it means and where to act on it.</Empty></div>
        )}
      </div>
    </div>
    </div>
  );
}

// Where to act on a notice: the case, the obligation, the EVC schedule, or the alert to acknowledge. Each link is
// offered only when the server named that record; navigation still checks the role's screens.
function Links({ n, onNavigate }) {
  const links = n.links ?? {};
  return (
    <>
      {links.obligation_id && (
        <button className="ghost small" onClick={() => onNavigate("compliance", { obligationId: links.obligation_id })}>Open the obligation</button>
      )}
      {links.evc_request_id && <button className="ghost small" onClick={() => onNavigate("evc")}>Open EVC scheduling</button>}
      {links.application_id && (
        <button className="ghost small" onClick={() => onNavigate("applications", { caseId: links.application_id })}>Open the case</button>
      )}
      {n.alert_id && <button className="ghost small" onClick={() => onNavigate("alerts")}>Open alerts to acknowledge</button>}
    </>
  );
}
