import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { useActionKey } from "../actionKey.js";
import { sentence } from "../nav.js";
import { INTERNAL_REF_TITLE, internalRef } from "../provenance.js";
import {
  COI_CODES, SELECTOR_LABEL, SELECTOR_NOTE, SLOT_PARTS, evcStatusOf, explanationText, refusal, slotPartLabel,
} from "../workflowText.js";
import { Badge, Card, Empty, ErrorBox, Kpis, Loading, dateIST, useApi, useSingleFlight, when } from "../components/ui.jsx";

// policy.py: who may plan (evc.schedule.propose), publish (evc.schedule.publish), manage the pool
// (evc.expert.register / availability.set / coi.record) and read it (evc.expert.read). This only decides what is
// shown; the server authorises every request and scopes regional officers to their own region.
const PLANNERS = new Set(["RO_OFFICER", "BUREAU_OFFICER", "BUREAU_HEAD"]);
const PUBLISHERS = new Set(["BUREAU_OFFICER", "BUREAU_HEAD"]);
const POOL_READERS = new Set(["RO_OFFICER", "BUREAU_OFFICER", "BUREAU_HEAD", "SCRUTINY_COMMITTEE", "AUDITOR"]);
const STATUSES = ["QUEUED", "PROPOSED", "PUBLISHED", "DONE", "CANCELLED"];
// OR-Tools CP-SAT status numbers as stored with the run.
const SOLVER_STATUS = { 0: "Unknown", 1: "Model invalid", 2: "Feasible", 3: "Infeasible", 4: "Optimal" };

const todayIST = () => new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(new Date());
const addDays = (iso, n) => {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
};
const short = (id) => String(id).slice(0, 8);

export default function EvcView({ who, me }) {
  const regional = me.role === "RO_OFFICER";
  const [region, setRegion] = useState(regional ? me.region : "");
  const [chosenRun, setChosenRun] = useState(null);
  const [tick, setTick] = useState(0);
  // A run opened under one demo identity may be outside the next one's scope (an all-region run is not readable by a
  // regional officer), so switching identity starts again from that identity's newest run.
  useEffect(() => setChosenRun(null), [me.role, me.region, me.institution_id]);
  const refresh = () => setTick((t) => t + 1);
  const scope = regional ? me.region : region.trim();

  return (
    <div className="evc">
      <div className="alert simulated" role="note">
        <strong>{SELECTOR_LABEL}.</strong> {SELECTOR_NOTE} Visit length, AM/PM slots and the expert policy are demo assumptions.
      </div>
      <div className="toolbar">
        <label className="inline">
          Region
          {regional ? <input value={me.region} readOnly aria-describedby="region-note" />
            : <input value={region} placeholder="All regions" autoComplete="off" onChange={(e) => setRegion(e.target.value)} />}
        </label>
        <span id="region-note" className="muted small">{regional ? "Regional officers see and plan their own region only." : "Leave empty to see every region."}</span>
      </div>
      <Queue who={who} me={me} region={scope} tick={tick} />
      {PLANNERS.has(me.role) && (
        <Plan who={who} region={scope} onProposed={(id) => { setChosenRun(id); refresh(); }} />
      )}
      {POOL_READERS.has(me.role) && (
        <Runs key={`${who.key ?? who.mode}:${me.role}:${me.region ?? ""}`} who={who} me={me} region={scope} tick={tick} chosen={chosenRun} onChoose={setChosenRun} onChanged={refresh} />
      )}
      {POOL_READERS.has(me.role) && <Pool who={who} me={me} region={scope} tick={tick} onChanged={refresh} />}
    </div>
  );
}

// ---- queue ----

function Queue({ who, me, region, tick }) {
  const [status, setStatus] = useState("");
  const [picked, setPicked] = useState(null);
  const q = new URLSearchParams({ limit: "100" });
  if (status) q.set("status", status);
  if (region) q.set("region", region);
  const queue = useApi(who, `/evc/queue?${q}`);
  useEffect(() => { if (tick) queue.reload(); }, [tick]); // eslint-disable-line react-hooks/exhaustive-deps
  const rows = queue.data?.items ?? [];
  const chosen = rows.find((r) => r.id === picked);
  return (
    <section className="card" aria-labelledby="evc-queue-title">
      <header className="card-head">
        <h2 id="evc-queue-title">Visit requests {queue.data && <span className="count num">{queue.data.total}</span>}</h2>
        <label className="inline">
          Status
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All</option>
            {STATUSES.map((s) => <option key={s} value={s}>{evcStatusOf(s).label}</option>)}
          </select>
        </label>
      </header>
      <p className="muted small">Ordered by visit deadline. The time allowed for a visit is a demo assumption (EVC_DURATION_UNCONFIRMED).</p>
      {queue.loading && !queue.data && <Loading what="Loading the visit queue" rows={3} />}
      <ErrorBox error={refusal(queue.error)} onRetry={queue.reload} />
      {queue.data && rows.length === 0 && <Empty>No visit requests in this scope.</Empty>}
      {rows.length > 0 && (
        <div className="table-wrap">
          <table className="table" tabIndex={0}>
            <thead>
              <tr>
                <th scope="col">Case</th><th scope="col">Region</th><th scope="col">Category</th>
                <th scope="col">Window</th><th scope="col">Status</th><th scope="col" className="num">Waiting (days)</th>
                {POOL_READERS.has(me.role) && <th scope="col">Panel preview</th>}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className={picked === r.id ? "current" : undefined}>
                  <td><code title={INTERNAL_REF_TITLE}>{internalRef(r.application_id)}</code></td>
                  <td>{r.region}</td>
                  <td>{sentence(r.category)}</td>
                  <td className="nowrap">{dateIST(r.earliest_date)} to {dateIST(r.due_by)}</td>
                  <td><Badge tone={evcStatusOf(r.status).tone}>{evcStatusOf(r.status).label}</Badge></td>
                  <td className="num">{r.days_waiting}</td>
                  {POOL_READERS.has(me.role) && (
                    <td>
                      {["QUEUED", "PROPOSED"].includes(r.status) ? (
                        <button className="small secondary" aria-pressed={picked === r.id} onClick={() => setPicked(picked === r.id ? null : r.id)}>
                          {picked === r.id ? "Hide" : "Preview"}
                        </button>
                      ) : <span className="muted small">—</span>}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {chosen && <PanelPreview key={chosen.id} who={who} request={chosen} />}
    </section>
  );
}

function PanelPreview({ who, request }) {
  const [date, setDate] = useState(request.earliest_date > todayIST() ? request.earliest_date : todayIST());
  const [part, setPart] = useState("AM");
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const look = (e) => {
    e.preventDefault();
    setError(null);
    api(who, `/evc/requests/${request.id}/panel-preview?date=${date}&slot_part=${part}`).then(setResult).catch((err) => { setResult(null); setError(err); });
  };
  return (
    <form className="action-form" onSubmit={look} aria-label={`Panel preview for case ${internalRef(request.application_id)}`}>
      <h3>Panel preview <Badge tone="sample">Simulated</Badge></h3>
      <p className="muted small">A read-only ranking by the {SELECTOR_LABEL}: nothing is reserved or appointed.</p>
      <div className="inline-form">
        <label>Date <input type="date" value={date} onChange={(e) => setDate(e.target.value)} required /></label>
        <label>
          Half-day
          <select value={part} onChange={(e) => setPart(e.target.value)}>{SLOT_PARTS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
        </label>
        <button className="small">Preview panel</button>
      </div>
      <ErrorBox error={refusal(error)} />
      {result && (
        <div role="status">
          <p>
            {result.status === "SELECTED"
              ? `A panel of ${result.panel.length} could be formed from ${result.eligible_count} eligible experts.`
              : `Not enough eligible experts: ${result.eligible_count} eligible, ${result.requested_size} needed.`}
          </p>
          {result.panel.length > 0 && <p className="muted small">Panel: {result.panel.map((id) => <code key={id}>{short(id)} </code>)} (identities unverified)</p>}
        </div>
      )}
    </form>
  );
}

// ---- propose ----

function Plan({ who, region, onProposed }) {
  const [algorithm, setAlgorithm] = useState("CPSAT");
  const [start, setStart] = useState(todayIST());
  const [end, setEnd] = useState(addDays(todayIST(), 13));
  const [capacity, setCapacity] = useState("");
  const [failure, setFailure] = useState(null);
  const [busy, setBusy] = useState(false);
  const key = useActionKey();
  const attempt = useRef(null); // { signature, run_id } — the run id is kept with the key for a retry
  const once = useSingleFlight();

  const submit = (e) => {
    e.preventDefault();
    return once(async () => {
      const fields = { algorithm, horizon_start: start, horizon_end: end, ...(region ? { region } : {}),
        ...(capacity ? { slot_capacity: Number(capacity) } : {}) };
      const signature = JSON.stringify(fields);
      if (attempt.current?.signature !== signature) attempt.current = { signature, run_id: crypto.randomUUID() };
      const body = { run_id: attempt.current.run_id, ...fields };
      setBusy(true);
      setFailure(null);
      try {
        const out = await api(who, "/evc/schedule:propose", { method: "POST", body, headers: { "Idempotency-Key": key.for(signature) } });
        key.settle(null);
        attempt.current = null;
        onProposed(out.run_id);
      } catch (err) {
        key.settle(err);
        if (!key.pending()) attempt.current = null;
        setFailure(err);
      } finally {
        setBusy(false);
      }
    });
  };

  return (
    <Card title="Plan visits" className="evc-plan">
      <form onSubmit={submit} aria-label="Propose a visit schedule">
        <fieldset className="choice">
          <legend>Planner</legend>
          <label className="inline"><input type="radio" name="algorithm" value="CPSAT" checked={algorithm === "CPSAT"} onChange={() => setAlgorithm("CPSAT")} />
            CP-SAT optimiser (most visits, then least lateness)</label>
          <label className="inline"><input type="radio" name="algorithm" value="EDF" checked={algorithm === "EDF"} onChange={() => setAlgorithm("EDF")} />
            Earliest deadline first (baseline)</label>
        </fieldset>
        <div className="form-grid">
          <label>From <input type="date" value={start} onChange={(e) => setStart(e.target.value)} required /></label>
          <label>To <input type="date" value={end} min={start} onChange={(e) => setEnd(e.target.value)} required /></label>
          <label>
            Visits per half-day (optional)
            <input type="number" min={1} max={50} value={capacity} onChange={(e) => setCapacity(e.target.value)} aria-describedby="cap-note" />
          </label>
        </div>
        <p id="cap-note" className="muted small">
          Planning covers {region ? `region ${region}` : "every region"}. Capacity, when given, creates the missing AM/PM slots in the window
          (demo assumption); existing slots keep theirs. A proposal reserves its experts and slots until published; it publishes nothing.
        </p>
        <ErrorBox error={refusal(failure)} />
        {failure && key.pending() && <p className="muted small">Trying again sends the same proposal, so it cannot be made twice.</p>}
        <div className="actions"><button disabled={busy}>{busy ? "Planning…" : "Propose schedule"}</button></div>
      </form>
    </Card>
  );
}

// ---- runs: list, detail, comparison, publication and discard ----

const RUN_STATUS = {
  PROPOSED: { tone: "info", label: "Proposed, not published" },
  PUBLISHED: { tone: "ok", label: "Published" },
  DISCARDED: { tone: "neutral", label: "Discarded" },
};
const runStatusOf = (s) => RUN_STATUS[s] ?? { tone: "neutral", label: sentence(s) || "Status not supplied" };
const planner = (a) => (a === "CPSAT" ? "CP-SAT" : "EDF");

// Proposal runs come from GET /evc/schedule/runs (scoped by the server: a regional officer sees the runs planned
// for its own region). The run just proposed, or the newest one, opens in full from GET /evc/schedule/runs/{id}.
function Runs({ who, me, region, tick, chosen, onChoose, onChanged }) {
  const [status, setStatus] = useState("");
  const [algorithm, setAlgorithm] = useState("");
  const q = new URLSearchParams({ limit: "20" });
  if (status) q.set("status", status);
  if (algorithm) q.set("algorithm", algorithm);
  if (region) q.set("region", region);
  const list = useApi(who, `/evc/schedule/runs?${q}`);
  useEffect(() => { if (tick) list.reload(); }, [tick]); // eslint-disable-line react-hooks/exhaustive-deps
  const runs = list.data?.items ?? [];
  // While the list reloads it still holds the previous identity's rows; only open the newest run once it settles.
  const open = chosen ?? (list.loading ? null : runs[0]?.run_id) ?? null;
  return (
    <>
      {open && <RunDetail key={open} who={who} me={me} runId={open} tick={tick} onChanged={onChanged} />}
      <section className="card" aria-labelledby="evc-runs-title">
        <header className="card-head">
          <h2 id="evc-runs-title">Proposal runs {list.data && <span className="count num">{list.data.total}</span>}</h2>
          <div className="inline-form">
            <label className="inline">
              State
              <select value={status} onChange={(e) => setStatus(e.target.value)}>
                <option value="">All</option>
                {Object.entries(RUN_STATUS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
              </select>
            </label>
            <label className="inline">
              Planner
              <select value={algorithm} onChange={(e) => setAlgorithm(e.target.value)}>
                <option value="">Both</option>
                <option value="CPSAT">CP-SAT</option>
                <option value="EDF">EDF</option>
              </select>
            </label>
          </div>
        </header>
        <p className="muted small">
          Every run is scored by the same metrics. Two runs are a fair comparison only when they planned the same input (same
          fingerprint): a later run sees only the requests earlier runs left queued. Discarding a proposal puts its requests back in the queue.
        </p>
        {list.loading && !list.data && <Loading what="Loading proposal runs" rows={2} />}
        <ErrorBox error={refusal(list.error)} onRetry={list.reload} />
        {list.data && runs.length === 0 && <Empty>No proposal runs in this scope yet.</Empty>}
        {runs.length > 0 && (
          <div className="table-wrap">
            <table className="table" tabIndex={0}>
              <caption className="sr-only">Proposal runs, newest first</caption>
              <thead>
                <tr>
                  <th scope="col">Run</th><th scope="col">Planner</th><th scope="col">Scope</th><th scope="col">Input</th>
                  <th scope="col" className="num">Requests</th><th scope="col" className="num">Planned</th><th scope="col" className="num">Unplanned</th>
                  <th scope="col" className="num">Late</th><th scope="col" className="num">Total lateness (days)</th>
                  <th scope="col" className="num">Waiting (days)</th><th scope="col" className="num">Rule breaks</th><th scope="col">State</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.run_id} className={open === r.run_id ? "current" : undefined}>
                    <td className="nowrap">
                      <button type="button" className="small secondary" aria-pressed={open === r.run_id} onClick={() => onChoose(r.run_id)}
                        aria-label={`Open run ${short(r.run_id)}`}>
                        {short(r.run_id)}
                      </button>
                      <span className="muted small"> {when(r.created_at)}</span>
                    </td>
                    <td>{planner(r.algorithm)}</td>
                    <td>{r.region_scope ?? "All regions"}</td>
                    <td><code title={r.input_fingerprint}>{r.input_fingerprint.slice(0, 10)}</code></td>
                    <td className="num">{r.metrics.queue_count}</td>
                    <td className="num">{r.metrics.scheduled}</td>
                    <td className="num">{r.metrics.unscheduled}</td>
                    <td className="num">{r.metrics.late_count}</td>
                    <td className="num">{r.metrics.total_lateness}</td>
                    <td className="num">{r.metrics.total_waiting}</td>
                    <td className="num">{r.metrics.hard_constraint_violations}</td>
                    <td><Badge tone={runStatusOf(r.status).tone}>{runStatusOf(r.status).label}</Badge></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}

const PUBLISH_CONFLICTS = new Set(["EVC_EXPERT_DOUBLE_BOOKED", "EVC_SLOT_CAPACITY_EXHAUSTED", "EVC_EXPERT_DAILY_CAP_EXCEEDED",
  "EVC_PUBLISH_RECHECK_FAILED"]);

function RunDetail({ who, me, runId, tick, onChanged }) {
  const read = useApi(who, `/evc/schedule/runs/${runId}`);
  useEffect(() => { if (tick) read.reload(); }, [tick]); // eslint-disable-line react-hooks/exhaustive-deps
  const [failure, setFailure] = useState(null);
  const [done, setDone] = useState(null);
  const [busy, setBusy] = useState(null);
  const key = useActionKey();
  const once = useSingleFlight();
  const run = read.data;

  // Publish and discard each send one Idempotency-Key per user action, reused if the same action is retried.
  const command = (name, path, message) => once(async () => {
    setBusy(name);
    setFailure(null);
    setDone(null);
    try {
      const out = await api(who, path, { method: "POST", body: { run_id: runId }, headers: { "Idempotency-Key": key.for(`${name} ${runId}`) } });
      key.settle(null);
      setDone(message(out));
      onChanged();
    } catch (err) {
      key.settle(err);
      setFailure(err);
    } finally {
      setBusy(null);
    }
  });
  const publish = () => command("publish", "/evc/schedule:publish",
    (x) => `Published ${x.published_count} visit${x.published_count === 1 ? "" : "s"}. The visits can now be completed on the cases.`);
  const discard = () => command("discard", "/evc/schedule:discard",
    (x) => `Discarded. ${x.discarded_count} request${x.discarded_count === 1 ? " is" : "s are"} back in the queue for a new proposal.`);

  if (!run) {
    return (
      <section className="card" aria-label="Proposal run">
        {read.loading && <Loading what="Opening the proposal run" rows={3} />}
        <ErrorBox error={refusal(read.error)} onRetry={read.reload} />
      </section>
    );
  }
  const m = run.metrics;
  const proposed = run.status === "PROPOSED";
  const s = runStatusOf(run.status);
  return (
    <section className="card" aria-labelledby="evc-run-title">
      <header className="card-head">
        <h2 id="evc-run-title">{planner(run.algorithm)} proposal · {dateIST(run.horizon_start)} to {dateIST(run.horizon_end)}</h2>
        <Badge tone={s.tone}>{s.label}</Badge>
      </header>
      <p className="muted small">
        Run reference <code>{run.run_id}</code> · {run.region_scope ? `region ${run.region_scope}` : "all regions"} · made {when(run.created_at)} ·
        panels by the {run.selector_label} <Badge tone="sample">Simulated</Badge>
      </p>
      <dl className="facts run-limits" aria-label="Planning limits used for this run">
        <dt>Visits per expert per day</dt>
        <dd>{run.expert_daily_cap ?? "Not recorded"} <Badge tone="sample">Demo assumption</Badge></dd>
        <dt>Visits per half-day slot</dt>
        <dd>{run.slot_capacity != null ? `${run.slot_capacity} in the slots this run created; existing slots kept theirs` : "Existing slots only"}</dd>
        {run.algorithm === "CPSAT" && (
          <>
            <dt>Candidate window</dt>
            <dd>{run.candidate_slots != null ? `The earliest ${run.candidate_slots} feasible slots per request, plus the baseline's own` : "Not recorded"}</dd>
          </>
        )}
      </dl>
      <Kpis label="Proposal metrics" items={[
        { label: "Requests", value: m.queue_count },
        { label: "Planned", value: m.scheduled, tone: m.scheduled ? "ok" : undefined },
        { label: "Unplanned", value: m.unscheduled, tone: m.unscheduled ? "attention" : undefined },
        { label: "Late", value: m.late_count, tone: m.late_count ? "attention" : undefined },
        { label: "Total lateness (days)", value: m.total_lateness },
        { label: "Rule breaks", value: m.hard_constraint_violations, tone: m.hard_constraint_violations ? "bad" : undefined },
      ]} />
      {run.proposals.length > 0 && (
        <div className="table-wrap">
          <table className="table" tabIndex={0}>
            <caption className="sr-only">Proposed visits</caption>
            <thead>
              <tr><th scope="col">Case</th><th scope="col">Visit</th><th scope="col" className="num">Panel</th><th scope="col">Due by</th><th scope="col" className="num">Days late</th></tr>
            </thead>
            <tbody>
              {run.proposals.map((p) => (
                <tr key={p.assignment_id}>
                  <td><code title={INTERNAL_REF_TITLE}>{internalRef(p.application_id)}</code></td>
                  <td className="nowrap">{dateIST(p.date)} · {slotPartLabel(p.slot_part)}</td>
                  <td className="num" title={p.expert_ids.join(", ")}>{p.expert_ids.length} experts</td>
                  <td className="nowrap">{dateIST(p.due_by)}</td>
                  <td className="num">{p.lateness_days}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {run.unscheduled.length > 0 && (
        <div>
          <h3>Not planned</h3>
          <ul className="round-items">
            {run.unscheduled.map((u) => (
              <li key={u.request_id}>
                Case <code title={INTERNAL_REF_TITLE}>{internalRef(u.application_id)}</code>: {explanationText(u.explanation_code)} It stays queued.
              </li>
            ))}
          </ul>
        </div>
      )}
      {!run.outcomes_recorded && <p className="muted small">This run was made before unplanned requests were recorded, so they are not listed.</p>}
      {run.withdrawn?.length > 0 && (
        <p className="muted small">
          Returned to the queue by the discard: {run.withdrawn.map((w) => <code key={w.request_id} title={INTERNAL_REF_TITLE}>{internalRef(w.application_id)} </code>)}
        </p>
      )}
      {run.solver && (
        <details className="solver">
          <summary>Solver details</summary>
          <dl className="facts">
            <dt>Result</dt><dd>{SOLVER_STATUS[run.solver.solver_status] ?? run.solver.solver_status}</dd>
            <dt>Objective / best bound</dt><dd className="num">{run.solver.objective_value} / {run.solver.best_bound}</dd>
            <dt>Request and slot pairs modelled</dt><dd className="num">{run.solver.candidate_count}</dd>
            <dt>Repair rounds</dt><dd className="num">{run.solver.repair_rounds}</dd>
            <dt>EDF baseline planned</dt><dd className="num">{run.solver.edf_scheduled}</dd>
            <dt>Kept the EDF plan</dt><dd>{run.solver.fallback_to_edf ? "Yes, it scored better" : "No"}</dd>
          </dl>
        </details>
      )}
      {done && <p className="ok" role="status">{done}</p>}
      <ErrorBox error={refusal(failure)} />
      {failure && PUBLISH_CONFLICTS.has(failure.reason) && (
        <p className="muted small">Discard this proposal and plan again once the conflict is resolved.</p>
      )}
      {proposed && PUBLISHERS.has(me.role) && (
        <div className="actions">
          {run.proposals.length > 0 && (
            <button onClick={publish} disabled={Boolean(busy)}>{busy === "publish" ? "Publishing…" : "Publish this schedule"}</button>
          )}
          <button className="secondary" onClick={discard} disabled={Boolean(busy)}>{busy === "discard" ? "Discarding…" : "Discard this proposal"}</button>
          <span className="muted small">
            Publishing checks every visit again against published visits; any conflict publishes nothing. Discarding releases the
            experts and slots and returns the requests to the queue.
          </span>
        </div>
      )}
      {proposed && !PUBLISHERS.has(me.role) && (
        <p className="muted small">Only the bureau publishes or discards a schedule. This proposal holds its experts and slots until then.</p>
      )}
    </section>
  );
}


// ---- expert pool ----

function Pool({ who, me, region, tick, onChanged }) {
  const [on, setOn] = useState("");
  const [part, setPart] = useState("");
  const q = new URLSearchParams({ limit: "100" });
  if (region) q.set("region", region);
  if (on) q.set("available_on", on);
  if (on && part) q.set("slot_part", part);
  const pool = useApi(who, `/evc/experts?${q}`);
  useEffect(() => { if (tick) pool.reload(); }, [tick]); // eslint-disable-line react-hooks/exhaustive-deps
  const manage = PLANNERS.has(me.role);
  const changed = () => { pool.reload(); onChanged(); };
  return (
    <section className="card" aria-labelledby="evc-pool-title">
      <header className="card-head">
        <h2 id="evc-pool-title">Expert pool {pool.data && <span className="count num">{pool.data.total}</span>}</h2>
      </header>
      <p className="muted small">
        Experts are opaque user references with coded expertise; identities are not verified against a user directory yet.
        {pool.data && ` Region rule: ${sentence(pool.data.region_rule)} (demo assumption).`}
      </p>
      <div className="inline-form">
        <label>Available on <input type="date" value={on} onChange={(e) => setOn(e.target.value)} /></label>
        <label>
          Half-day
          <select value={part} onChange={(e) => setPart(e.target.value)} disabled={!on}>
            <option value="">Either</option>
            {SLOT_PARTS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
        </label>
      </div>
      {pool.loading && !pool.data && <Loading what="Loading experts" rows={2} />}
      <ErrorBox error={refusal(pool.error)} onRetry={pool.reload} />
      {pool.data?.items.length === 0 && <Empty>No experts match.</Empty>}
      {pool.data?.items.length > 0 && (
        <div className="table-wrap">
          <table className="table" tabIndex={0}>
            <thead><tr><th scope="col">Expert</th><th scope="col">Region</th><th scope="col">Expertise</th><th scope="col">Active</th>{on && <th scope="col">Free</th>}</tr></thead>
            <tbody>
              {pool.data.items.map((x) => (
                <tr key={x.id}>
                  <td><code title={`user reference ${x.user_ref} (unverified)`}>{short(x.id)}</code></td>
                  <td>{x.region}</td>
                  <td>{x.expertise_tags.join(", ")}</td>
                  <td>{x.active ? "Yes" : "No"}</td>
                  {on && <td>{(x.available_parts ?? []).map(slotPartLabel).join(", ") || "—"}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {manage && (
        <div className="pool-forms">
          <RegisterExpert who={who} me={me} region={region} onChanged={changed} />
          <Availability who={who} experts={pool.data?.items ?? []} onChanged={changed} />
          <Conflict who={who} experts={pool.data?.items ?? []} onChanged={changed} />
        </div>
      )}
    </section>
  );
}

// One POST with an Idempotency-Key per user action, reused when the same action is retried.
function usePost(who, onDone) {
  const key = useActionKey();
  const [failure, setFailure] = useState(null);
  const [done, setDone] = useState(null);
  const [busy, setBusy] = useState(false);
  const once = useSingleFlight();
  const post = (path, body, message) => once(async () => {
    setBusy(true);
    setFailure(null);
    setDone(null);
    try {
      const out = await api(who, path, { method: "POST", body, headers: { "Idempotency-Key": key.for(`${path} ${JSON.stringify(body)}`) } });
      key.settle(null);
      setDone(message(out));
      onDone?.();
      return out;
    } catch (err) {
      key.settle(err);
      setFailure(err);
      return null;
    } finally {
      setBusy(false);
    }
  });
  return { post, failure, done, busy };
}

function RegisterExpert({ who, me, region, onChanged }) {
  const [userRef, setUserRef] = useState(() => crypto.randomUUID());
  const [expertRegion, setExpertRegion] = useState(me.role === "RO_OFFICER" ? me.region : region || "");
  const [tags, setTags] = useState("DEMO");
  const w = usePost(who, onChanged);
  const submit = async (e) => {
    e.preventDefault();
    const body = { user_ref: userRef, region: expertRegion.trim(), expertise_tags: tags.split(",").map((t) => t.trim().toUpperCase()).filter(Boolean), active: true };
    if (await w.post("/evc/experts", body, (x) => `Registered expert ${short(x.id)} in ${x.region}.`)) setUserRef(crypto.randomUUID());
  };
  return (
    <form className="action-form" onSubmit={submit} aria-label="Register an expert">
      <h3>Register an expert</h3>
      <label>
        User reference
        <input value={userRef} onChange={(e) => setUserRef(e.target.value)} pattern="[0-9a-fA-F\-]{36}" required spellCheck={false} />
      </label>
      <p className="muted small">An opaque reference, not a name. Use a synthetic one; no personal details are collected here.</p>
      <label>Region <input value={expertRegion} readOnly={me.role === "RO_OFFICER"} onChange={(e) => setExpertRegion(e.target.value)} required pattern="[A-Za-z][A-Za-z0-9_]*" /></label>
      <label>Expertise codes (comma-separated) <input value={tags} onChange={(e) => setTags(e.target.value)} required /></label>
      <ErrorBox error={refusal(w.failure)} />
      {w.done && <p className="ok small" role="status">{w.done}</p>}
      <div className="actions"><button className="small" disabled={w.busy}>Register</button></div>
    </form>
  );
}

function Availability({ who, experts, onChanged }) {
  const [expert, setExpert] = useState("");
  const [from, setFrom] = useState(todayIST());
  const [to, setTo] = useState(addDays(todayIST(), 13));
  const [parts, setParts] = useState(["AM", "PM"]);
  const [available, setAvailable] = useState(true);
  const w = usePost(who, onChanged);
  const chosen = expert || experts[0]?.id || "";
  const submit = (e) => {
    e.preventDefault();
    const items = [];
    for (let d = from; d <= to && items.length < 732; d = addDays(d, 1)) for (const p of parts) items.push({ date: d, slot_part: p, available });
    w.post(`/evc/experts/${chosen}/availability`, { items }, (x) => `Saved ${x.items.length} half-days (${x.changed_count} changed).`);
  };
  return (
    <form className="action-form" onSubmit={submit} aria-label="Set availability">
      <h3>Set availability</h3>
      <label>
        Expert
        <select value={chosen} onChange={(e) => setExpert(e.target.value)} required>
          {experts.map((x) => <option key={x.id} value={x.id}>{short(x.id)} · {x.region}</option>)}
        </select>
      </label>
      <div className="form-grid">
        <label>From <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} required /></label>
        <label>To <input type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} required /></label>
      </div>
      <fieldset className="choice">
        <legend>Half-days</legend>
        {SLOT_PARTS.map(([k, l]) => (
          <label key={k} className="inline">
            <input type="checkbox" checked={parts.includes(k)} onChange={(e) => setParts((s) => (e.target.checked ? [...s, k] : s.filter((x) => x !== k)))} /> {l}
          </label>
        ))}
        <label className="inline"><input type="checkbox" checked={available} onChange={(e) => setAvailable(e.target.checked)} /> Available (untick to mark unavailable)</label>
      </fieldset>
      <ErrorBox error={refusal(w.failure)} />
      {w.done && <p className="ok small" role="status">{w.done}</p>}
      <div className="actions"><button className="small" disabled={w.busy || !chosen || !parts.length || to < from}>Save availability</button></div>
    </form>
  );
}

function Conflict({ who, experts, onChanged }) {
  const institutions = useApi(who, "/institutions");
  const [expert, setExpert] = useState("");
  const [institution, setInstitution] = useState("");
  const [code, setCode] = useState(COI_CODES[0][0]);
  const w = usePost(who, onChanged);
  const chosenExpert = expert || experts[0]?.id || "";
  const chosenInstitution = institution || institutions.data?.[0]?.id || "";
  const submit = (e) => {
    e.preventDefault();
    w.post("/evc/coi", { expert_id: chosenExpert, institution_ref: chosenInstitution, source: code, reason_code: code },
      (x) => (x.created ? "Conflict of interest recorded. The expert will not be put on this institution's panels." : "This conflict was already recorded."));
  };
  return (
    <form className="action-form" onSubmit={submit} aria-label="Record a conflict of interest">
      <h3>Record a conflict of interest</h3>
      <label>
        Expert
        <select value={chosenExpert} onChange={(e) => setExpert(e.target.value)} required>
          {experts.map((x) => <option key={x.id} value={x.id}>{short(x.id)} · {x.region}</option>)}
        </select>
      </label>
      <label>
        Institution
        <select value={chosenInstitution} onChange={(e) => setInstitution(e.target.value)} required>
          {(institutions.data ?? []).map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}
        </select>
      </label>
      <label>
        Reason
        <select value={code} onChange={(e) => setCode(e.target.value)}>{COI_CODES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
      </label>
      <ErrorBox error={refusal(w.failure)} />
      {w.done && <p className="ok small" role="status">{w.done}</p>}
      <div className="actions"><button className="small" disabled={w.busy || !chosenExpert || !chosenInstitution}>Record conflict</button></div>
    </form>
  );
}
