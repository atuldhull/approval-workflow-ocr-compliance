import { datePositions } from "../operations/semanticData.js";
import { useRef, useState } from "react";
import { api, newIdempotencyKey } from "../api.js";
import { Icon } from "../components/Icons.jsx";
import { Badge, Card, Empty, ErrorBox, Inspector, Loading, dateIST, useApi, useSingleFlight, when } from "../components/ui.jsx";
import { ROLE_LABELS, sentence } from "../nav.js";
import { INTERNAL_REF_TITLE, deadlineSource, internalRef } from "../provenance.js";
import {
  LETTER_TYPES, OBLIGATION_KINDS, ORIGIN, REASON_CODES, RECORDABLE_RULES, VALIDITY_DOCUMENTS, checklistLabel,
  daysLeftText, evidenceStatusOf, explain, isAvailable, kindLabel, letterLabel, obligationStatusOf, reasonLabel,
  validitySource, validityStateOf,
} from "../recordText.js";

// Letters, the obligations they create, and the evidence that meets them (backend/app/compliance).
// An obligation is met only when an officer accepts evidence; registering or acknowledging a letter never is.
const OFFICERS = new Set(["SCRUTINY_COMMITTEE", "RO_OFFICER", "BUREAU_OFFICER", "BUREAU_HEAD"]);
const REGISTRARS = new Set(["BUREAU_OFFICER", "BUREAU_HEAD"]);
// compliance.validity.record and compliance.obligation.record (backend/app/platform/policy.py)
const RECORDERS = new Set(["RO_OFFICER", "BUREAU_OFFICER", "BUREAU_HEAD"]);
const FILTERS = [["", "All"], ["OPEN", "Open"], ["EVIDENCE_SUBMITTED", "Awaiting verification"], ["MET", "Met"]];
// GET /compliance/evidence/{id}/note: officers who may verify and the owning institution. The server narrows this
// further (region, assignment); auditors only learn that a note exists.
const NOTE_READERS = new Set(["INSTITUTION", ...OFFICERS]);
const NOTE_CODES = { NoteIntegrityError: "The stored note does not match the decision's record, so it is not shown. Tell the bureau." };

export default function ComplianceView({ who, me, focusObligation, onNavigate }) {
  const [status, setStatus] = useState("");
  const [openId, setOpenId] = useState(focusObligation ?? null);
  const letters = useApi(who, "/compliance/letters");
  const obligations = useApi(who, `/compliance/obligations${status ? `?status=${status}` : ""}`);
  const validity = useApi(who, "/compliance/obligations?kind=DOCUMENT_VALIDITY");
  const refresh = () => { letters.reload(); obligations.reload(); validity.reload(); };


  return (
    <div className="compliance">
      <DocumentValidity who={who} me={me} state={validity} openId={openId} onOpen={setOpenId} onNavigate={onNavigate} onChanged={refresh} />
      <ObligationTimeline state={obligations} openId={openId} onOpen={setOpenId} />
      <div className="split compliance-layout">
        <Card title="Obligations" className="split-list"
          actions={<button className="ghost small" onClick={refresh}><Icon name="refresh" /> Refresh</button>}>
          <div className="chips" role="group" aria-label="Show obligations">
            {FILTERS.map(([key, label]) => (
              <button key={key || "all"} className={`chip${status === key ? " on" : ""}`} aria-pressed={status === key} onClick={() => setStatus(key)}>
                {label}
              </button>
            ))}
          </div>
          <ObligationTable state={obligations} openId={openId} onOpen={setOpenId} />
        </Card>
        <div className="split-detail">
          {openId ? (
            <ObligationDetail key={openId} who={who} me={me} id={openId} onClose={() => setOpenId(null)} onChanged={refresh} />
          ) : (
            <div className="card placeholder-case">
              <Empty>Open an obligation to see what it requires, its source, the evidence submitted and what is still unverified.</Empty>
            </div>
          )}
        </div>
      </div>
      {RECORDERS.has(me.role) && (
        <Card title="Record an undertaking" className="record-undertaking">
          <p className="muted small">An undertaking or other obligation stated in a letter or affidavit: its clause, what it asks, the evidence that meets it, and its due date or the official rule that times it.</p>
          <RecordUndertaking who={who} onRecorded={refresh} />
        </Card>
      )}
      <Card title="Approval letters" className="letters">
        <p className="muted small">Each registered letter creates the obligations its rules attach. Registering a letter never meets an obligation.</p>
        <LetterTable state={letters} />
        {REGISTRARS.has(me.role) && <RegisterLetter who={who} onRegistered={refresh} />}
      </Card>
    </div>
  );
}

// ---- document validity (APH cl. 6.17) ----

const VALIDITY_ORDER = { EXPIRED: 0, RENEWAL_UNDER_REVIEW: 1, EXPIRING_SOON: 2, VALID: 3, RENEWED: 4 };

// Lease deeds, completion/occupancy, structural stability and fire safety certificates whose expiry is tracked. A
// record falls due on the document's expiry date; a renewal is a new version of the same document, offered as
// evidence and accepted by an officer once its own expiry date is confirmed.
function DocumentValidity({ who, me, state, openId, onOpen, onNavigate, onChanged }) {
  const [recording, setRecording] = useState(false);
  const tracked = (state.data ?? []).filter((o) => o.kind === "DOCUMENT_VALIDITY");
  const rows = tracked.filter((o) => o.status !== "MET")
    .sort((a, b) => (VALIDITY_ORDER[a.validity_state] ?? 9) - (VALIDITY_ORDER[b.validity_state] ?? 9) || a.valid_until.localeCompare(b.valid_until));
  const renewed = tracked.length - rows.length;
  const institution = me.role === "INSTITUTION";
  return (
    <section className="card validity-panel" aria-labelledby="validity-title">
      <header className="card-head">
        <h2 id="validity-title">Document validity</h2>
        {RECORDERS.has(me.role) && !recording && (
          <button className="secondary small" onClick={() => setRecording(true)}>Record a validity date</button>
        )}
      </header>
      <p className="muted small">
        APH 2024-27 cl. 6.17: the land lease, the occupancy or completion certificate, the structural stability certificate
        and the fire safety certificate must stay valid. Reminders before an expiry (90, 30 and 7 days) and the escalation after it are demo assumptions.
      </p>
      {state.loading && !state.data && <Loading what="Loading validity records" rows={2} />}
      <ErrorBox error={state.error} onRetry={state.reload} />
      {state.data && rows.length === 0 && <Empty>No document validity is being tracked in your scope.</Empty>}
      {rows.length > 0 && (
        <div className="table-wrap"><table className="table" tabIndex={0} aria-label="Document validity">
          <thead>
            <tr>
              <th scope="col">Document</th><th scope="col">Case</th><th scope="col">Valid until</th><th scope="col">Days left</th>
              <th scope="col">State</th><th scope="col">Source</th><th scope="col"><span className="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((o) => {
              const s = validityStateOf(o.validity_state);
              const lease = VALIDITY_DOCUMENTS[o.doc_type]?.lease;
              return (
                <tr key={o.id} className={openId === o.id ? "current" : undefined}>
                  <td>
                    {checklistLabel(o.doc_type)}<span className="muted small"> · v{o.document_version_no ?? "?"}</span>
                    {lease && o.eoa_stop_year && <p className="muted small">No extension of approval from {o.eoa_stop_year} unless the lease is extended (APH cl. 2.1(e))</p>}
                    {lease && o.live_lease_ok === false && <p className="small"><Badge tone="bad">Live lease shorter than the longest course</Badge> APH cl. 6.17(a)</p>}
                  </td>
                  <td><code title={INTERNAL_REF_TITLE}>{internalRef(o.application_id)}</code></td>
                  <td className="nowrap">{dateIST(o.valid_until)}</td>
                  <td className="nowrap num">{daysLeftText(o.days_left)}</td>
                  <td><Badge tone={s.tone}>{s.label}</Badge></td>
                  <td className="small">{validitySource(o)}<span className="muted"> · APH cl. {o.source_clause}</span></td>
                  <td className="actions">
                    {institution && o.status === "OPEN" && onNavigate && (
                      <button className="secondary small" onClick={() => onNavigate("documents", { caseId: o.application_id, docType: o.doc_type })}
                        aria-label={`Upload a renewal of the ${checklistLabel(o.doc_type).toLowerCase()} for case ${internalRef(o.application_id)}`}>
                        Upload renewal
                      </button>
                    )}
                    <button className="ghost small" aria-expanded={openId === o.id} onClick={() => onOpen(openId === o.id ? null : o.id)}
                      aria-label={`${o.validity_state === "RENEWAL_UNDER_REVIEW" && !institution ? "Verify the renewal of" : "Open"} the ${checklistLabel(o.doc_type).toLowerCase()} record for case ${internalRef(o.application_id)}`}>
                      {o.validity_state === "RENEWAL_UNDER_REVIEW" && OFFICERS.has(me.role) ? "Verify renewal" : institution && o.status === "OPEN" ? "Submit renewal" : "Open"}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table></div>
      )}
      {renewed > 0 && <p className="source">{renewed} earlier record{renewed === 1 ? " was" : "s were"} met by an accepted renewal; the older versions stay on file.</p>}
      {recording && <RecordValidity who={who} onDone={() => setRecording(false)} onRecorded={onChanged} />}
    </section>
  );
}

function RecordValidity({ who, onDone, onRecorded }) {
  const apps = useApi(who, "/applications");
  const [appId, setAppId] = useState("");
  const app = apps.data?.find((a) => a.id === appId) ?? apps.data?.[0];
  const docs = useApi(who, app ? `/applications/${app.id}/documents` : null);
  const versions = [];
  for (const d of docs.data ?? []) {
    if (!VALIDITY_DOCUMENTS[d.doc_type]) continue;
    for (const v of d.versions) if (isAvailable(v)) versions.push({ id: v.version_id, doc_type: d.doc_type, label: `${checklistLabel(d.doc_type)} · v${v.version_no} · ${v.original_filename}` });
  }
  const [picked, setPicked] = useState("");
  const version = versions.find((v) => v.id === picked) ?? versions[0];
  const spec = version ? VALIDITY_DOCUMENTS[version.doc_type] : null;
  const [mode, setMode] = useState("valid_until");
  const [day, setDay] = useState("");
  const [years, setYears] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [done, setDone] = useState(null);
  const pendingKey = useRef(null);
  const once = useSingleFlight();
  const usedMode = spec?.period ? mode : "valid_until";
  const edited = (fn) => (e) => { fn(e.target.value); pendingKey.current = null; setDone(null); };

  const submit = (e) => {
    e.preventDefault();
    return once(async () => {
      if (!version || !day) return;
      setBusy(true);
      setError(null);
      pendingKey.current ??= newIdempotencyKey();
      const body = { document_version_id: version.id, [usedMode]: day, ...(spec?.lease && years ? { max_course_duration_years: Number(years) } : {}) };
      try {
        const o = await api(who, "/compliance/validity", { method: "POST", body, headers: { "Idempotency-Key": pendingKey.current } });
        pendingKey.current = null;
        setDone(o);
        onRecorded?.();
      } catch (err) {
        if (err.status && err.status < 500) pendingKey.current = null;
        setError(err);
      } finally {
        setBusy(false);
      }
    });
  };

  return (
    <form onSubmit={submit} className="record-validity" aria-label="Record a validity date">
      <h3>Record a validity date</h3>
      {apps.loading && !apps.data && <Loading what="Loading applications" rows={1} />}
      <ErrorBox error={apps.error} onRetry={apps.reload} />
      {app && (
        <div className="form-grid">
          <label>
            Application
            <select value={app.id} onChange={edited((v) => { setAppId(v); setPicked(""); })}>
              {apps.data.map((a) => <option key={a.id} value={a.id}>{sentence(a.category)} · {a.academic_year} · ref {internalRef(a.id)}</option>)}
            </select>
          </label>
          {docs.loading && !docs.data && <Loading what="Loading documents" rows={1} />}
          {docs.data && versions.length === 0 && <p className="muted">This application has no lease deed, completion, structural stability or fire safety certificate that passed the malware scan.</p>}
          {version && (
            <>
              <label>
                Document version
                <select value={version.id} onChange={edited(setPicked)}>
                  {versions.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
                </select>
              </label>
              {spec?.period && (
                <label>
                  Date read from the certificate
                  <select value={mode} onChange={edited(setMode)}>
                    <option value="valid_until">The date it is valid until</option>
                    <option value="issue_date">Its issue date (valid five years, APH cl. 6.17(h))</option>
                  </select>
                </label>
              )}
              <label>
                {usedMode === "issue_date" ? "Issue date" : "Valid until"}
                <input type="date" value={day} onChange={edited(setDay)} required />
              </label>
              {spec?.lease && (
                <label>
                  Longest course, in years (optional)
                  <input type="number" min={1} max={10} value={years} onChange={edited(setYears)} />
                </label>
              )}
            </>
          )}
        </div>
      )}
      <p className="muted small">Record the date only from the document itself. The record falls due on that date; the institution renews by uploading a new version.</p>
      <ErrorBox error={error} />
      {done && <p className="ok" role="status">Recorded. Valid until {dateIST(done.valid_until)}.</p>}
      <div className="actions">
        <button disabled={!version || !day || busy}>{busy ? "Recording…" : "Record date"}</button>
        <button type="button" className="ghost small" onClick={onDone}>Close</button>
      </div>
    </form>
  );
}

function RecordUndertaking({ who, onRecorded }) {
  const [open, setOpen] = useState(false);
  const apps = useApi(who, open ? "/applications" : null);
  const [form, setForm] = useState({ application_id: "", kind: "UNDERTAKING", title: "", evidence_required: "",
    source_clause: "", timing: "date", due_date: "", rule_id: RECORDABLE_RULES[0][0] });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [done, setDone] = useState(null);
  const pendingKey = useRef(null);
  const once = useSingleFlight();
  const app = apps.data?.find((a) => a.id === form.application_id) ?? apps.data?.[0];
  const set = (field) => (e) => { setForm((f) => ({ ...f, [field]: e.target.value })); pendingKey.current = null; setDone(null); };
  const byDate = form.timing === "date";

  const submit = (e) => {
    e.preventDefault();
    return once(async () => {
      if (!app) return;
      setBusy(true);
      setError(null);
      pendingKey.current ??= newIdempotencyKey();
      const body = {
        application_id: app.id, kind: form.kind, title: form.title.trim(), evidence_required: form.evidence_required.trim(),
        source_clause: form.source_clause.trim() || null,
        ...(byDate ? { due_date: form.due_date } : { rule_id: form.rule_id }),
      };
      try {
        const o = await api(who, "/compliance/obligations", { method: "POST", body, headers: { "Idempotency-Key": pendingKey.current } });
        pendingKey.current = null;
        setDone(o);
        onRecorded?.();
      } catch (err) {
        if (err.status && err.status < 500) pendingKey.current = null;
        setError(err);
      } finally {
        setBusy(false);
      }
    });
  };

  if (!open) return <button className="secondary small register-open" onClick={() => setOpen(true)}>Record an undertaking</button>;
  return (
    <form onSubmit={submit} className="register-letter record-undertaking-form" aria-label="Record an undertaking">
      {apps.loading && !apps.data && <Loading what="Loading applications" rows={1} />}
      <ErrorBox error={apps.error} onRetry={apps.reload} />
      {app && (
        <div className="form-grid">
          <label>
            Application
            <select value={app.id} onChange={set("application_id")}>
              {apps.data.map((a) => <option key={a.id} value={a.id}>{sentence(a.category)} · {a.academic_year} · ref {internalRef(a.id)}</option>)}
            </select>
          </label>
          <label>
            Kind
            <select value={form.kind} onChange={set("kind")}>
              {OBLIGATION_KINDS.filter(([k]) => k !== "DOCUMENT_VALIDITY").map(([k, label]) => <option key={k} value={k}>{label}</option>)}
            </select>
          </label>
          <label>
            What it asks for
            <input value={form.title} onChange={set("title")} maxLength={200} required autoComplete="off" />
          </label>
          <label>
            Evidence that meets it
            <input value={form.evidence_required} onChange={set("evidence_required")} maxLength={500} required autoComplete="off" />
          </label>
          <label>
            Clause it comes from{byDate ? "" : " (optional: the rule's clause is used)"}
            <input value={form.source_clause} onChange={set("source_clause")} maxLength={32} required={byDate}
              pattern="[0-9A-Za-z.()/ \-]{1,32}" placeholder="e.g. 2.25(f)" autoComplete="off" />
          </label>
          <label>
            Timing
            <select value={form.timing} onChange={set("timing")}>
              <option value="date">The due date the undertaking states</option>
              <option value="rule">An official rule, counted from today</option>
            </select>
          </label>
          {byDate ? (
            <label>
              Due date
              <input type="date" value={form.due_date} onChange={set("due_date")} required />
            </label>
          ) : (
            <label>
              Rule
              <select value={form.rule_id} onChange={set("rule_id")}>
                {RECORDABLE_RULES.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
              </select>
            </label>
          )}
        </div>
      )}
      <ErrorBox error={error} />
      {done && <p className="ok" role="status">Recorded. Due {dateIST(done.due_date)}; the institution is reminded before then.</p>}
      <div className="actions">
        <button disabled={!app || busy}>{busy ? "Recording…" : "Record obligation"}</button>
        <button type="button" className="ghost small" onClick={() => setOpen(false)}>Cancel</button>
      </div>
    </form>
  );
}

const TIMELINE_TONE = { MET: "ok", OPEN: "attention", EVIDENCE_SUBMITTED: "info" };
// overdue comes from the obligation's own clock (breached and not met); it is not an obligation status
const toneOf = (o) => (o.overdue ? "bad" : TIMELINE_TONE[o.status] ?? "neutral");

// Markers closer than MIN_GAP percent are pushed apart in date order so each number stays readable; the order and
// the clustering are kept, only the exact spacing gives way.
const MIN_GAP = 2.6;
function spread(positions) {
  const out = [...positions];
  let last = -Infinity;
  out.forEach((p, i) => { if (p !== null) { out[i] = Math.max(p, last + MIN_GAP); last = out[i]; } });
  const over = last - 100;
  if (over > 0) {
    let next = Infinity;
    for (let i = out.length - 1; i >= 0; i--) if (out[i] !== null) { out[i] = Math.min(out[i] - over, next - MIN_GAP); next = out[i]; }
  }
  return out;
}

// Due dates of the listed obligations on one axis, so clustering and order are visible at a glance. Spacing follows
// the dates; an obligation without a due date is counted but not placed. The axis carries one numbered marker per
// date and the obligations are listed under it by the same number, so nearby dates never overlap. Selecting an
// obligation opens it.
function ObligationTimeline({ state, openId, onOpen }) {
  const rows = (state.data ?? []).filter((o) => o.due_date);
  if (!rows.length) return null;
  const sorted = [...rows].sort((a, b) => a.due_date.localeCompare(b.due_date));
  const dates = [...new Set(sorted.map((o) => o.due_date))];
  const positions = spread(datePositions(dates.map((date) => ({ date }))));
  // One marker per date; several obligations due the same day stack above it instead of overlapping.
  const groups = dates.map((date, i) => {
    const items = sorted.filter((o) => o.due_date === date);
    const tone = items.some((o) => o.overdue) ? "bad" : items.some((o) => o.status === "OPEN") ? "attention" : items.some((o) => o.status === "EVIDENCE_SUBMITTED") ? "info" : "ok";
    return { date, items, position: positions[i], tone };
  });
  const undated = (state.data ?? []).length - rows.length;
  return (
    <section className="card obligation-axis" aria-labelledby="axis-title">
      <header className="card-head">
        <h2 id="axis-title">Due dates</h2>
        <span className="muted small">
          {dateIST(sorted[0].due_date)} to {dateIST(sorted.at(-1).due_date)}
          {undated > 0 && ` · ${undated} without a due date`}
        </span>
      </header>
      <div className="axis-track" aria-hidden="true">
        {groups.map((g, i) => g.position !== null && (
          <div key={g.date} className="axis-group" style={{ left: `${g.position}%` }} title={dateIST(g.date)}>
            <span className={`axis-dot tone-${g.tone}`}>{i + 1}</span>
          </div>
        ))}
      </div>
      <ol className="axis-list">
        {groups.map((g, i) => (
          <li key={g.date}>
            <span className={`axis-dot tone-${g.tone}`} aria-hidden="true">{i + 1}</span>
            <span className="axis-date">{dateIST(g.date)}</span>
            <span className="axis-items">
              {g.items.map((o) => (
                <button key={o.id} className={`axis-mark tone-${toneOf(o)}${openId === o.id ? " is-selected" : ""}`}
                  aria-pressed={openId === o.id} onClick={() => onOpen(o.id)}
                  aria-label={`${kindLabel(o.kind)}, case ${internalRef(o.application_id)}, due ${dateIST(o.due_date)}, ${obligationStatusOf(o.status).label}${o.overdue ? ", overdue" : ""}`}>
                  {kindLabel(o.kind)}, case <code>{internalRef(o.application_id)}</code>
                </button>
              ))}
            </span>
          </li>
        ))}
      </ol>
      <ul className="axis-legend" aria-hidden="true">
        <li className="tone-bad">Overdue: due date passed, not met</li>
        <li className="tone-attention">Open: evidence needed</li>
        <li className="tone-info">Evidence submitted, unverified</li>
        <li className="tone-ok">Met</li>
      </ul>
    </section>
  );
}

function LetterTable({ state }) {
  if (state.loading && !state.data) return <Loading what="Loading letters" rows={2} />;
  if (state.error) return <ErrorBox error={state.error} onRetry={state.reload} />;
  if (!state.data) return null;
  if (state.data.length === 0) return <Empty>No approval letters are registered in your scope.</Empty>;
  return (
    <div className="table-wrap"><table className="table" tabIndex={0} aria-label="Approval letters">
      <thead>
        <tr>
          <th scope="col">Letter</th><th scope="col">Case</th><th scope="col">Year</th><th scope="col">Issued</th>
          <th scope="col">Letter number</th><th scope="col">Valid until</th><th scope="col">Obligations</th>
        </tr>
      </thead>
      <tbody>
        {state.data.map((l) => (
          <tr key={l.id}>
            <td>{letterLabel(l.letter_type)}{l.lists_deficiencies && <> <Badge tone="warn">Lists deficiencies</Badge></>}</td>
            <td><code title={INTERNAL_REF_TITLE}>{internalRef(l.application_id)}</code></td>
            <td>{l.academic_year}</td>
            <td>{dateIST(l.issue_date)}<span className="muted small"> · {l.issue_date_source === "PORTAL_EVENT" ? "from the portal record" : "from a confirmed fact"}</span></td>
            <td>{l.f_no ?? "—"}</td>
            <td>{l.valid_until ? dateIST(l.valid_until) : "—"}</td>
            <td className="num">{l.obligation_ids.length}</td>
          </tr>
        ))}
      </tbody>
    </table></div>
  );
}

function ObligationTable({ state, openId, onOpen }) {
  if (state.loading && !state.data) return <Loading what="Loading obligations" />;
  if (state.error) return <ErrorBox error={state.error} onRetry={state.reload} />;
  if (!state.data) return null;
  if (state.data.length === 0) return <Empty>No obligations match.</Empty>;
  return (
    <div className="table-wrap"><table className="table" tabIndex={0} aria-label="Obligations">
      <thead>
        <tr><th scope="col">Obligation</th><th scope="col">Case</th><th scope="col">Due</th><th scope="col">Status</th><th scope="col">Evidence</th><th scope="col"><span className="sr-only">Open</span></th></tr>
      </thead>
      <tbody>
        {state.data.map((o) => {
          const s = obligationStatusOf(o.status);
          return (
            <tr key={o.id} className={openId === o.id ? "current" : undefined}>
              <td>{kindLabel(o.kind)}{(o.title || o.doc_type) && <span className="muted small"> · {o.title ?? checklistLabel(o.doc_type)}</span>}</td>
              <td><code title={INTERNAL_REF_TITLE}>{internalRef(o.application_id)}</code></td>
              <td className="nowrap">{o.due_date ? dateIST(o.due_date) : "No due date"}</td>
              <td><Badge tone={s.tone}>{s.label}</Badge>{o.overdue && <> <Badge tone="bad">Overdue</Badge></>}</td>
              <td className="small">{evidenceSummary(o.evidence)}</td>
              <td>
                <button className="secondary small" aria-expanded={openId === o.id} onClick={() => onOpen(openId === o.id ? null : o.id)}
                  aria-label={`${openId === o.id ? "Close" : "Open"} ${kindLabel(o.kind).toLowerCase()} for case ${internalRef(o.application_id)}`}>
                  {openId === o.id ? "Close" : "Open"}
                </button>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table></div>
  );
}

// What the evidence on an obligation amounts to, in a few words: nothing yet, waiting for an officer, or decided.
function evidenceSummary(evidence) {
  if (!evidence?.length) return <span className="muted">None submitted</span>;
  const waiting = evidence.filter((e) => e.status === "SUBMITTED").length;
  const accepted = evidence.filter((e) => e.status === "ACCEPTED").length;
  if (waiting) return <span className="unverified">{waiting} unverified</span>;
  if (accepted) return <span className="ok">{accepted} accepted</span>;
  return <span className="muted">{evidence.length} rejected</span>;
}

function versionNames(docs) {
  const names = {};
  for (const d of docs ?? []) for (const v of d.versions) names[v.version_id] = `${checklistLabel(d.doc_type)} · v${v.version_no} · ${v.original_filename}`;
  return names;
}

function ObligationDetail({ who, me, id, onClose, onChanged }) {
  const ob = useApi(who, `/compliance/obligations/${id}`);
  const docs = useApi(who, ob.data ? `/applications/${ob.data.application_id}/documents` : null);
  const changed = () => { ob.reload(); docs.reload(); onChanged?.(); };
  const o = ob.data;
  const names = versionNames(docs.data);
  const source = o && deadlineSource({ source_status: o.source_status, clause: o.source_clause });

  return (
    <aside className="card inspector obligation-detail" aria-label="Obligation detail">
      <header className="card-head">
        <h2>{o ? kindLabel(o.kind) : "Obligation"}</h2>
        <button className="ghost icon-only" aria-label="Close obligation" onClick={onClose}><Icon name="close" /></button>
      </header>
      {ob.loading && !o && <Loading what="Opening the obligation" rows={4} />}
      <ErrorBox error={ob.error} onRetry={ob.reload} />
      {o && (
        <>
          <dl className="facts">
            <dt>Status</dt><dd><Badge tone={obligationStatusOf(o.status).tone}>{obligationStatusOf(o.status).label}</Badge></dd>
            <dt>Due</dt><dd>{o.due_date ? dateIST(o.due_date) : "No due date"}{o.overdue && <> <Badge tone="bad">Overdue</Badge></>}</dd>
            <dt>Case</dt><dd><code title={INTERNAL_REF_TITLE}>{internalRef(o.application_id)}</code></dd>
            <dt>Source</dt><dd><Badge tone={source.tone}>{source.label}</Badge> <span className="muted small">{source.detail}</span></dd>
            <dt>Origin</dt><dd>{ORIGIN[o.state_origin] ?? sentence(o.state_origin)}</dd>
            {o.met_at && <><dt>Met</dt><dd>{when(o.met_at)}</dd></>}
            {o.title && <><dt>Asks for</dt><dd>{o.title}</dd></>}
            {o.evidence_required && <><dt>Evidence</dt><dd>{o.evidence_required}</dd></>}
            {o.valid_until && (
              <>
                <dt>Document</dt><dd>{checklistLabel(o.doc_type)} · v{o.document_version_no ?? "?"}</dd>
                <dt>Valid until</dt><dd>{dateIST(o.valid_until)} <Badge tone={validityStateOf(o.validity_state).tone}>{validityStateOf(o.validity_state).label}</Badge> <span className="muted small">{daysLeftText(o.days_left)}</span></dd>
                <dt>Date from</dt><dd>{validitySource(o)}</dd>
                {o.eoa_stop_year && <><dt>EoA stop year</dt><dd>{o.eoa_stop_year} <span className="muted small">no extension of approval from this academic year unless the lease is extended (APH cl. 2.1(e))</span></dd></>}
              </>
            )}
          </dl>
          {o.penalty_notes?.length > 0 && (
            <div className="penalty-notes" role="note" aria-label="Penalty notes for the competent authority">
              <h3>Penalty notes</h3>
              <ul>{o.penalty_notes.map((n) => <li key={n} className="small">{n}</li>)}</ul>
            </div>
          )}
          {o.kind === "DOCUMENT_VALIDITY" && o.status !== "MET" && (
            <p className="muted small">
              Renewal: the institution uploads a new version of this document and submits it here. Officers confirm its expiry date
              under fact review; accepting it meets this record and opens the next one from that date.
            </p>
          )}
          <ol className="obligation-flow" aria-label="Who does what">
            <li className={o.evidence.length ? "done" : "now"}><strong>Institution</strong> submits a scanned-clean document version as evidence</li>
            <li className={o.status === "EVIDENCE_SUBMITTED" ? "now" : o.status === "MET" ? "done" : undefined}><strong>Officer</strong> accepts or rejects it</li>
            <li className={o.status === "MET" ? "done" : undefined}><strong>Met</strong> only when an officer accepts</li>
          </ol>
          <h3>Evidence</h3>
          {o.evidence.length === 0 ? <p className="muted">No evidence has been submitted.</p> : (
            <ul className="evidence-list">
              {o.evidence.map((e) => (
                <li key={e.id} className="evidence">
                  <p>
                    <strong>{names[e.document_version_id] ?? `Document version ${internalRef(e.document_version_id)}`}</strong>{" "}
                    <Badge tone={evidenceStatusOf(e.status).tone}>{evidenceStatusOf(e.status).label}</Badge>
                  </p>
                  <p className="muted small">
                    Submitted {when(e.submitted_at)}
                    {e.verified_at && <> · decided {when(e.verified_at)} by the {(ROLE_LABELS[e.verified_role] ?? sentence(e.verified_role)).toLowerCase()}</>}
                    {e.reason_code && <> · reason: {reasonLabel(e.reason_code)}</>}
                    {e.has_note && !NOTE_READERS.has(me.role) && <> · a note is on file (only the verifying officers and the institution can read it)</>}
                  </p>
                  {e.has_note && NOTE_READERS.has(me.role) && <EvidenceNote who={who} evidenceId={e.id} />}
                  {OFFICERS.has(me.role) && e.status === "SUBMITTED" && <VerifyEvidence who={who} evidence={e} onVerified={changed} />}
                </li>
              ))}
            </ul>
          )}
          {me.role === "INSTITUTION" && o.status === "OPEN" && (
            <EvidencePicker who={who} obligation={o} docs={renewalsOnly(docs, o)} onSubmitted={changed} />
          )}
          {me.role === "INSTITUTION" && o.status === "EVIDENCE_SUBMITTED" && (
            <p className="muted small">Your evidence is with an officer. You can submit again only if it is rejected.</p>
          )}
          {me.role === "AUDITOR" && <p className="muted small" role="note">Read-only: auditors can see decisions but not make them.</p>}
        </>
      )}
    </aside>
  );
}

// A validity record is met only by a newer version of the same document (its renewal).
function renewalsOnly(docs, o) {
  if (!o.document_id || !docs.data) return docs;
  const data = docs.data.filter((d) => d.document_id === o.document_id)
    .map((d) => ({ ...d, versions: d.versions.filter((v) => v.version_id !== o.document_version_id) }));
  return { ...docs, data };
}

// Only versions whose status is AVAILABLE (scanned clean) can be evidence.
export function availableVersions(docs, alreadySubmitted = []) {
  const used = new Set(alreadySubmitted);
  const out = [];
  for (const d of docs ?? []) {
    for (const v of d.versions) {
      if (isAvailable(v) && !used.has(v.version_id)) {
        out.push({ id: v.version_id, label: `${checklistLabel(d.doc_type)} · v${v.version_no} · ${v.original_filename}` });
      }
    }
  }
  return out;
}

function EvidencePicker({ who, obligation, docs, onSubmitted }) {
  const options = availableVersions(docs.data, obligation.evidence.map((e) => e.document_version_id));
  const [picked, setPicked] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const pendingKey = useRef(null);
  const once = useSingleFlight();
  const chosen = picked || options[0]?.id || "";

  const submit = (e) => {
    e.preventDefault();
    return once(async () => {
      if (!chosen) return;
      setBusy(true);
      setError(null);
      pendingKey.current ??= newIdempotencyKey();
      try {
        await api(who, `/compliance/obligations/${obligation.id}/evidence`, {
          method: "POST", body: { document_version_id: chosen }, headers: { "Idempotency-Key": pendingKey.current },
        });
        pendingKey.current = null;
        onSubmitted?.();
      } catch (err) {
        if (err.status && err.status < 500) pendingKey.current = null;
        setError(err);
      } finally {
        setBusy(false);
      }
    });
  };

  if (docs.loading && !docs.data) return <Loading what="Loading your documents" rows={2} />;
  if (docs.error) return <ErrorBox error={docs.error} onRetry={docs.reload} />;
  return (
    <form onSubmit={submit} className="evidence-picker" aria-label="Submit evidence">
      <h3>Submit evidence</h3>
      {options.length === 0 ? (
        obligation.document_id ? (
          <p className="muted">
            No new version of this document has passed the malware scan yet. Upload the renewal under Documents; it can be
            submitted here once the scan is clean.
          </p>
        ) : (
          <p className="muted">
            None of this application's documents has a version that passed the malware scan. Upload one under Documents;
            it can be used here once the scan is clean.
          </p>
        )
      ) : (
        <>
          <label>
            Document version
            <select value={chosen} onChange={(e) => { setPicked(e.target.value); pendingKey.current = null; }}>
              {options.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
            </select>
          </label>
          <p className="muted small">Only versions that passed the malware scan are listed. An officer decides whether it meets the obligation.</p>
          <ErrorBox error={error} />
          <button disabled={busy}>{busy ? "Submitting…" : "Submit as evidence"}</button>
        </>
      )}
    </form>
  );
}

// The verifier's note, fetched only when asked for. A redacted note says so instead of showing nothing.
export function EvidenceNote({ who, evidenceId }) {
  const [open, setOpen] = useState(false);
  const note = useApi(who, open ? `/compliance/evidence/${evidenceId}/note` : null);
  const d = note.data;
  return (
    <div className="evidence-note">
      <button type="button" className="ghost small" aria-expanded={open} onClick={() => setOpen(!open)}>
        {open ? "Hide the officer's note" : "Read the officer's note"}
      </button>
      {open && note.loading && !d && <Loading what="Loading the note" rows={1} />}
      {open && <ErrorBox error={explain(note.error, {}, NOTE_CODES)} onRetry={note.reload} />}
      {open && d && (
        d.redacted ? <p className="muted small" role="note">This note has been redacted; its text is no longer kept.</p>
          : d.has_note && d.note != null ? <blockquote className="note-text">{d.note}</blockquote>
            : <p className="muted small">No note was left with this decision.</p>
      )}
    </div>
  );
}

function VerifyEvidence({ who, evidence, onVerified }) {
  const [decision, setDecision] = useState("ACCEPTED");
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const pendingKey = useRef(null);
  const once = useSingleFlight();
  const edited = (fn) => (e) => { fn(e.target.value); pendingKey.current = null; };
  const needsNote = decision === "REJECTED" && reason === "OTHER_SEE_NOTE";
  const valid = decision === "ACCEPTED" || (reason && (!needsNote || note.trim()));
  const name = `verify-${evidence.id}`;

  const submit = (e) => {
    e.preventDefault();
    return once(async () => {
      if (!valid) return;
      setBusy(true);
      setError(null);
      pendingKey.current ??= newIdempotencyKey();
      const body = { decision, ...(decision === "REJECTED" ? { reason_code: reason } : {}), ...(note.trim() ? { note: note.trim() } : {}) };
      try {
        await api(who, `/compliance/evidence/${evidence.id}/verify`, { method: "POST", body, headers: { "Idempotency-Key": pendingKey.current } });
        pendingKey.current = null;
        onVerified?.();
      } catch (err) {
        if (err.status && err.status < 500) pendingKey.current = null;
        setError(err);
      } finally {
        setBusy(false);
      }
    });
  };

  return (
    <form onSubmit={submit} className="verify-evidence" aria-label="Verify this evidence">
      <div role="radiogroup" aria-label="Decision" className="choice">
        <label className="inline">
          <input type="radio" name={name} value="ACCEPTED" checked={decision === "ACCEPTED"} onChange={edited(setDecision)} />
          Accept: it meets the obligation
        </label>
        <label className="inline">
          <input type="radio" name={name} value="REJECTED" checked={decision === "REJECTED"} onChange={edited(setDecision)} />
          Reject
        </label>
      </div>
      {decision === "REJECTED" && (
        <label>
          Reason
          <select value={reason} onChange={edited(setReason)} required>
            <option value="">Choose a reason…</option>
            {REASON_CODES.map(([code, label]) => <option key={code} value={code}>{label}</option>)}
          </select>
        </label>
      )}
      <label>
        Note {needsNote ? "(required for this reason)" : "(optional)"}
        <textarea value={note} onChange={edited(setNote)} rows={2} maxLength={4000} required={needsNote} />
      </label>
      <ErrorBox error={error} />
      <button disabled={!valid || busy}>{busy ? "Saving…" : "Record decision"}</button>
    </form>
  );
}

function RegisterLetter({ who, onRegistered }) {
  const [open, setOpen] = useState(false);
  const apps = useApi(who, open ? "/applications" : null);
  const [form, setForm] = useState({ application_id: "", letter_type: "LOA", academic_year: "", issue_date: "",
    issue_date_source: "PORTAL_EVENT", f_no: "", issue_date_fact_id: "", document_version_id: "", lists_deficiencies: false });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [done, setDone] = useState(null);
  const pendingKey = useRef(null);
  const once = useSingleFlight();
  const app = apps.data?.find((a) => a.id === form.application_id) ?? apps.data?.[0];
  const set = (field) => (e) => {
    const value = e.target.type === "checkbox" ? e.target.checked : e.target.value;
    setForm((f) => ({ ...f, [field]: value }));
    pendingKey.current = null;
    setDone(null);
  };

  const submit = (e) => {
    e.preventDefault();
    return once(async () => {
      if (!app) return;
      setBusy(true);
      setError(null);
      pendingKey.current ??= newIdempotencyKey();
      const portal = form.issue_date_source === "PORTAL_EVENT";
      const body = {
        application_id: app.id, institution_id: app.institution_id, letter_type: form.letter_type,
        academic_year: form.academic_year || app.academic_year, issue_date: form.issue_date,
        issue_date_source: form.issue_date_source, lists_deficiencies: form.lists_deficiencies,
        f_no: form.f_no.trim() || null,
        issue_date_fact_id: portal ? null : form.issue_date_fact_id.trim() || null,
        document_version_id: portal ? null : form.document_version_id.trim() || null,
      };
      try {
        const letter = await api(who, "/compliance/letters", { method: "POST", body, headers: { "Idempotency-Key": pendingKey.current } });
        pendingKey.current = null;
        setDone(letter);
        onRegistered?.();
      } catch (err) {
        if (err.status && err.status < 500) pendingKey.current = null;
        setError(err);
      } finally {
        setBusy(false);
      }
    });
  };

  if (!open) {
    return <button className="secondary small register-open" onClick={() => setOpen(true)}>Register a letter</button>;
  }
  return (
    <form onSubmit={submit} className="register-letter" aria-label="Register an approval letter">
      <h3>Register an approval letter</h3>
      {apps.loading && !apps.data && <Loading what="Loading applications" rows={1} />}
      <ErrorBox error={apps.error} onRetry={apps.reload} />
      {apps.data?.length === 0 && <p className="muted">There are no applications to register a letter against.</p>}
      {app && (
        <div className="form-grid">
          <label>
            Application
            <select value={app.id} onChange={set("application_id")}>
              {apps.data.map((a) => <option key={a.id} value={a.id}>{sentence(a.category)} · {a.academic_year} · ref {internalRef(a.id)}</option>)}
            </select>
          </label>
          <label>
            Letter
            <select value={form.letter_type} onChange={set("letter_type")}>
              {LETTER_TYPES.map(([code, label]) => <option key={code} value={code}>{label}</option>)}
            </select>
          </label>
          <label>
            Academic year
            <input value={form.academic_year} placeholder={app.academic_year} onChange={set("academic_year")} pattern="[0-9]{4}-[0-9]{2}" autoComplete="off" />
          </label>
          <label>
            Issue date
            <input type="date" value={form.issue_date} onChange={set("issue_date")} required />
          </label>
          <label>
            Where the issue date comes from
            <select value={form.issue_date_source} onChange={set("issue_date_source")}>
              <option value="PORTAL_EVENT">The portal record (needs the letter number)</option>
              <option value="CONFIRMED_FACT">A fact an officer confirmed from the letter</option>
            </select>
          </label>
          <label>
            Letter number (F. No.)
            <input value={form.f_no} onChange={set("f_no")} maxLength={100} required={form.issue_date_source === "PORTAL_EVENT"} autoComplete="off" />
          </label>
          {form.issue_date_source === "CONFIRMED_FACT" && (
            <>
              <label>
                Confirmed issue-date fact id
                <input value={form.issue_date_fact_id} onChange={set("issue_date_fact_id")} required autoComplete="off" spellCheck={false} />
              </label>
              <label>
                Letter's document version id
                <input value={form.document_version_id} onChange={set("document_version_id")} autoComplete="off" spellCheck={false} />
              </label>
            </>
          )}
          <label className="inline">
            <input type="checkbox" checked={form.lists_deficiencies} onChange={set("lists_deficiencies")} />
            The letter lists deficiencies
          </label>
        </div>
      )}
      <p className="muted small">Registering records this system's copy of a letter issued on the AICTE portal. It creates the obligations the rules attach to that letter type.</p>
      <ErrorBox error={error} />
      {done && <p className="ok" role="status">Registered. {done.obligation_ids.length} obligation{done.obligation_ids.length === 1 ? "" : "s"} created.</p>}
      <div className="actions">
        <button disabled={!app || busy}>{busy ? "Registering…" : "Register letter"}</button>
        <button type="button" className="ghost small" onClick={() => setOpen(false)}>Cancel</button>
      </div>
    </form>
  );
}
