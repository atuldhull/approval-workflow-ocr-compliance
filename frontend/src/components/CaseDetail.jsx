import { Fragment, useEffect, useState } from "react";
import { DeadlineTimeline } from "../operations/World.jsx";
import { api } from "../api.js";
import { sentence } from "../nav.js";
import { EVENT_TEXT, refusalText } from "../workflowText.js";
import CaseActions from "./CaseActions.jsx";
import CaseEvc from "./CaseEvc.jsx";
import Checklist from "./Checklist.jsx";
import CommitteeWorkspace from "./CommitteeWorkspace.jsx";
import Deficiencies from "./Deficiencies.jsx";
import { Badge, Loading, dateIST, when } from "./ui.jsx";
import RouteJourney, { stageLabel } from "./RouteJourney.jsx";
import { CALENDAR_NOTE, INTERNAL_REF_TITLE, OFFICIAL_REFERENCES, STATUS_NOTE, deadlineSource, internalRef } from "../provenance.js";

const STATUS_TONE = { DRAFT: "draft", IN_PROCESS: "info", APPROVED: "ok", REJECTED: "bad", WITHDRAWN: "neutral" };

const settled = (p) => p.then((value) => ({ value }), (error) => ({ error }));
// Auxiliary stages are drawn at the route stage they belong to (routes.yaml auxiliary_stages).
const AUXILIARY = { DEFICIENT: "SCRUTINY", RESCRUTINY: "SCRUTINY" };

// The case inspector: identity and status first, then what the signed-in role can do now (actions, checklist,
// deficiencies, committees, expert visit), then the prescribed route, the dated obligations on the case
// (deadlines) beside its recorded history (audit timeline). The case record (GET /cases/{id}) is the source of
// stage, version and available actions; the application record adds the academic year and filing dates.
export default function CaseDetail({ who, me, id, onChanged, onLoaded, onNavigate }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const demo = who?.mode !== "oidc";

  const load = () => Promise.all([
    api(who, `/cases/${id}`),
    settled(api(who, `/applications/${id}`)),
    settled(api(who, `/deadlines?subject_id=${id}`)),
    settled(api(who, `/cases/${id}/timeline`)),
    settled(api(who, `/cases/${id}/deficiencies`)),
    settled(api(who, `/applications/${id}/documents`)),
    settled(api(who, `/cases/${id}/committees`)),
  ]).then(([caseRec, a, d, t, def, docs, cm]) => {
    const app = a.value ?? {
      id, category: caseRec.route_id, academic_year: null, status: caseRec.status, current_stage: caseRec.stage,
      ruleset_rev: caseRec.ruleset_key, route: caseRec.route, submitted_at: caseRec.stage_history?.[0]?.entered_at ?? null,
    };
    setData({ caseRec, app, deadlines: d.value ?? [], timeline: t.value ?? [], deficiencies: def.value ?? null,
      docs: docs.value ?? null, committees: cm.value ?? null, committeesError: cm.error ?? null });
    onLoaded?.();
  }).catch(setError);

  useEffect(() => { load(); }, [who, id]); // eslint-disable-line react-hooks/exhaustive-deps

  // A change made inside the case reloads it in place (keeping any message on screen) and refreshes the list.
  const changed = () => { load(); onChanged?.(id); };

  if (error) return <div className="alert error" role="alert">{refusalText(error)}</div>;
  if (!data) return <div className="card case case-loading"><Loading what="Opening the case" rows={5} /></div>;

  const { caseRec, app, deadlines, timeline, deficiencies, docs, committees, committeesError } = data;
  const stage = caseRec.stage ? stageLabel(caseRec.stage) : caseRec.status === "DRAFT" ? "Not submitted" : "Route finished";
  const sorted = [...deadlines].sort((a, b) => String(a.due_date).localeCompare(String(b.due_date)));
  return (
    <article className="card case" aria-labelledby={`case-${app.id}`}>
      <header className="case-head">
        <div className="case-title">
          <p className="case-ref">Internal ref <code title={INTERNAL_REF_TITLE}>{internalRef(app.id)}</code>{app.academic_year ? ` · ${app.academic_year}` : ""}</p>
          <h2 id={`case-${app.id}`}>{sentence(app.category)}</h2>
          <p className="case-status">
            <Badge tone={STATUS_TONE[caseRec.status] ?? "neutral"}>{STATUS_TEXT[caseRec.status] ?? caseRec.status}</Badge>
            <span>{stage}</span>
            {caseRec.ruleset_key && <span className="muted small">rules <code>{caseRec.ruleset_key}</code></span>}
            {caseRec.assumption_status && <Badge tone="sample">Demo assumption route</Badge>}
          </p>
        </div>
      </header>

      {caseRec.status === "DRAFT" && me.role === "INSTITUTION" ? (
        <Checklist who={who} me={me} appId={app.id} draft onChanged={changed} onNavigate={onNavigate} />
      ) : (
        <CaseActions who={who} me={me} caseRec={caseRec} application={app} deficiencies={deficiencies} docs={docs}
          committees={committees} onChanged={changed} />
      )}
      <Deficiencies who={who} me={me} caseRec={caseRec} data={deficiencies} docs={docs} onChanged={changed} />
      <CommitteeWorkspace who={who} me={me} caseRec={caseRec} list={committees} listError={committeesError} demo={demo} onChanged={changed} />
      <CaseEvc who={who} caseRec={caseRec} />
      {caseRec.status !== "DRAFT" && <Checklist who={who} me={me} appId={app.id} draft={false} />}
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
        {caseRec.status !== "DRAFT" && caseRec.route?.length ? (
          <>
            <RouteJourney route={caseRec.route} current={AUXILIARY[caseRec.stage] ?? caseRec.stage} status={caseRec.status} />
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
