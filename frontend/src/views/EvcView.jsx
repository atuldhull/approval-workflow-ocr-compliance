import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { useActionKey } from "../actionKey.js";
import { sentence } from "../nav.js";
import { INTERNAL_REF_TITLE, internalRef } from "../provenance.js";
import {
  COI_CODES, SELECTOR_LABEL, SELECTOR_NOTE, SLOT_PARTS, evcStatusOf, refusal, slotPartLabel,
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

// There is no endpoint that lists or reads proposal runs yet, so the proposals made in this browser tab are kept
// in sessionStorage (a convenience only: a reload of the tab keeps them, nothing else does). A bureau officer
// elsewhere publishes a run by its reference, which the planner passes on.
const RUNS_KEY = "awoc.evc-runs";
function readRuns() {
  try {
    const value = JSON.parse(sessionStorage.getItem(RUNS_KEY) ?? "[]");
    return Array.isArray(value) ? value : [];
  } catch {
    return [];
  }
}
function useRuns() {
  const [runs, setState] = useState(readRuns);
  const setRuns = (update) => setState((current) => {
    const next = typeof update === "function" ? update(current) : update;
    try { sessionStorage.setItem(RUNS_KEY, JSON.stringify(next.slice(0, 10))); } catch { /* convenience only */ }
    return next;
  });
  return [runs, setRuns];
}

export default function EvcView({ who, me }) {
  const regional = me.role === "RO_OFFICER";
  const [region, setRegion] = useState(regional ? me.region : "");
  const [runs, setRuns] = useRuns();
  const [tick, setTick] = useState(0);
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
        <Plan who={who} me={me} region={scope} runs={runs} setRuns={setRuns} onChanged={refresh} />
      )}
      {runs.length > 0 && <Runs who={who} me={me} runs={runs} setRuns={setRuns} onChanged={refresh} />}
      {PUBLISHERS.has(me.role) && <PublishByReference who={who} setRuns={setRuns} onChanged={refresh} />}
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

function Plan({ who, me, region, runs, setRuns, onChanged }) {
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
        setRuns((r) => [{ ...out, published: null }, ...r.filter((x) => x.run_id !== out.run_id)]);
        onChanged();
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

// ---- runs: detail, comparison and publication ----

function Runs({ who, me, runs, setRuns, onChanged }) {
  const latest = runs[0];
  return (
    <>
      <RunDetail who={who} me={me} run={latest} setRuns={setRuns} onChanged={onChanged} />
      <section className="card" aria-labelledby="evc-compare-title">
        <header className="card-head"><h2 id="evc-compare-title">Compare proposals</h2></header>
        <p className="muted small">
          Every proposal made in this session, scored by the same metrics. Two runs are a fair comparison only when they planned the same
          input (same fingerprint): a later run sees only requests the earlier one left queued, and a proposal cannot be discarded yet.
        </p>
        <div className="table-wrap">
          <table className="table" tabIndex={0}>
            <thead>
              <tr>
                <th scope="col">Planner</th><th scope="col">Input</th><th scope="col" className="num">Requests</th>
                <th scope="col" className="num">Planned</th><th scope="col" className="num">Unplanned</th><th scope="col" className="num">Late</th>
                <th scope="col" className="num">Total lateness (days)</th><th scope="col" className="num">Max lateness</th>
                <th scope="col" className="num">Waiting (days)</th><th scope="col" className="num">Rule breaks</th><th scope="col">State</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.run_id}>
                  <td>{r.algorithm === "CPSAT" ? "CP-SAT" : "EDF"}</td>
                  <td><code title={r.input_fingerprint}>{r.input_fingerprint.slice(0, 10)}</code></td>
                  <td className="num">{r.metrics.queue_count}</td>
                  <td className="num">{r.metrics.scheduled}</td>
                  <td className="num">{r.metrics.unscheduled}</td>
                  <td className="num">{r.metrics.late_count}</td>
                  <td className="num">{r.metrics.total_lateness}</td>
                  <td className="num">{r.metrics.max_lateness}</td>
                  <td className="num">{r.metrics.total_waiting}</td>
                  <td className="num">{r.metrics.hard_constraint_violations}</td>
                  <td>{r.published ? <Badge tone="ok">Published</Badge> : <Badge tone="info">Proposed</Badge>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

const PUBLISH_CONFLICTS = new Set(["EVC_EXPERT_DOUBLE_BOOKED", "EVC_SLOT_CAPACITY_EXHAUSTED", "EVC_PUBLISH_RECHECK_FAILED"]);

function RunDetail({ who, me, run, setRuns, onChanged }) {
  const [failure, setFailure] = useState(null);
  const [busy, setBusy] = useState(false);
  const key = useActionKey();
  const once = useSingleFlight();
  const m = run.metrics;

  const publish = () => once(async () => {
    const body = { run_id: run.run_id };
    setBusy(true);
    setFailure(null);
    try {
      const out = await api(who, "/evc/schedule:publish", { method: "POST", body, headers: { "Idempotency-Key": key.for(run.run_id) } });
      key.settle(null);
      setRuns((rs) => rs.map((r) => (r.run_id === run.run_id ? { ...r, published: out } : r)));
      onChanged();
    } catch (err) {
      key.settle(err);
      setFailure(err);
    } finally {
      setBusy(false);
    }
  });

  return (
    <section className="card" aria-labelledby="evc-run-title">
      <header className="card-head">
        <h2 id="evc-run-title">{run.algorithm === "CPSAT" ? "CP-SAT" : "EDF"} proposal · {dateIST(run.horizon_start)} to {dateIST(run.horizon_end)}</h2>
        {run.published ? <Badge tone="ok">Published</Badge> : <Badge tone="info">Proposed, not published</Badge>}
      </header>
      <p className="muted small">
        Run reference <code>{run.run_id}</code> · {run.region_scope ? `region ${run.region_scope}` : "all regions"} · made {when(run.created_at)} ·
        panels by the {run.selector_label} <Badge tone="sample">Simulated</Badge>
      </p>
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
              <li key={u.request_id}>Request <code>{short(u.request_id)}</code>: no slot in the window had a full eligible panel. It stays queued.</li>
            ))}
          </ul>
        </div>
      )}
      {run.solver && (
        <details className="solver">
          <summary>Solver details</summary>
          <dl className="facts">
            <dt>Result</dt><dd>{SOLVER_STATUS[run.solver.solver_status] ?? run.solver.solver_status}</dd>
            <dt>Objective / best bound</dt><dd className="num">{run.solver.objective_value} / {run.solver.best_bound}</dd>
            <dt>Candidate slots</dt><dd className="num">{run.solver.candidate_count}</dd>
            <dt>Repair rounds</dt><dd className="num">{run.solver.repair_rounds}</dd>
            <dt>EDF baseline planned</dt><dd className="num">{run.solver.edf_scheduled}</dd>
            <dt>Kept the EDF plan</dt><dd>{run.solver.fallback_to_edf ? "Yes, it scored better" : "No"}</dd>
          </dl>
        </details>
      )}
      {run.published && (
        <p className="ok" role="status">Published {run.published.published_count} visit{run.published.published_count === 1 ? "" : "s"}. The cases' visits can now be completed.</p>
      )}
      {!run.published && PUBLISHERS.has(me.role) && run.proposals.length > 0 && (
        <>
          <ErrorBox error={refusal(failure)} />
          {failure && PUBLISH_CONFLICTS.has(failure.reason) && <p className="muted small">Make a new proposal for the affected requests once the conflict is resolved.</p>}
          <div className="actions">
            <button onClick={publish} disabled={busy}>{busy ? "Publishing…" : "Publish this schedule"}</button>
            <span className="muted small">Every visit is checked again against published visits; any conflict publishes nothing.</span>
          </div>
        </>
      )}
      {!run.published && !PUBLISHERS.has(me.role) && (
        <p className="muted small">Only the bureau publishes a schedule. This proposal holds its experts and slots until then.</p>
      )}
    </section>
  );
}

// A run proposed elsewhere (for example by a regional officer) is published by its reference.
function PublishByReference({ who, setRuns, onChanged }) {
  const [ref, setRef] = useState("");
  const w = usePost(who, onChanged);
  const submit = async (e) => {
    e.preventDefault();
    const out = await w.post("/evc/schedule:publish", { run_id: ref.trim() },
      (x) => `Published ${x.published_count} visit${x.published_count === 1 ? "" : "s"} of run ${short(x.run_id)}.`);
    if (out) setRuns((rs) => rs.map((r) => (r.run_id === out.run_id ? { ...r, published: out } : r)));
  };
  return (
    <Card title="Publish a proposal by reference">
      <form className="inline-form" onSubmit={submit} aria-label="Publish a proposal by reference">
        <label>
          Run reference
          <input value={ref} onChange={(e) => setRef(e.target.value)} required spellCheck={false} autoComplete="off"
            pattern="[0-9a-fA-F\-]{36}" placeholder="The reference shown with the proposal" />
        </label>
        <button className="small" disabled={w.busy}>Publish</button>
      </form>
      <p className="muted small">For a proposal made by someone else, such as a regional officer. Every visit is checked again before anything is published.</p>
      <ErrorBox error={refusal(w.failure)} />
      {w.done && <p className="ok small" role="status">{w.done}</p>}
    </Card>
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
