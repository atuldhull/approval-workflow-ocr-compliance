import World, { DeadlineTimeline } from '../operations/World.jsx';
import { applicationRecords } from '../operations/semanticData.js';
import { INTERNAL_REF_TITLE, internalRef } from "../provenance.js";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api.js";
import { STAGE_LABEL, stageLabel } from "../components/RouteJourney.jsx";
import { Card, Empty, ErrorBox, Loading, dateIST, useApi } from "../components/ui.jsx";
import { sentence } from "../nav.js";

const ORDER = Object.keys(STAGE_LABEL);
const MAX_DEADLINE_LOOKUPS = 12;

// Institution overview, built only from what an institution may already read: its own applications
// (filtered by the server) and each case's deadlines. The workflow path is 2D (SVG).
export default function OverviewView({ who, onNavigate }) {
  const { data: apps, error, loading, reload } = useApi(who, "/applications");
  const [deadlines, setDeadlines] = useState(null);
  const [deadlineError, setDeadlineError] = useState(null);

  const inProcess = useMemo(() => (apps ?? []).filter((a) => a.status === "IN_PROCESS"), [apps]);

  useEffect(() => {
    if (!apps) return;
    let alive = true;
    const ids = inProcess.slice(0, MAX_DEADLINE_LOOKUPS).map((a) => a.id);
    Promise.all(ids.map((id) => api(who, `/deadlines?subject_id=${id}`).then((ds) => ds.map((d) => ({ ...d, app: id })))))
      .then((lists) => alive && setDeadlines(lists.flat().filter((d) => d.status === "RUNNING" || d.status === "PAUSED")))
      .catch((e) => alive && setDeadlineError(e));
    return () => {
      alive = false;
    };
  }, [apps, inProcess, who]);

  if (loading && !apps) return <Loading what="Gathering your applications" rows={4} />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;

  const drafts = apps.filter((a) => a.status === "DRAFT").length;
  const byStage = inProcess.reduce((m, a) => ({ ...m, [a.current_stage]: (m[a.current_stage] ?? 0) + 1 }), {});
  const stages = ORDER.filter((s) => apps.some((a) => a.route?.some((r) => r.stage === s)));
  const upcoming = [...(deadlines ?? [])].sort((a, b) => a.due_date.localeCompare(b.due_date));
  const next = upcoming[0];
  const appById = Object.fromEntries(apps.map((a) => [a.id, a]));

  return (
    <div className="overview">
      <section className="figure-strip" data-reveal aria-label="Your applications in figures">
        <div><span className="stat-label">Applications</span><span className="stat-value num">{apps.length}</span></div>
        <div><span className="stat-label">In process</span><span className="stat-value num">{inProcess.length}</span></div>
        <div><span className="stat-label">Drafts not yet submitted</span><span className="stat-value num">{drafts}</span></div>
        <div>
          <span className="stat-label">Next deadline</span>
          <span className="stat-value num">{next ? next.due_date : "—"}</span>
          {next && <span className="stat-hint">{sentence(next.rule_id)}</span>}
        </div>
      </section>
      <World kind="overview" records={applicationRecords(apps)} onSelect={id=>onNavigate?.("applications",{caseId:id})} />

      <Card title="Where your applications are">
        {stages.length === 0 ? (
          <Empty>Nothing submitted yet. A route appears here when you submit your first application.</Empty>
        ) : (
          <WorkflowPath stages={stages} counts={byStage} />
        )}
        <p className="source">Each node counts your applications currently at that stage. Drafts have no route until submitted.</p>
      </Card>

      <Card title="Due next">
        <DeadlineTimeline deadlines={upcoming} />
        {deadlineError && <ErrorBox error={deadlineError} />}
        {!deadlines && !deadlineError && <Loading what="Reading deadlines" rows={2} />}
        {deadlines && upcoming.length === 0 && <Empty>No deadlines are running on your applications.</Empty>}
        {upcoming.length > 0 && (
          <ul className="due-list">
            {upcoming.slice(0, 5).map((d) => (
              <li key={`${d.app}-${d.id}`}>
                <span className="due-date num">{d.due_date}</span>
                <span className="due-what">
                  {sentence(d.rule_id)}
                  <span className="muted small"> · {sentence(appById[d.app]?.category)} <code title={INTERNAL_REF_TITLE}>{internalRef(d.app)}</code></span>
                </span>
                <button className="ghost small" onClick={() => onNavigate?.("applications", { caseId: d.app })}>Open case</button>
              </li>
            ))}
          </ul>
        )}
        {inProcess.length > MAX_DEADLINE_LOOKUPS && (
          <p className="source">Showing deadlines for your {MAX_DEADLINE_LOOKUPS} most recent cases in process.</p>
        )}
        <p className="source">Dates are Indian Standard Time calendar dates. Last checked {dateIST(new Date().toISOString())}.</p>
      </Card>
    </div>
  );
}

// 2D: the stages your cases travel, as a luminous path. A node's size and label carry its count.
function WorkflowPath({ stages, counts }) {
  const w = 1000;
  const step = w / stages.length;
  const x = (i) => step * i + step / 2;
  const total = Object.values(counts).reduce((a, b) => a + b, 0) || 1;
  return (
    <div className="workflow-path">
      <svg viewBox={`0 0 ${w} 120`} role="img"
        aria-label={stages.map((s) => `${stageLabel(s)}: ${counts[s] ?? 0}`).join(", ")}>
        <path className="wp-track" d={`M ${x(0)} 60 L ${x(stages.length - 1)} 60`} />
        <path className="wp-flow" d={`M ${x(0)} 60 L ${x(stages.length - 1)} 60`} />
        {stages.map((s, i) => {
          const n = counts[s] ?? 0;
          return (
            <g key={s} className={n ? "wp-node live" : "wp-node"} transform={`translate(${x(i)} 60)`}>
              {n > 0 && <circle className="wp-halo" r={14 + 18 * (n / total)} />}
              <circle className="wp-dot" r={n ? 9 : 6} />
            </g>
          );
        })}
      </svg>
      <ol className="wp-labels" style={{ gridTemplateColumns: `repeat(${stages.length}, 1fr)` }}>
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
