import { useEffect, useState } from "react";
import { api } from "../api.js";
import { useActionKey } from "../actionKey.js";
import { ROLE_LABELS, sentence } from "../nav.js";
import {
  DEFICIENCY_ITEM_KEYS, LETTER_ACTIONS, WORKFLOW_REASONS, actionLabel, itemLabel, reasonText, refusal,
} from "../workflowText.js";
import { versionOptions, VersionPicker } from "./Checklist.jsx";
import { stageLabel } from "./RouteJourney.jsx";
import { ErrorBox, useSingleFlight } from "./ui.jsx";

// Actions the server needs a reason code for (reason_codes_required) get the ruleset's reason list; the submit
// action is driven by the checklist panel, which collects the items and the DSC flag it needs.
const HANDLED_ELSEWHERE = new Set(["submit"]);

const todayIST = () => new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(new Date());

// POST /cases/{id}/actions with the case's expected_version and one Idempotency-Key per user action. A retry of
// the same action (same body) reuses the key; a version conflict reloads the case.
export function useCaseAction(who, caseRec, onChanged) {
  const key = useActionKey();
  const [failure, setFailure] = useState(null);
  const [busy, setBusy] = useState(null);
  const once = useSingleFlight();
  const run = (action, extra = {}) => once(async () => {
    const body = { action, expected_version: caseRec.version, ...extra };
    setBusy(action);
    setFailure(null);
    try {
      await api(who, `/cases/${caseRec.case_id}/actions`, {
        method: "POST", body, headers: { "Idempotency-Key": key.for(JSON.stringify(body)) },
      });
      key.settle(null);
      onChanged?.(caseRec.case_id);
      return true;
    } catch (e) {
      key.settle(e);
      setFailure(e);
      if (e.reason === "VERSION_CONFLICT") onChanged?.(caseRec.case_id, { keepMessage: true });
      return false;
    } finally {
      setBusy(null);
    }
  });
  return { run, failure, busy, retrying: (action) => failure && key.pending() && busy !== action, clear: () => setFailure(null) };
}

// The actions the server lists for the signed-in role at the case's current stage, each enabled or with the
// guard's reason. Nothing is derived on the client: an action not in available_actions is not offered.
export default function CaseActions({ who, me, caseRec, application, deficiencies, docs, committeeIds, onChanged }) {
  const [open, setOpen] = useState(null);
  const act = useCaseAction(who, caseRec, onChanged);
  const listed = (caseRec.available_actions ?? []).filter((a) => !HANDLED_ELSEWHERE.has(a.action));
  const where = caseRec.stage ? stageLabel(caseRec.stage) : caseRec.status === "DRAFT" ? "draft" : "the end of the route";

  return (
    <section className="case-zone case-actions" aria-labelledby={`act-${caseRec.case_id}`}>
      <h3 id={`act-${caseRec.case_id}`}>What you can do now</h3>
      <p className="muted small">
        As {ROLE_LABELS[me.role] ?? me.role}, at {where}. Case version <span className="num">{caseRec.version}</span>; the server checks every
        rule again when you act.
      </p>
      {listed.length === 0 && <p className="muted">No actions for your role at this stage.</p>}
      {[["enabled", listed.filter((a) => a.enabled)], ["blocked", listed.filter((a) => !a.enabled)]].map(([group, actions]) => {
        if (!actions.length) return null;
        const list = (
          <ul className="action-list">
            {actions.map((a) => (
              <li key={a.action} className={`action-row${a.enabled ? "" : " blocked"}`}>
                <div className="action-head">
                  <strong>{actionLabel(a.action)}</strong>
                  {a.targets?.length > 0 && <span className="muted small">to {a.targets.map(stageLabel).join(" or ")}</span>}
                  {a.enabled && (
                    <button type="button" className="small secondary" aria-expanded={open === a.action}
                      onClick={() => { setOpen(open === a.action ? null : a.action); act.clear(); }}>
                      {open === a.action ? "Close" : "Open"}
                    </button>
                  )}
                </div>
                {!a.enabled && <p className="small action-reason">{reasonText(a.reason_code)}</p>}
                {a.enabled && open === a.action && (
                  <ActionForm who={who} action={a} caseRec={caseRec} application={application} deficiencies={deficiencies}
                    docs={docs} committeeIds={committeeIds} act={act} onDone={() => setOpen(null)} />
                )}
              </li>
            ))}
          </ul>
        );
        // Blocked actions stay listed with their reason, folded away when something can be done now.
        return group === "enabled" ? <div key={group}>{list}</div> : (
          <details key={group} className="action-blocked" open={!listed.some((a) => a.enabled)}>
            <summary>Not available now ({actions.length})</summary>
            {list}
          </details>
        );
      })}
      {!open && <ErrorBox error={refusal(act.failure)} />}
    </section>
  );
}

function ReasonPicker({ value, onChange, required }) {
  return (
    <label>
      Reason{required ? "" : " (optional)"}
      <select value={value} onChange={(e) => onChange(e.target.value)} required={required}>
        <option value="">Choose a reason</option>
        {WORKFLOW_REASONS.map(([code, label]) => <option key={code} value={code}>{label}</option>)}
      </select>
    </label>
  );
}

function ActionForm({ who, action, caseRec, application, deficiencies, docs, committeeIds, act, onDone }) {
  const name = action.action;
  const [reason, setReason] = useState(name === "record_deficiency" ? "DEMO_MISSING_EVIDENCE" : "");
  const [note, setNote] = useState("");
  const [items, setItems] = useState([]);
  const [target, setTarget] = useState(action.targets?.[0] ?? "");
  const [responses, setResponses] = useState({});
  const [letter, setLetter] = useState({ f_no: "", decision_ref: "" });
  const options = versionOptions(docs);
  const round = deficiencies?.rounds?.findLast?.((r) => r.status === "OPEN") ?? null;
  const openItems = round ? round.items.filter((i) => i.state === "OPEN") : [];

  const extra = () => {
    const out = {};
    if (reason) out.reason_code = reason;
    if (note.trim()) out.note = note.trim();
    if (name === "record_deficiency") out.payload = { item_keys: [...items].sort() };
    if (name === "submit_compliance") out.payload = { responses: openItems.map((i) => ({ item_id: i.id, response_ref: responses[i.id] })) };
    if (name === "revert") out.payload = { target_stage: target };
    if (LETTER_ACTIONS[name]) {
      out.payload = {
        decision_ref: letter.decision_ref,
        letter: {
          type: LETTER_ACTIONS[name], academic_year: application?.academic_year, issue_date: todayIST(),
          issue_date_source: "PORTAL_EVENT", lists_deficiencies: false, f_no: letter.f_no.trim(),
        },
      };
    }
    return out;
  };

  const ready = (!action.reason_codes_required || reason)
    && (name !== "record_deficiency" || items.length > 0)
    && (name !== "submit_compliance" || (openItems.length > 0 && openItems.every((i) => responses[i.id])))
    && (name !== "revert" || target)
    && (!LETTER_ACTIONS[name] || (letter.f_no.trim() && letter.decision_ref && application?.academic_year));

  const submit = async (e) => {
    e.preventDefault();
    if (await act.run(name, extra())) onDone();
  };

  return (
    <form className="action-form" onSubmit={submit} aria-label={actionLabel(name)}>
      {name === "record_deficiency" && (
        <fieldset>
          <legend>Items the institution must answer</legend>
          {DEFICIENCY_ITEM_KEYS.map((k) => (
            <label key={k} className="inline">
              <input type="checkbox" checked={items.includes(k)}
                onChange={(e) => setItems((s) => (e.target.checked ? [...s, k] : s.filter((x) => x !== k)))} />
              {itemLabel(k)}
            </label>
          ))}
          <p className="muted small">Item list and reasons are the ruleset's demo vocabulary (DEMO ASSUMPTION); the server validates them.</p>
        </fieldset>
      )}
      {name === "submit_compliance" && (
        <fieldset>
          <legend>Answer each open item with one of your documents</legend>
          {openItems.length === 0 && <p className="muted small">No open deficiency items were found.</p>}
          {openItems.map((i) => (
            <label key={i.id}>
              {itemLabel(i.item_key)}
              <VersionPicker value={responses[i.id] ?? null} options={options} preferType={i.item_key} label={`Response for ${itemLabel(i.item_key)}`}
                onChange={(v) => setResponses((r) => ({ ...r, [i.id]: v }))} />
            </label>
          ))}
          {options.every((o) => !o.available) && <p className="muted small">Upload the response documents under My documents first.</p>}
        </fieldset>
      )}
      {name === "revert" && (
        <label>
          Send back to
          <select value={target} onChange={(e) => setTarget(e.target.value)}>
            {(action.targets ?? []).map((t) => <option key={t} value={t}>{stageLabel(t)}</option>)}
          </select>
        </label>
      )}
      {LETTER_ACTIONS[name] && (
        <LetterFields who={who} committeeIds={committeeIds} letter={letter} setLetter={setLetter} application={application} />
      )}
      {(action.reason_codes_required || ["reject", "withdraw", "revert"].includes(name)) && (
        <ReasonPicker value={reason} onChange={setReason} required={action.reason_codes_required} />
      )}
      <label>
        Note (optional, stored as a protected note)
        <textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
      </label>
      <ErrorBox error={refusal(act.failure)} />
      {act.failure && act.retrying(name) && <p className="muted small">Trying again sends the same request, so it cannot be applied twice.</p>}
      <div className="actions">
        <button disabled={!ready || Boolean(act.busy)}>{act.busy === name ? "Working…" : actionLabel(name)}</button>
      </div>
    </form>
  );
}

// A letter cites the committee decision it carries out: the latest report version of a committee on this case.
function LetterFields({ who, committeeIds, letter, setLetter, application }) {
  const [reports, setReports] = useState(null);
  useEffect(() => {
    let live = true;
    Promise.all((committeeIds ?? []).map((id) => Promise.all([
      api(who, `/committees/${id}`).catch(() => null), api(who, `/committees/${id}/reports`).catch(() => []),
    ]))).then((all) => live && setReports(all
      .map(([c, rs]) => (rs.length ? { ...rs[rs.length - 1], committee: c } : null)).filter(Boolean)));
    return () => { live = false; };
  }, [who, committeeIds]);
  return (
    <fieldset>
      <legend>Letter details</legend>
      <label>
        Decision cited
        <select value={letter.decision_ref} onChange={(e) => setLetter((l) => ({ ...l, decision_ref: e.target.value }))}>
          <option value="">Choose a committee report</option>
          {(reports ?? []).map((r) => <option key={r.id} value={r.id}>
            {r.committee ? `${sentence(r.committee.type)} committee` : `Committee ${r.committee_id.slice(0, 8)}`} · latest report, version {r.version_no}
          </option>)}
        </select>
      </label>
      <label>
        Letter number (F. No.)
        <input value={letter.f_no} maxLength={100} autoComplete="off" onChange={(e) => setLetter((l) => ({ ...l, f_no: e.target.value }))} />
      </label>
      <p className="muted small">
        Academic year {application?.academic_year ?? "not available"}; issue date is today (IST), as the portal event records it.
      </p>
    </fieldset>
  );
}
