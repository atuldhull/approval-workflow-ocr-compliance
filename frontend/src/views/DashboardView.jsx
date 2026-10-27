import World from '../operations/World.jsx';
import { useEffect } from "react";
import { Icon } from "../components/Icons.jsx";
import { Badge, BarList, Card, ErrorBox, Loading, NotAvailable, StatTile, useApi, when } from "../components/ui.jsx";

function Section({ s }) {
  if (s.status === "NOT_AVAILABLE") {
    return (
      <Card title={s.title}>
        <NotAvailable dependsOn={s.depends_on}>No figures are shown until the data exists.</NotAvailable>
      </Card>
    );
  }
  const d = s.data;
  return (
    <Card title={s.title} actions={s.status === "PARTIAL" && <Badge tone="warn">Partial</Badge>}>
      {s.key === "applications" && (
        <>
          <div className="stats">
            <StatTile label="Applications" value={d.total} />
            <StatTile label="In process" value={d.by_status.IN_PROCESS ?? 0} />
            <StatTile label="Drafts" value={d.by_status.DRAFT ?? 0} />
          </div>
          <h3>By current stage</h3>
          <BarList data={d.by_stage} label="Applications by stage" />
          <h3>By regional office</h3>
          <BarList data={d.by_region} label="Applications by region" />
        </>
      )}
      {s.key === "ageing" && <BarList data={d.buckets} label="Time since submission" />}
      {s.key === "deadlines" && (
        <>
          <div className="stats">
            <StatTile label="Deadlines opened" value={d.opened} />
            <StatTile label="Due date passed" value={d.due_date_passed} hint="may include met deadlines" />
          </div>
          <BarList data={d.by_rule} label="Deadlines by rule" />
        </>
      )}
      {s.key === "alerts" && (
        <div className="stats">
          <StatTile label="Delivered" value={d.by_status.DELIVERED} />
          <StatTile label="Waiting" value={d.by_status.PENDING + d.by_status.SENDING} />
          <StatTile label="Dead letters" value={d.by_status.DEAD} />
          <StatTile
            label="First-try success (24 h)"
            value={d.first_try_success_rate_24h == null ? "—" : `${Math.round(d.first_try_success_rate_24h * 100)}%`}
          />
        </div>
      )}
      {s.note && <p className="muted small">{s.note}</p>}
      {s.depends_on && s.status === "PARTIAL" && <p className="muted small">Waiting for: {s.depends_on}</p>}
      <p className="source">Source: {s.source}</p>
    </Card>
  );
}

export default function DashboardView({ who }) {
  const { data, error, loading, reload } = useApi(who, "/analytics/dashboard");
  useEffect(() => {
    window.addEventListener("awoc:clock-changed", reload);
    return () => window.removeEventListener("awoc:clock-changed", reload);
  }, [reload]);

  if (loading && !data) return <Loading what="Building dashboard" rows={6} />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  return (
    <div className="dashboard">
      <div className="freshness">
        <span className="muted">
          {data.scope.region ? `${data.scope.region} region` : "All regions"} · as of {when(data.scope.as_of)} · rebuilt from
          the audit event log
        </span>
        <button className="ghost small" onClick={reload}><Icon name="refresh" /> Refresh</button>
      </div>
      <World kind={data.scope.region ? 'officer' : 'dashboard'} records={Object.entries(data.scope.region ? data.sections.find(s=>s.key==='ageing' && s.status!=='NOT_AVAILABLE')?.data?.buckets || {} : data.sections.find(s=>s.key==='applications' && s.status!=='NOT_AVAILABLE')?.data?.by_region || {}).map(([label,value])=>({id:label,label,value,detail:value+' applications',state:'reported',facts:[['Scope',data.scope.region||'All supplied regions'],['As of',data.scope.as_of],['Measure',data.scope.region?'Age since submission; not priority':'Regional application count'],['Coverage',data.scope.region?'Individual work assignments are not supplied':'Per-region status breakdown is not supplied']]}))} />
      <div className="grid cards">
        {data.sections.map((s) => (
          <Section key={s.key} s={s} />
        ))}
      </div>
    </div>
  );
}
