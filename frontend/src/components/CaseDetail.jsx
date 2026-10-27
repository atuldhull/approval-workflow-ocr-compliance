import { Fragment, useEffect, useRef, useState } from "react";
import { DeadlineTimeline } from "../operations/World.jsx";
import { api, newIdempotencyKey } from "../api.js";
import { sentence } from "../nav.js";
import { Badge, Loading, dateIST, useSingleFlight, when } from "./ui.jsx";
import RouteJourney, { stageLabel } from "./RouteJourney.jsx";
import { CALENDAR_NOTE, INTERNAL_REF_TITLE, OFFICIAL_REFERENCES, STATUS_NOTE, deadlineSource, internalRef } from "../provenance.js";

const STATUS_TONE = { DRAFT: "draft", IN_PROCESS: "info", APPROVED: "ok", REJECTED: "bad", WITHDRAWN: "neutral" };

// The case inspector: identity and status first, then the prescribed route, then the dated obligations on the
// case (deadlines) beside its recorded history (audit timeline).
export default function CaseDetail({ who, me, id, onChanged, onLoaded }) {
  const [app, setApp] = useState(null);
  const [deadlines, setDeadlines] = useState([]);
  const [timeline, setTimeline] = useState([]);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const submitKey = useRef(null);
  const once = useSingleFlight();

  useEffect(() => {
    Promise.all([
      api(who, `/applications/${id}`),
      api(who, `/deadlines?subject_id=${id}`),
      api(who, `/cases/${id}/timeline`),
    ])
      .then(([a, d, t]) => {
        setApp(a);
        setDeadlines(d);
        setTimeline(t);
        onLoaded?.();
      })
      .catch((e) => setError(e.message));
  }, [who, id]); // eslint-disable-line react-hooks/exhaustive-deps

  const submit = () => once(send);

  async function send() {
    setBusy(true);
    submitKey.current ??= newIdempotencyKey();
    try {
      await api(who, `/applications/${id}/submit`, { method: "POST", headers: { "Idempotency-Key": submitKey.current } });
      onChanged(id);
    } catch (e) {
      if (e.status && e.status < 500) submitKey.current = null;
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  if (error) return <div className="alert error" role="alert">{error}</div>;
  if (!app) return <div className="card case case-loading"><Loading what="Opening the case" rows={5} /></div>;

  const stage = app.current_stage ? stageLabel(app.current_stage) : "Not submitted";
  const sorted = [...deadlines].sort((a, b) => String(a.due_date).localeCompare(String(b.due_date)));
  return (
    <article className="card case" aria-labelledby={`case-${app.id}`}>
      <header className="case-head">
        <div className="case-title">
          <p className="case-ref">Internal ref <code title={INTERNAL_REF_TITLE}>{internalRef(app.id)}</code> · {app.academic_year}</p>
          <h2 id={`case-${app.id}`}>{sentence(app.category)}</h2>
          <p className="case-status">
            <Badge tone={STATUS_TONE[app.status] ?? "neutral"}>{STATUS_TEXT[app.status] ?? app.status}</Badge>
            <span>{stage}</span>
            {app.ruleset_rev && <span className="muted small">rules <code>{app.ruleset_rev}</code></span>}
          </p>
        </div>
        {app.status === "DRAFT" && me.role === "INSTITUTION" && (
          <button onClick={submit} disabled={busy}>
            {busy ? "Submitting…" : "Submit application"}
          </button>
        )}
      </header>
      <div className="case-provenance">
        <p className="muted small status-note">{STATUS_NOTE}</p>
        <dl className="official-refs" aria-label="Official AICTE references">
          {OFFICIAL_REFERENCES.map(([k, v]) => (
            <Fragment key={k}><dt>{k}</dt><dd>{v}</dd></Fragment>
          ))}
        </dl>
      </div>

      <section className="case-zone" aria-labelledby={`route-${app.id}`}>
        <h3 id={`route-${app.id}`}>Approval route</h3>
        {app.route ? (
          <>
            <RouteJourney route={app.route} current={app.current_stage} status={app.status} />
            <p className="source">Steps are the stages prescribed for this case. Completion of an earlier stage is not reported, so it is not shown as done.</p>
          </>
        ) : (
          <p className="muted">The route is fixed when the application is submitted.</p>
        )}
      </section>

      <div className="case-grid">
        <section className="case-zone" aria-labelledby={`dl-${app.id}`}>
          <h3 id={`dl-${app.id}`}>Deadlines</h3>
          <DeadlineTimeline deadlines={sorted} submittedAt={app.submitted_at} />
          {deadlines.length === 0 && <p className="muted small">No deadlines running.</p>}
          {sorted.map((d) => {
            const src = deadlineSource(d);
            return (
              <div key={d.id} className="clock">
                <div className="clock-head">
                  <strong>{sentence(d.rule_id)}</strong>
                  <span className="clock-due">Due <strong className="num">{dateIST(d.due_date)}</strong></span>
                </div>
                <div className="clock-tags">
                  <span className={`badge ${d.status === "BREACHED" ? "bad" : d.status === "RUNNING" ? "ok" : "neutral"}`}>{sentence(d.status)}</span>
                  <span className="badge neutral">{d.clock_kind === "LEGAL" ? "Legal clock" : "Internal clock"}</span>
                  <span className={`badge ${src.tone}`}>{src.label}</span>
                </div>
                <p className="muted small clock-source">{src.detail}</p>
                <details>
                  <summary>Why is this due then?</summary>
                  <p className="why">{d.explanation}</p>
                </details>
              </div>
            );
          })}
          {deadlines.length > 0 && <p className="muted small calendar-note">{CALENDAR_NOTE}</p>}
        </section>

        <section className="case-zone" aria-labelledby={`tl-${app.id}`}>
          <h3 id={`tl-${app.id}`}>Audit timeline</h3>
          {timeline.length === 0 && <p className="muted small">No recorded events for this case yet.</p>}
          <ol className="timeline">
            {timeline.map((e) => (
              <li key={e.seq}>
                <span className="tl-dot" aria-hidden="true" />
                <span className="tl-what">{EVENT_TEXT[e.event_type] ?? e.event_type}</span>
                <span className="tl-meta">
                  <code>#{e.seq}</code> · {sentence(e.role)} · {when(e.at)}
                </span>
              </li>
            ))}
          </ol>
        </section>
      </div>
    </article>
  );
}

const STATUS_TEXT = { DRAFT: "Draft", IN_PROCESS: "In process", APPROVED: "Approved", REJECTED: "Rejected", WITHDRAWN: "Withdrawn" };
const EVENT_TEXT = {
  "wf.application_created": "Draft created",
  "wf.application_submitted": "Submitted; route fixed",
  "dl.deadline_opened": "Deadline started",
};
