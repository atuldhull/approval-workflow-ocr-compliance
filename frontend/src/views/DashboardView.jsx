import { useEffect } from "react";
import { Icon } from "../components/Icons.jsx";
import { STAGE_LABEL, stageLabel } from "../components/RouteJourney.jsx";
import { Badge, BarList, Card, ErrorBox, Kpis, Loading, NotAvailable, StatTile, useApi, when } from "../components/ui.jsx";

const STAGE_ORDER = Object.keys(STAGE_LABEL);
const byStageOrder = (data) => Object.fromEntries(Object.entries(data || {})
  .sort(([a], [b]) => (STAGE_ORDER.indexOf(a) + 1 || 99) - (STAGE_ORDER.indexOf(b) + 1 || 99)));
const stageKeys = (data) => Object.fromEntries(Object.entries(data || {}).map(([k, v]) => [STAGE_LABEL[k] ?? k, v]));

function Section({ s }) {
  if (s.status === "NOT_AVAILABLE") {
    return (
      <Card title={s.title} className="dash-section unavailable">
        <NotAvailable dependsOn={s.depends_on}>No figures are shown until the data exists.</NotAvailable>
      </Card>
    );
  }
  const d = s.data;
  return (
    <Card title={s.title} className={`dash-section section-${s.key}`} actions={s.status === "PARTIAL" && <Badge tone="warn">Partial</Badge>}>
      {s.key === "applications" && (
        <>
          <div className="stats">
            <StatTile label="Applications" value={d.total} />
            <StatTile label="In process" value={d.by_status.IN_PROCESS ?? 0} />
            <StatTile label="Drafts" value={d.by_status.DRAFT ?? 0} />
          </div>
          <h3>By current stage</h3>
          <BarList data={stageKeys(byStageOrder(d.by_stage))} label="Applications by stage" />
          <h3>By regional office</h3>
          <BarList data={d.by_region} label="Applications by region" />
          <p className="source">{Object.keys(d.by_region || {}).length} region(s) reported. Regions without applications are not listed.</p>
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

// Applications in process, region by stage, from the pendency report. Each cell is a count the report returned;
// an empty cell is zero for that region and stage. One region returned means one row.
function Pendency({ who }) {
  const p = useApi(who, "/dashboards/pendency");
  const rows = p.data?.rows ?? [];
  const regions = [...new Set(rows.map((r) => r.region))];
  const stages = [...new Set(rows.map((r) => r.stage))].sort((a, b) => (STAGE_ORDER.indexOf(a) + 1 || 99) - (STAGE_ORDER.indexOf(b) + 1 || 99));
  const cell = (region, stage) => rows.find((r) => r.region === region && r.stage === stage)?.count ?? 0;
  const max = Math.max(1, ...rows.map((r) => r.count));
  const rowTotal = (region) => rows.filter((r) => r.region === region).reduce((n, r) => n + r.count, 0);
  return (
    <section className="card pendency" aria-labelledby="pendency-title">
      <header className="card-head">
        <h2 id="pendency-title">Pendency by region and stage</h2>
        {p.data && <span className="muted small">{p.data.total} in process · {regions.length} region{regions.length === 1 ? "" : "s"}</span>}
      </header>
      {p.loading && !p.data && <Loading rows={3} />}
      <ErrorBox error={p.error} onRetry={p.reload} />
      {p.data && rows.length === 0 && <p className="muted">No applications are in process in this scope.</p>}
      {rows.length > 0 && (
        <div className="table-wrap">
          <table className="table heat" aria-label="Applications in process by region and current stage">
            <thead>
              <tr>
                <th scope="col">Region</th>
                {stages.map((s) => <th key={s} scope="col" className="num">{stageLabel(s)}</th>)}
                <th scope="col" className="num">Total</th>
              </tr>
            </thead>
            <tbody>
              {regions.map((region) => (
                <tr key={region}>
                  <th scope="row">{region}</th>
                  {stages.map((s) => {
                    const n = cell(region, s);
                    return (
                      <td key={s} className="num heat-cell" data-empty={n === 0 || undefined} style={{ "--heat": n / max }}>
                        <span>{n}</span>
                      </td>
                    );
                  })}
                  <td className="num"><strong>{rowTotal(region)}</strong></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {p.data?.coverage?.note && <p className="source">{p.data.coverage.note} Snapshot <code>{String(p.data.snapshot_hash).slice(0, 12)}</code> at ledger entry #{p.data.ledger_head?.seq}.</p>}
    </section>
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
  const section = (key) => data.sections.find((s) => s.key === key && s.status !== "NOT_AVAILABLE")?.data;
  const apps = section("applications");
  const deadlines = section("deadlines");
  const alerts = section("alerts");
  const available = data.sections.filter((s) => s.status !== "NOT_AVAILABLE");
  const missing = data.sections.filter((s) => s.status === "NOT_AVAILABLE");
  return (
    <div className="dashboard">
      <div className="freshness">
        <span className="scope-chip">{data.scope.region ? `${data.scope.region} region only` : "All regions"}</span>
        <span className="muted small">as of {when(data.scope.as_of)} · rebuilt from the audit event log</span>
        <button className="ghost small" onClick={reload}><Icon name="refresh" /> Refresh</button>
      </div>
      <Kpis label="Headline figures" items={[
        ...(apps ? [{ label: "Applications", value: apps.total }, { label: "In process", value: apps.by_status.IN_PROCESS ?? 0 }] : []),
        ...(deadlines ? [{ label: "Deadlines opened", value: deadlines.opened },
          { label: "Due date passed", value: deadlines.due_date_passed, hint: "may include met deadlines", tone: deadlines.due_date_passed ? "attention" : undefined }] : []),
        ...(alerts ? [{ label: "Dead letters", value: alerts.by_status.DEAD, tone: alerts.by_status.DEAD ? "bad" : undefined }] : []),
      ]} />
      <div className="dash-grid">
        <Pendency who={who} />
        {available.map((s) => <Section key={s.key} s={s} />)}
      </div>
      {missing.length > 0 && (
        <div className="dash-missing">
          <h2 className="subhead">Not available yet</h2>
          <div className="grid cards">
            {missing.map((s) => <Section key={s.key} s={s} />)}
          </div>
        </div>
      )}
    </div>
  );
}
