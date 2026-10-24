import { useEffect, useState } from "react";
import { api } from "../api.js";

export default function CaseDetail({ who, id, onChanged }) {
  const [app, setApp] = useState(null);
  const [deadlines, setDeadlines] = useState([]);
  const [timeline, setTimeline] = useState([]);
  const [verify, setVerify] = useState(null);
  const [error, setError] = useState(null);

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

  async function submit() {
    try {
      await api(who, `/applications/${id}/submit`, { method: "POST" });
      onChanged(id);
    } catch (e) {
      setError(e.message);
    }
  }

  async function checkLedger() {
    try {
      setVerify(await api(who, "/ledger/verify"));
    } catch (e) {
      setVerify({ ok: false, detail: e.message });
    }
  }

  if (error) return <p className="error">{error}</p>;
  if (!app) return <p className="muted">Loading…</p>;

  return (
    <div className="card">
      <h2>{app.category.replaceAll("_", " ").toLowerCase()}</h2>
      <p className="muted">
        {app.academic_year} · {app.status} {app.ruleset_rev && `· ruleset ${app.ruleset_rev}`}
      </p>

      {app.status === "DRAFT" && who.role === "INSTITUTION" && <button onClick={submit}>Submit application</button>}

      {app.route && (
        <>
          <h3>Route</h3>
          <ol className="route">
            {app.route.map((s) => (
              <li key={s.stage} className={s.stage === app.current_stage ? "current" : ""}>
                {s.stage}
                {s.when === "as_applicable" && <small> as applicable</small>}
              </li>
            ))}
          </ol>
        </>
      )}

      <h3>Clocks</h3>
      {deadlines.length === 0 && <p className="muted">No clocks running.</p>}
      {deadlines.map((d) => (
        <div key={d.id} className="clock">
          <strong>{d.rule_id}</strong> <span className="badge">{d.clock_kind}</span>{" "}
          <span className="badge">{d.status}</span> due <strong>{d.due_date}</strong>
          <p className="why">Why: {d.explanation}</p>
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

      <button className="secondary" onClick={checkLedger}>
        Verify ledger
      </button>
      {verify && (
        <p className={verify.ok ? "ok" : "error"}>
          {verify.ok ? `Ledger intact (${verify.checked} entries checked)` : `Not verified: ${verify.detail}`}
          {verify.first_bad_seq && ` at entry #${verify.first_bad_seq}`}
        </p>
      )}
    </div>
  );
}
