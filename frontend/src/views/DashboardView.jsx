import OperationsPulse from "../product/Instruments.jsx";

import { useEffect } from "react";

import { DEMO_USERS } from "../api.js";

import { Icon } from "../components/Icons.jsx";

import { STAGE_LABEL, stageLabel } from "../components/RouteJourney.jsx";

import { Badge, BarList, Card, Empty, ErrorBox, Kpis, Loading, NotAvailable, StatTile, useApi, when } from "../components/ui.jsx";

import { sentence } from "../nav.js";

import { alertStatusOf, deadlineStatusOf, letterLabel, obligationStatusOf, ruleLabel } from "../recordText.js";

import { evcStatusOf } from "../workflowText.js";



const STAGE_ORDER = Object.keys(STAGE_LABEL);

const byStageOrder = (data) => Object.fromEntries(Object.entries(data || {})

  .sort(([a], [b]) => (STAGE_ORDER.indexOf(a) + 1 || 99) - (STAGE_ORDER.indexOf(b) + 1 || 99)));

const stageKeys = (data) => Object.fromEntries(Object.entries(data || {}).map(([k, v]) => [STAGE_LABEL[k] ?? k, v]));

// Readable keys for a count map: rule ids, statuses and letter types become the words used on their own screens.

const relabel = (data, label) => Object.fromEntries(Object.entries(data || {}).map(([k, v]) => [label(k), v]));

const COMMITTEE_LABEL = { SCRUTINY: "Scrutiny", RESCRUTINY: "Re-scrutiny", EVC: "Expert visit", SHC: "Standing hearing", EC: "Executive", COUNCIL: "Council" };



// Officers are references in the record; a demo session can name its demo users, otherwise the short reference shows.

function officerName(ref, who, me) {

  if (me && ref === me.user_id) return "You";

  const user = who?.mode !== "oidc" ? DEMO_USERS.find((u) => u.user === ref) : null;

  return user ? user.label : `Officer ${ref.slice(0, 8)}`;

}



function Section({ s, who, me }) {

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

            <StatTile label="Open clocks" value={d.open} />

            <StatTile label="Overdue" value={d.overdue} />

            <StatTile label="Met" value={d.met} hint={d.met_late ? `${d.met_late} met late` : undefined} />

          </div>

          <h3>By state</h3>

          <BarList data={relabel(d.by_status, (k) => deadlineStatusOf(k).label)} label="Deadlines by state" />

          <h3>Open clocks by rule</h3>

          <BarList data={relabel(d.by_rule, ruleLabel)} label="Open deadlines by rule" />

        </>

      )}

      {s.key === "workload" && (

        <>

          <div className="stats">

            <StatTile label="Committees" value={d.committees} />

            <StatTile label="Open tasks" value={d.open_tasks} />

            <StatTile label="Officers" value={d.officers} />

          </div>

          <h3>By officer</h3>

          {d.by_officer.length === 0 ? <Empty>No committee work on cases in process.</Empty> : (

            <div className="table-wrap">

              <table className="table" tabIndex={0} aria-label="Workload by officer">

                <thead>

                  <tr><th scope="col">Officer</th><th scope="col" className="num">Open tasks</th><th scope="col" className="num">Committees</th></tr>

                </thead>

                <tbody>

                  {d.by_officer.map((o) => (

                    <tr key={o.user_ref}>

                      <th scope="row" title={o.user_ref}>{officerName(o.user_ref, who, me)}</th>

                      <td className="num">{o.open_tasks}</td>

                      <td className="num">{o.committees}</td>

                    </tr>

                  ))}

                </tbody>

              </table>

            </div>

          )}

          {d.officers > d.by_officer.length && <p className="source">The {d.by_officer.length} busiest of {d.officers} officers are listed.</p>}

          <h3>By committee</h3>

          <BarList data={Object.fromEntries(Object.entries(d.by_committee).map(([k, v]) => [COMMITTEE_LABEL[k] ?? sentence(k), v.open_tasks]))} label="Open tasks by committee" />

        </>

      )}

      {s.key === "evc" && (

        <>

          <div className="stats">

            <StatTile label="Open requests" value={d.open} />

            <StatTile label="Overdue" value={d.overdue} />

            <StatTile label="Published schedules" value={d.published_schedules} hint={`${d.upcoming_visits} visit(s) ahead`} />

          </div>

          <BarList data={relabel(d.by_status, (k) => evcStatusOf(k).label)} label="EVC requests by status" />

        </>

      )}

      {s.key === "compliance" && (

        <>

          <div className="stats">

            <StatTile label="Obligations" value={d.obligations} />

            <StatTile label="Overdue" value={d.overdue} />

            <StatTile label="Evidence awaiting an officer" value={d.awaiting_verification} />

          </div>

          <h3>By status</h3>

          <BarList data={relabel(d.by_status, (k) => obligationStatusOf(k).label)} label="Obligations by status" />

          <h3>By kind</h3>

          <BarList data={relabel(d.by_kind, sentence)} label="Obligations by kind" />

          {Object.keys(d.letters).length > 0 && <p className="source">Letters registered: {Object.entries(d.letters).map(([k, n]) => `${n} ${letterLabel(k)}`).join(", ")}.</p>}

        </>

      )}

      {s.key === "alerts" && (

        <>

          <div className="stats">

            <StatTile label="Delivered" value={d.by_status.DELIVERED} />

            <StatTile label="Waiting" value={d.by_status.PENDING + d.by_status.SENDING} />

            <StatTile label="Dead letters" value={d.by_status.DEAD} />

            <StatTile

              label="First-try success (24 h)"

              value={d.first_try_success_rate_24h == null ? "—" : `${Math.round(d.first_try_success_rate_24h * 100)}%`}

            />

          </div>

          {d.alerts && (

            <>

              <h3>Alerts raised</h3>

              <BarList data={relabel(d.alerts.by_status, (k) => alertStatusOf(k).label)} label="Alerts by status" />

            </>

          )}

        </>

      )}

      {s.note && <p className="muted small">{s.note}</p>}

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



export default function DashboardView({ who, me, onNavigate }) {

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

      {me && <OperationsPulse who={who} me={me} counts={apps?.by_stage} onNavigate={onNavigate} />}

      <Kpis label="Headline figures" items={[

        ...(apps ? [{ label: "Applications", value: apps.total }, { label: "In process", value: apps.by_status.IN_PROCESS ?? 0 }] : []),

        ...(deadlines ? [{ label: "Open deadlines", value: deadlines.open },

          { label: "Overdue", value: deadlines.overdue, tone: deadlines.overdue ? "attention" : undefined }] : []),

        ...(alerts ? [{ label: "Dead letters", value: alerts.by_status.DEAD, tone: alerts.by_status.DEAD ? "bad" : undefined }] : []),

      ]} />



      <div className="dash-grid">

        <Pendency who={who} />

        {available.map((s) => <Section key={s.key} s={s} who={who} me={me} />)}

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

