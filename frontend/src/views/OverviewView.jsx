import { useEffect, useMemo, useState } from "react";
import { INTERNAL_REF_TITLE, internalRef } from "../provenance.js";
import { api } from "../api.js";
import { Icon } from "../components/Icons.jsx";
import { STAGE_LABEL, RouteTrack, stageLabel } from "../components/RouteJourney.jsx";
import { Badge, Empty, ErrorBox, Kpis, Loading, dateIST, useApi } from "../components/ui.jsx";
import { sentence } from "../nav.js";
import { obligationStatusOf } from "../recordText.js";

const ORDER = Object.keys(STAGE_LABEL);
const MAX_DEADLINE_LOOKUPS = 12;
const STATUS_TONE = { DRAFT: "draft", IN_PROCESS: "info", APPROVED: "ok", REJECTED: "bad", WITHDRAWN: "neutral" };

// Institution overview, built only from what an institution may already read: its own applications (filtered by
// the server), each case's running deadlines, and its open compliance obligations. Every count is computed from
// those rows; nothing is estimated.
export default function OverviewView({ who, onNavigate }) {
  const { data: apps, error, loading, reload } = useApi(who, "/applications");
  const obligations = useApi(who, "/compliance/obligations?status=OPEN");
  const [deadlines, setDeadlines] = useState(null);
  const [deadlineError, setDeadlineError] = useState(null);

  const inProcess = useMemo(() => (apps ?? []).filter((a) => a.status === "IN_PROCESS"), [apps]);

  useEffect(() => {
    if (!apps) return undefined;
    let alive = true;
    const ids = inProcess.slice(0, MAX_DEADLINE_LOOKUPS).map((a) => a.id);
    Promise.all(ids.map((id) => api(who, `/deadlines?subject_id=${id}`).then((ds) => ds.map((d) => ({ ...d, app: id })))))
      .then((lists) => alive && setDeadlines(lists.flat().filter((d) => ["RUNNING", "PAUSED", "BREACHED"].includes(d.status))))
      .catch((e) => alive && setDeadlineError(e));
    return () => { alive = false; };
  }, [apps, inProcess, who]);

  if (loading && !apps) return <Loading what="Gathering your applications" rows={4} />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;

  const drafts = apps.filter((a) => a.status === "DRAFT").length;
  const byStage = inProcess.reduce((m, a) => ({ ...m, [a.current_stage]: (m[a.current_stage] ?? 0) + 1 }), {});
  const stages = ORDER.filter((s) => apps.some((a) => a.route?.some((r) => r.stage === s)));
  const upcoming = [...(deadlines ?? [])].sort((a, b) => a.due_date.localeCompare(b.due_date));
  const next = upcoming[0];
  const appById = Object.fromEntries(apps.map((a) => [a.id, a]));
  const openObligations = obligations.data ?? [];
  const evidenceNeeded = openObligations.reduce((m, o) => ({ ...m, [o.application_id]: (m[o.application_id] ?? 0) + 1 }), {});
  const openCase = (id) => onNavigate?.("applications", { caseId: id });

  if (apps.length === 0) {
    return (
      <section className="card overview-empty" aria-label="No applications yet">
        <h2>No applications yet</h2>
        <p className="muted">
          Your applications, their approval route and what falls due next will appear here. Start by creating a draft;
          its route is fixed when you submit it.
        </p>
        {onNavigate && <button onClick={() => onNavigate("applications")}>Start an application <Icon name="arrow" /></button>}
      </section>
    );
  }

  return (
    <div className="overview">
      <Kpis label="Your applications in figures" items={[
        { label: "Applications", value: apps.length },
        { label: "In process", value: inProcess.length },
        { label: "Drafts not yet submitted", value: drafts, tone: drafts ? "attention" : undefined },
        { label: "Next deadline", value: next ? dateIST(next.due_date) : deadlines ? "None running" : "…",
          hint: next ? `${sentence(next.rule_id)} · ${internalRef(next.app)}` : undefined, tone: next ? "attention" : undefined },
        { label: "Obligations needing evidence", value: obligations.data ? openObligations.length : obligations.error ? "—" : "…" },
      ]} />

      <div className="overview-grid">
        <section className="card app-board" aria-labelledby="board-title">
          <header className="card-head">
            <h2 id="board-title">Applications <span className="count num">{apps.length}</span></h2>
            {onNavigate && <button className="ghost small" onClick={() => onNavigate("applications")}>All cases <Icon name="arrow" /></button>}
          </header>
          <ul className="app-rows">
            {apps.map((a) => (
              <li key={a.id} className="app-row">
                <div className="app-row-head">
                  <span className="app-row-title">{sentence(a.category)}</span>
                  <Badge tone={STATUS_TONE[a.status] ?? "neutral"}>{a.current_stage ? stageLabel(a.current_stage) : sentence(a.status)}</Badge>
                </div>
                <p className="app-row-meta">
                  <code title={INTERNAL_REF_TITLE}>{internalRef(a.id)}</code> · {a.academic_year}
                  {a.submitted_at ? <> · submitted {dateIST(a.submitted_at)}</> : a.created_at ? <> · created {dateIST(a.created_at)}</> : null}
                </p>
                {a.route?.length ? <RouteTrack route={a.route} current={a.current_stage} status={a.status} />
                  : <p className="app-row-route muted small">The route is fixed when the application is submitted.</p>}
                <div className="app-row-foot">
                  <span className={`next-step${a.status === "DRAFT" || evidenceNeeded[a.id] ? " needs-you" : ""}`}>
                    {nextStep(a, evidenceNeeded[a.id])}
                  </span>
                  <button className="secondary small" onClick={() => openCase(a.id)} aria-label={`Open case ${internalRef(a.id)}`}>Open</button>
                </div>
              </li>
            ))}
          </ul>
        </section>

        <div className="overview-side">
          <section className="card" aria-labelledby="due-title">
            <header className="card-head"><h2 id="due-title">Due next</h2></header>
            {deadlineError && <ErrorBox error={deadlineError} />}
            {!deadlines && !deadlineError && <Loading what="Reading deadlines" rows={2} />}
            {deadlines && upcoming.length === 0 && <Empty>No deadlines are running on your applications.</Empty>}
            {upcoming.length > 0 && (
              <ul className="due-list">
                {upcoming.slice(0, 5).map((d, i) => (
                  <li key={`${d.app}-${d.id}`} className={i === 0 ? "is-next" : undefined}>
                    <span className="due-date num">{dateIST(d.due_date)}</span>
                    <span className="due-what">
                      {sentence(d.rule_id)}
                      <span className="muted small"> · {sentence(appById[d.app]?.category)} <code title={INTERNAL_REF_TITLE}>{internalRef(d.app)}</code></span>
                    </span>
                    <button className="ghost small" onClick={() => openCase(d.app)}>Open case</button>
                  </li>
                ))}
              </ul>
            )}
            {inProcess.length > MAX_DEADLINE_LOOKUPS && (
              <p className="source">Showing deadlines for your {MAX_DEADLINE_LOOKUPS} most recent cases in process.</p>
            )}
            <p className="source">Indian Standard Time calendar dates, as computed by the deadline service.</p>
          </section>

          <section className="card" aria-labelledby="stage-title">
            <header className="card-head"><h2 id="stage-title">Where your applications are</h2></header>
            {stages.length === 0 ? (
              <Empty>Nothing submitted yet. A route appears here when you submit your first application.</Empty>
            ) : (
              <WorkflowPath stages={stages} counts={byStage} />
            )}
            <p className="source">Each stage counts your applications currently at it. Drafts have no route until submitted.</p>
          </section>

          <section className="card" aria-labelledby="ob-title">
            <header className="card-head">
              <h2 id="ob-title">Compliance evidence needed</h2>
              {onNavigate && <button className="ghost small" onClick={() => onNavigate("compliance")}>Compliance <Icon name="arrow" /></button>}
            </header>
            {obligations.loading && !obligations.data && <Loading rows={2} />}
            <ErrorBox error={obligations.error} />
            {obligations.data?.length === 0 && <Empty>No open obligations. Nothing is waiting for your evidence.</Empty>}
            {openObligations.length > 0 && (
              <ul className="due-list">
                {[...openObligations].sort((a, b) => String(a.due_date).localeCompare(String(b.due_date))).slice(0, 4).map((o) => (
                  <li key={o.id}>
                    <span className="due-date num">{o.due_date ? dateIST(o.due_date) : "No date"}</span>
                    <span className="due-what">{sentence(o.kind)}<span className="muted small"> · {obligationStatusOf(o.status).label}</span></span>
                    <button className="ghost small" onClick={() => onNavigate?.("compliance", { obligationId: o.id })}
                      aria-label={`Open ${sentence(o.kind).toLowerCase()} obligation`}>Open</button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

// What the institution can do next, from recorded facts only. An in-process case asks nothing of the institution
// unless an obligation is open; this screen does not guess at officer work it cannot see.
function nextStep(app, openObligations) {
  if (app.status === "DRAFT") return "Next: open the draft and submit it to fix the route";
  if (openObligations) return `Next: submit evidence for ${openObligations} open obligation${openObligations === 1 ? "" : "s"}`;
  if (app.status === "IN_PROCESS") return `With ${stageLabel(app.current_stage).toLowerCase()}; nothing is recorded as awaiting you`;
  return sentence(app.status);
}

// The stages your cases travel, with the count currently at each. A node's size and label carry its count.
function WorkflowPath({ stages, counts }) {
  const w = 1000;
  const step = w / stages.length;
  const x = (i) => step * i + step / 2;
  const max = Math.max(1, ...Object.values(counts));
  return (
    <div className="workflow-path">
      <svg viewBox={`0 0 ${w} 64`} role="img" aria-label={stages.map((s) => `${stageLabel(s)}: ${counts[s] ?? 0}`).join(", ")}>
        <path className="wp-track" d={`M ${x(0)} 32 L ${x(stages.length - 1)} 32`} />
        {stages.map((s, i) => {
          const n = counts[s] ?? 0;
          return (
            <g key={s} className={n ? "wp-node live" : "wp-node"} transform={`translate(${x(i)} 32)`}>
              <circle className="wp-dot" r={n ? 7 + 9 * (n / max) : 5} />
            </g>
          );
        })}
      </svg>
      <ol className="wp-labels" style={{ gridTemplateColumns: `repeat(${stages.length}, minmax(0, 1fr))` }}>
        {stages.map((s) => (
          <li key={s}>
            <span className="num wp-count">{counts[s] ?? 0}</span>
            <span className="wp-name">{stageLabel(s)}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}
