import { useEffect, useRef, useState } from "react";
import { api, newIdempotencyKey } from "../api.js";
import { Icon } from "../components/Icons.jsx";
import { Badge, Card, Empty, ErrorBox, Kpis, Loading, Toast, dateIST, useApi, useSingleFlight, when } from "../components/ui.jsx";
import Lifecycle from "../components/Lifecycle.jsx";
import { ROLE_LABELS, sentence } from "../nav.js";
import { INTERNAL_REF_TITLE, internalRef } from "../provenance.js";
import { ALERT_REASON, alertMeaning, alertStatusOf, ruleLabel } from "../recordText.js";
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

export default function AlertsView({ who, me, onNavigate }) {
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


  return (
    <div>
      <Lifecycle here={["alerts", "ack"]} />
      {data && !status && (
        <Kpis label="Alerts in your scope" items={[
          { label: "Open", value: data.filter((a) => a.status === "OPEN").length, tone: data.some((a) => a.status === "OPEN") ? "attention" : undefined },
          { label: "Escalated", value: data.filter((a) => a.status === "ESCALATED").length, tone: data.some((a) => a.status === "ESCALATED") ? "bad" : undefined },
          { label: "Acknowledged", value: data.filter((a) => a.status === "ACKNOWLEDGED").length },
          { label: "Vacant (nobody held the role)", value: data.filter((a) => a.status === "VACANT").length },
          { label: "Awaiting your role", value: data.filter((a) => canAcknowledge(a, me.role)).length, tone: data.some((a) => canAcknowledge(a, me.role)) ? "attention" : undefined },
        ]} />
      )}
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
        {done && <Toast>Acknowledged. No further escalation will be raised for that due date.</Toast>}
        {data && data.length === 0 && <Empty>{status ? "No alerts with this status." : "No deadline alerts in your scope."}</Empty>}
        {data && data.length > 0 && (
          <ul className="alert-list">
            {data.map((a) => {
              const s = alertStatusOf(a.status);
              return (
                <li key={a.id} className={`alert-row status-${a.status.toLowerCase()}`}>
                  <Ladder level={a.level} status={a.status} />
                  <div className="alert-main">
                    <p className="alert-title">
                      <strong>{alertMeaning(a.template)}</strong> <Badge tone={s.tone}>{s.label}</Badge>
                    </p>
                    <p className="small alert-rule">
                      {ruleLabel(a.rule_id)}
                      {a.due_date && <> · due <strong>{dateIST(a.due_date)}</strong></>}
                      {a.deadline_status && <span className="muted"> · deadline {sentence(a.deadline_status).toLowerCase()}</span>}
                    </p>
                    <p className="muted small">
                      {levelText(a.level)} · to {ROLE_LABELS[a.role] ?? a.role}
                      {a.region && <> · {a.region} region</>}
                      {a.application_id && <> · case <code title={INTERNAL_REF_TITLE}>{internalRef(a.application_id)}</code></>}
                    </p>
                    <p className="muted small">
                      Raised {when(a.raised_at)}
                      {a.escalated_at && <> · escalated {when(a.escalated_at)}</>}
                      {a.acknowledged_at && <> · acknowledged {when(a.acknowledged_at)}</>}
                    </p>
                    {a.reason && <p className="small">{ALERT_REASON[a.reason] ?? "Raised after the previous level."}</p>}
                  </div>
                  <div className="actions">
                    {onNavigate && a.application_id && (
                      <button className="ghost small" onClick={() => onNavigate("applications", { caseId: a.application_id })}
                        aria-label={`Open case ${internalRef(a.application_id)}`}>
                        Open case
                      </button>
                    )}
                    {onNavigate && a.subject_type === "obligation" && (
                      <button className="ghost small" onClick={() => onNavigate("compliance", { obligationId: a.subject_id })}>
                        Open obligation
                      </button>
                    )}
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

// The escalation ladder for one alert: one rung per level up to this one. The last rung is this alert.
function Ladder({ level, status }) {
  return (
    <span className={"ladder status-" + status.toLowerCase()} aria-hidden="true">
      {Array.from({ length: level + 1 }, (_, i) => <i key={i} className={i === level ? "this" : undefined} />)}
    </span>
  );
}
