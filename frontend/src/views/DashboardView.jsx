import { useEffect } from "react";
import { Icon } from "../components/Icons.jsx";
import RegionColumns, { AgeingRadar } from "../components/RegionColumns.jsx";
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

// The hero answers the screen's question first. National scope ("Where is the load across the
// country?"): regional offices as 3D columns. Regional scope ("How old is my region's queue?"): the
// ageing radar (2D). Both are drawn from the same dashboard response as the panels below.
function Hero({ data }) {
  const by = Object.fromEntries(data.sections.map((s) => [s.key, s]));
  const apps = by.applications?.data;
  const ageing = by.ageing?.data?.buckets;
  if (!apps) return null;
  const inProcess = apps.by_status?.IN_PROCESS ?? 0;
  const regional = Boolean(data.scope.region);
  const regions = Object.keys(apps.by_region ?? {}).length;
  const old = ageing ? Object.entries(ageing).slice(2).reduce((a, [, n]) => a + n, 0) : null;
  return (
    <section className={`hero-band ${regional ? "regional" : "national"}`} data-reveal aria-labelledby="hero-title">
      <div className="hero-copy">
        <h2 id="hero-title">{regional ? `${data.scope.region} regional office` : "National control room"}</h2>
        <p className="hero-figure"><span className="num">{inProcess}</span> in process</p>
        <p className="hero-finding">
          {regional
            ? old == null ? "Ageing is not available." : old > 0 ? `${old} case${old === 1 ? " is" : "s are"} older than 30 days.` : "No case in process is older than 30 days."
            : `${apps.total} application${apps.total === 1 ? "" : "s"} across ${regions} regional office${regions === 1 ? "" : "s"} with cases.`}
        </p>
      </div>
      <div className="hero-visual">
        {regional ? (ageing ? <AgeingRadar buckets={ageing} /> : null) : <RegionColumns byRegion={apps.by_region} />}
      </div>
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
  return (
    <div className="dashboard">
      <div className="freshness">
        <span className="muted">
          {data.scope.region ? `${data.scope.region} region` : "All regions"} · as of {when(data.scope.as_of)} · rebuilt from
          the audit event log
        </span>
        <button className="ghost small" onClick={reload}><Icon name="refresh" /> Refresh</button>
      </div>
      <Hero data={data} />
      <div className="grid cards">
        {data.sections.map((s) => (
          <Section key={s.key} s={s} />
        ))}
      </div>
    </div>
  );
}
