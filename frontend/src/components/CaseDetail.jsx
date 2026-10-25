import World, { DeadlineTimeline } from '../nebula/World.jsx';
import { routeRecords } from '../nebula/semanticData.js';
import { Fragment, useEffect, useRef, useState } from "react";
import { api, newIdempotencyKey } from "../api.js";
import { humanise, sentence } from "../nav.js";
import { Loading, useSingleFlight, when } from "./ui.jsx";
import RouteJourney, { stageLabel } from "./RouteJourney.jsx";
import { CALENDAR_NOTE, INTERNAL_REF_TITLE, OFFICIAL_REFERENCES, STATUS_NOTE, deadlineSource, internalRef } from "../provenance.js";

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
  }, [who, id]);

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
  if (!app) return <Loading what="Opening the case" rows={5} />;

  const stage = app.current_stage ? stageLabel(app.current_stage) : "Not submitted";
  return (
    <article className="card case" aria-labelledby={`case-${app.id}`}>
      <header className="case-head">
        <div>
          <p className="case-ref">Internal ref <code title={INTERNAL_REF_TITLE}>{internalRef(app.id)}</code> · {app.academic_year}</p>
          <h2 id={`case-${app.id}`}>{sentence(app.category)}</h2>
          <p className="muted">
            {STATUS_TEXT[app.status] ?? app.status} · {stage}
            {app.ruleset_rev && <> · rules <code>{app.ruleset_rev}</code></>}
          </p>
          <p className="muted small status-note">{STATUS_NOTE}</p>
          <dl className="facts official-refs" aria-label="Official AICTE references">
            {OFFICIAL_REFERENCES.map(([k, v]) => (
              <Fragment key={k}><dt>{k}</dt><dd>{v}</dd></Fragment>
            ))}
          </dl>
        </div>
        {app.status === "DRAFT" && me.role === "INSTITUTION" && (
          <button onClick={submit} disabled={busy}>
            {busy ? "Submitting…" : "Submit application"}
          </button>
        )}
      </header>

      {app.route ? (
        <section className="case-zone">
          <World compact kind="route" records={routeRecords(app)} />
          <h3>Approval route</h3>
          <RouteJourney route={app.route} current={app.current_stage} status={app.status} />
        </section>
      ) : (
        <p className="muted">The route is fixed when the application is submitted.</p>
      )}

      <div className="case-grid">
        <section className="case-zone">
          <h3>Deadlines</h3>
          <DeadlineTimeline deadlines={deadlines} submittedAt={app.submitted_at} />
          {deadlines.length === 0 && <p className="muted">No deadlines running.</p>}
          {deadlines.map((d) => {
            const src = deadlineSource(d);
            return (
            <div key={d.id} className="clock">
              <div className="clock-head">
                <strong>{sentence(d.rule_id)}</strong>
                <span className="badge neutral">{d.clock_kind === "LEGAL" ? "Legal clock" : "Internal clock"}</span>
                <span className={`badge ${d.status === "BREACHED" ? "bad" : d.status === "RUNNING" ? "ok" : "neutral"}`}>{sentence(d.status)}</span>
                <span className={`badge ${src.tone}`}>{src.label}</span>
              </div>
              <p className="clock-due">Due <strong className="num">{d.due_date}</strong></p>
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

        <section className="case-zone">
          <h3>Audit timeline</h3>
          <ol className="timeline">
            {timeline.map((e) => (
              <li key={e.seq}>
                <span className="tl-dot" aria-hidden="true" />
                <span className="tl-what">{EVENT_TEXT[e.event_type] ?? e.event_type}</span>
                <span className="tl-meta muted">
                  <code>#{e.seq}</code> {e.event_type} · by {sentence(e.role)} · {when(e.at)}
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
