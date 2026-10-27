import World from "../nebula/World.jsx";
import { useEffect, useRef, useState } from "react";
import { api, newIdempotencyKey } from "../api.js";
import { Icon } from "../components/Icons.jsx";
import { Badge, Card, Empty, ErrorBox, Loading, useApi, useSingleFlight, when } from "../components/ui.jsx";
import { ROLE_LABELS } from "../nav.js";
import { INTERNAL_REF_TITLE, internalRef } from "../provenance.js";
import { ALERT_REASON, alertMeaning, alertStatusOf } from "../recordText.js";
import { TIMERS_RAN } from "../components/TimeTravel.jsx";

// Deadline alerts (backend/app/deadlines). Each level of a deadline's ladder is addressed to one role; only that
// role may acknowledge it, and acknowledging stops further escalation for that due date.

const FILTERS = [["", "All"], ["OPEN", "Open"], ["ESCALATED", "Escalated"], ["ACKNOWLEDGED", "Acknowledged"], ["VACANT", "Vacant"]];
const ACK_ERRORS = { 409: "This alert was never delivered, because nobody held its role, so it cannot be acknowledged." };
const ACKABLE = new Set(["OPEN", "ESCALATED"]);

// policy.py alert.ack: officers and institutions; the deadlines module also requires the addressed role.
const ACK_ROLES = new Set(["INSTITUTION", "SCRUTINY_COMMITTEE", "RO_OFFICER", "BUREAU_OFFICER", "BUREAU_HEAD"]);
export const canAcknowledge = (alert, role) => ACK_ROLES.has(role) && alert.role === role && ACKABLE.has(alert.status);
const levelText = (level) => (level === 0 ? "Level 0 · first notice" : `Level ${level} · escalation`);

export default function AlertsView({ who, me }) {
  const [status, setStatus] = useState("");
  const { data, error, loading, reload } = useApi(who, `/alerts${status ? `?status=${status}` : ""}`);
  const [busy, setBusy] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [done, setDone] = useState(null);
  const keys = useRef({}); // per alert: a retry of the same acknowledgement reuses its key
  const once = useSingleFlight();

  useEffect(() => {
    const again = () => reload();
    window.addEventListener(TIMERS_RAN, again);
    window.addEventListener("awoc:clock-changed", again);
    return () => { window.removeEventListener(TIMERS_RAN, again); window.removeEventListener("awoc:clock-changed", again); };
  }, [reload]);

  const ack = (alert) => once(async () => {
    setBusy(alert.id);
    setActionError(null);
    setDone(null);
    keys.current[alert.id] ??= newIdempotencyKey();
    try {
      await api(who, `/alerts/${alert.id}/ack`, { method: "POST", headers: { "Idempotency-Key": keys.current[alert.id] } });
      delete keys.current[alert.id];
      setDone(alert.id);
      reload();
    } catch (e) {
      if (e.status && e.status < 500) delete keys.current[alert.id];
      setActionError(e.status === 409 ? Object.assign(new Error(ACK_ERRORS[409]), { status: 409 }) : e);
    } finally {
      setBusy(null);
    }
  });

  const records = (data ?? []).map((a) => ({
    id: a.id, label: alertMeaning(a.template), category: levelText(a.level),
    state: a.status === "ACKNOWLEDGED" ? "checked" : a.status === "ESCALATED" ? "broken" : a.status === "OPEN" ? "unread" : "unknown",
    detail: `${alertStatusOf(a.status).label} · to ${ROLE_LABELS[a.role] ?? a.role}`,
    facts: [["Raised", when(a.raised_at)], ["Addressed to", ROLE_LABELS[a.role] ?? a.role], ["Case", internalRef(a.subject_id)],
      ["Region", a.region ?? "Not supplied"]],
  }));

  return (
    <div>
      <World kind="alerts" records={records} />
      <Card title="Deadline alerts" actions={<button className="secondary small" onClick={reload}><Icon name="refresh" /> Refresh</button>}>
        <div className="chips" role="group" aria-label="Show alerts">
          {FILTERS.map(([key, label]) => (
            <button key={key || "all"} className={`chip${status === key ? " on" : ""}`} aria-pressed={status === key} onClick={() => setStatus(key)}>
              {label}
            </button>
          ))}
        </div>
        {loading && !data && <Loading what="Loading alerts" />}
        <ErrorBox error={error} onRetry={reload} />
        <ErrorBox error={actionError} />
        {done && <p className="ok" role="status">Acknowledged. No further escalation will be raised for that due date.</p>}
        {data && data.length === 0 && <Empty>{status ? "No alerts with this status." : "No deadline alerts in your scope."}</Empty>}
        {data && data.length > 0 && (
          <ul className="alert-list">
            {data.map((a) => {
              const s = alertStatusOf(a.status);
              return (
                <li key={a.id} className={`alert-row status-${a.status.toLowerCase()}`}>
                  <div className="alert-main">
                    <p className="alert-title">
                      <strong>{alertMeaning(a.template)}</strong> <Badge tone={s.tone}>{s.label}</Badge>
                    </p>
                    <p className="muted small">
                      {levelText(a.level)} · to {ROLE_LABELS[a.role] ?? a.role}
                      {a.region && <> · {a.region} region</>} · case <code title={INTERNAL_REF_TITLE}>{internalRef(a.subject_id)}</code>
                    </p>
                    <p className="muted small">
                      Raised {when(a.raised_at)}
                      {a.escalated_at && <> · escalated {when(a.escalated_at)}</>}
                      {a.acknowledged_at && <> · acknowledged {when(a.acknowledged_at)}</>}
                    </p>
                    {a.reason && <p className="small">{ALERT_REASON[a.reason] ?? "Raised after the previous level."}</p>}
                  </div>
                  <div className="actions">
                    {canAcknowledge(a, me.role) ? (
                      <button className="small" disabled={busy !== null} onClick={() => ack(a)}
                        aria-label={`Acknowledge: ${alertMeaning(a.template)} raised ${when(a.raised_at)}`}>
                        {busy === a.id ? "Acknowledging…" : "Acknowledge"}
                      </button>
                    ) : a.status !== "ACKNOWLEDGED" && a.role !== me.role && me.role !== "AUDITOR" ? (
                      <span className="muted small">Only the {(ROLE_LABELS[a.role] ?? a.role).toLowerCase()} can acknowledge this</span>
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
        {me.role === "AUDITOR" && <p className="muted small" role="note">Read-only: auditors see alerts but do not acknowledge them.</p>}
      </Card>
    </div>
  );
}
