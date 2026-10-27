import World from "../nebula/World.jsx";
import { useRef, useState } from "react";
import { api, newIdempotencyKey } from "../api.js";
import { Icon } from "../components/Icons.jsx";
import { Badge, Card, Empty, ErrorBox, Loading, dateIST, useApi, useSingleFlight, when } from "../components/ui.jsx";
import { ROLE_LABELS, sentence } from "../nav.js";
import { INTERNAL_REF_TITLE, deadlineSource, internalRef } from "../provenance.js";
import {
  LETTER_TYPES, ORIGIN, REASON_CODES, checklistLabel, evidenceStatusOf, explain, isAvailable, letterLabel,
  obligationStatusOf, reasonLabel,
} from "../recordText.js";

// Letters, the obligations they create, and the evidence that meets them (backend/app/compliance).
// An obligation is met only when an officer accepts evidence; registering or acknowledging a letter never is.
const OFFICERS = new Set(["SCRUTINY_COMMITTEE", "RO_OFFICER", "BUREAU_OFFICER", "BUREAU_HEAD"]);
const REGISTRARS = new Set(["BUREAU_OFFICER", "BUREAU_HEAD"]);
const FILTERS = [["", "All"], ["OPEN", "Open"], ["EVIDENCE_SUBMITTED", "Awaiting verification"], ["MET", "Met"]];
// GET /compliance/evidence/{id}/note: officers who may verify and the owning institution. The server narrows this
// further (region, assignment); auditors only learn that a note exists.
const NOTE_READERS = new Set(["INSTITUTION", ...OFFICERS]);
const NOTE_CODES = { NoteIntegrityError: "The stored note does not match the decision's record, so it is not shown. Tell the bureau." };

export default function ComplianceView({ who, me, focusObligation }) {
  const [status, setStatus] = useState("");
  const [openId, setOpenId] = useState(focusObligation ?? null);
  const letters = useApi(who, "/compliance/letters");
  const obligations = useApi(who, `/compliance/obligations${status ? `?status=${status}` : ""}`);
  const refresh = () => { letters.reload(); obligations.reload(); };

  const records = (obligations.data ?? []).map((o) => ({
    id: o.id, label: sentence(o.kind), state: o.status === "MET" ? "checked" : o.status === "OPEN" ? "active" : "unknown",
    date: o.due_date, evidence: o.status === "OPEN" ? null : obligationStatusOf(o.status).label,
    detail: `${o.due_date ? `Due ${dateIST(o.due_date)}` : "No due date"} · ${obligationStatusOf(o.status).label}`,
    facts: [["Case", internalRef(o.application_id)], ["Due", o.due_date ? dateIST(o.due_date) : "Not supplied"],
      ["Status", obligationStatusOf(o.status).label], ["Origin", ORIGIN[o.state_origin] ?? sentence(o.state_origin)]],
  }));

  return (
    <div>
      <World kind="compliance" records={records} onSelect={setOpenId} actionLabel="Open obligation" />
      <Card title="Approval letters" actions={<button className="secondary small" onClick={refresh}><Icon name="refresh" /> Refresh</button>}>
        <LetterTable state={letters} />
        {REGISTRARS.has(me.role) && <RegisterLetter who={who} onRegistered={refresh} />}
      </Card>
      <div className={`grid compliance-layout${openId ? " has-detail" : ""}`}>
        <Card title="Obligations">
          <div className="chips" role="group" aria-label="Show obligations">
            {FILTERS.map(([key, label]) => (
              <button key={key || "all"} className={`chip${status === key ? " on" : ""}`} aria-pressed={status === key} onClick={() => setStatus(key)}>
                {label}
              </button>
            ))}
          </div>
          <ObligationTable state={obligations} openId={openId} onOpen={setOpenId} />
        </Card>
        {openId && (
          <ObligationDetail key={openId} who={who} me={me} id={openId} onClose={() => setOpenId(null)} onChanged={obligations.reload} />
        )}
      </div>
    </div>
  );
}

function LetterTable({ state }) {
  if (state.loading && !state.data) return <Loading what="Loading letters" rows={2} />;
  if (state.error) return <ErrorBox error={state.error} onRetry={state.reload} />;
  if (!state.data) return null;
  if (state.data.length === 0) return <Empty>No approval letters are registered in your scope.</Empty>;
  return (
    <table className="table" tabIndex={0} aria-label="Approval letters">
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
    </table>
  );
}

function ObligationTable({ state, openId, onOpen }) {
  if (state.loading && !state.data) return <Loading what="Loading obligations" />;
  if (state.error) return <ErrorBox error={state.error} onRetry={state.reload} />;
  if (!state.data) return null;
  if (state.data.length === 0) return <Empty>No obligations match.</Empty>;
  return (
    <table className="table" tabIndex={0} aria-label="Obligations">
      <thead>
        <tr><th scope="col">Obligation</th><th scope="col">Case</th><th scope="col">Due</th><th scope="col">Status</th><th scope="col"><span className="sr-only">Open</span></th></tr>
      </thead>
      <tbody>
        {state.data.map((o) => {
          const s = obligationStatusOf(o.status);
          return (
            <tr key={o.id} className={openId === o.id ? "current" : undefined}>
              <td>{sentence(o.kind)}</td>
              <td><code title={INTERNAL_REF_TITLE}>{internalRef(o.application_id)}</code></td>
              <td className="nowrap">{o.due_date ? dateIST(o.due_date) : "No due date"}</td>
              <td><Badge tone={s.tone}>{s.label}</Badge></td>
              <td>
                <button className="secondary small" aria-expanded={openId === o.id} onClick={() => onOpen(openId === o.id ? null : o.id)}
                  aria-label={`${openId === o.id ? "Close" : "Open"} ${sentence(o.kind).toLowerCase()} for case ${internalRef(o.application_id)}`}>
                  {openId === o.id ? "Close" : "Open"}
                </button>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
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
    <aside className="card obligation-detail" aria-label="Obligation detail">
      <header className="card-head">
        <h2>{o ? sentence(o.kind) : "Obligation"}</h2>
        <button className="ghost icon-only" aria-label="Close obligation" onClick={onClose}><Icon name="close" /></button>
      </header>
      {ob.loading && !o && <Loading what="Opening the obligation" rows={4} />}
      <ErrorBox error={ob.error} onRetry={ob.reload} />
      {o && (
        <>
          <dl className="facts">
            <dt>Status</dt><dd><Badge tone={obligationStatusOf(o.status).tone}>{obligationStatusOf(o.status).label}</Badge></dd>
            <dt>Due</dt><dd>{o.due_date ? dateIST(o.due_date) : "No due date"}</dd>
            <dt>Case</dt><dd><code title={INTERNAL_REF_TITLE}>{internalRef(o.application_id)}</code></dd>
            <dt>Source</dt><dd><Badge tone={source.tone}>{source.label}</Badge> <span className="muted small">{source.detail}</span></dd>
            <dt>Origin</dt><dd>{ORIGIN[o.state_origin] ?? sentence(o.state_origin)}</dd>
            {o.met_at && <><dt>Met</dt><dd>{when(o.met_at)}</dd></>}
          </dl>
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
            <EvidencePicker who={who} obligation={o} docs={docs} onSubmitted={changed} />
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
        <p className="muted">
          None of this application's documents has a version that passed the malware scan. Upload one under Documents;
          it can be used here once the scan is clean.
        </p>
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
