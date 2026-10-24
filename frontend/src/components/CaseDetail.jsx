import { useEffect, useRef, useState } from "react";
import { api, newIdempotencyKey } from "../api.js";
import { humanise } from "../nav.js";
import { useSingleFlight } from "./ui.jsx";

export default function CaseDetail({ who, me, id, onChanged }) {
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

  if (error) return <p className="error" role="alert">{error}</p>;
  if (!app) return <p className="muted" role="status">Loading…</p>;

  return (
    <div className="card">
      <h2>{humanise(app.category)}</h2>
      <p className="muted">
        {app.academic_year} · {app.status} {app.ruleset_rev && `· ruleset ${app.ruleset_rev}`}
      </p>

      {app.status === "DRAFT" && me.role === "INSTITUTION" && (
        <button onClick={submit} disabled={busy}>
          {busy ? "Submitting…" : "Submit application"}
        </button>
      )}

      {app.route && (
        <>
          <h3>Route</h3>
          <ol className="route">
            {app.route.map((s) => (
              <li
                key={s.stage}
                className={s.stage === app.current_stage ? "current" : ""}
                aria-current={s.stage === app.current_stage ? "step" : undefined}
              >
                {s.stage}
                {s.when === "as_applicable" && <small> as applicable</small>}
              </li>
            ))}
          </ol>
        </>
      )}

      <h3>Deadlines</h3>
      {deadlines.length === 0 && <p className="muted">No deadlines running.</p>}
      {deadlines.map((d) => (
        <div key={d.id} className="clock">
          <strong>{d.rule_id}</strong> <span className="badge neutral">{d.clock_kind}</span>{" "}
          <span className="badge neutral">{d.status}</span> due <strong>{d.due_date}</strong>
          <details>
            <summary>Why is this due then?</summary>
            <p className="why">{d.explanation}</p>
          </details>
        </div>
      ))}

      <h3>Audit timeline</h3>
      <ol className="timeline">
        {timeline.map((e) => (
          <li key={e.seq}>
            <code>#{e.seq}</code> {e.event_type} <span className="muted">by {e.role}</span>{" "}
            <span className="muted">{new Date(e.at).toLocaleString()}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}
