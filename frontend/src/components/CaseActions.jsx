import { useEffect, useState } from "react";
import { api } from "../api.js";
import { useActionKey } from "../actionKey.js";
import { ROLE_LABELS, sentence } from "../nav.js";
import {
  DECISION_ACTIONS, LETTER_ACTIONS, actionLabel, itemLabel, reasonText, refusal, workflowReasonLabel,
} from "../workflowText.js";
import { versionOptions, VersionPicker } from "./Checklist.jsx";
import { stageLabel } from "./RouteJourney.jsx";
import { ErrorBox, useSingleFlight } from "./ui.jsx";

// Actions the server needs a reason code for (reason_codes_required) get the ruleset's reason list; the submit
// action is driven by the checklist panel, which collects the items and the DSC flag it needs.
const HANDLED_ELSEWHERE = new Set(["submit"]);

// A Letter of Rejection carries a speaking order (APH cl. 1.10(b)); an appeal may state its grounds. Both are kept as
// protected notes: the ledger holds their hash, never the text.
const NOTE_LABEL = {
  issue_lor: "Speaking order: the specific reasons for rejection (required, stored as a protected note)",
  file_appeal: "Grounds of appeal (optional, stored as a protected note)",
};

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
// The pinned ruleset's deficiency items and reason codes (GET /rulesets/{key}/deficiency-vocabulary). A draft has
// no pinned ruleset yet, and none of its actions needs the vocabulary.
function useVocabulary(who, rulesetKey) {
  const [state, setState] = useState({ data: null, error: null });
  useEffect(() => {
    if (!rulesetKey) return undefined;
    let live = true;
    api(who, `/rulesets/${encodeURIComponent(rulesetKey)}/deficiency-vocabulary`)
      .then((data) => live && setState({ data, error: null }), (error) => live && setState({ data: null, error }));
    return () => { live = false; };
  }, [who, rulesetKey]);
  return state;
}

export default function CaseActions({ who, me, caseRec, application, deficiencies, docs, committees, onChanged }) {
  const [open, setOpen] = useState(null);
  const vocabulary = useVocabulary(who, caseRec.ruleset_key);
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
                    docs={docs} committees={committees} vocabulary={vocabulary} act={act} onDone={() => setOpen(null)} />
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

function ReasonPicker({ value, onChange, required, codes }) {
  return (
    <label>
      Reason{required ? "" : " (optional)"}
      <select value={value} onChange={(e) => onChange(e.target.value)} required={required}>
        <option value="">Choose a reason</option>
        {codes.map((code) => <option key={code} value={code}>{workflowReasonLabel(code)}</option>)}
      </select>
    </label>
  );
}

function ActionForm({ who, action, caseRec, application, deficiencies, docs, committees, vocabulary, act, onDone }) {
  const name = action.action;
  const reasonCodes = vocabulary.data?.reason_codes ?? [];
  const itemKeys = vocabulary.data?.item_keys ?? [];
  const [picked, setPicked] = useState(null);
  // A deficiency usually records missing evidence, so that reason is preselected when the ruleset has it.
  const preset = name === "record_deficiency" ? (reasonCodes.includes("DEMO_MISSING_EVIDENCE") ? "DEMO_MISSING_EVIDENCE" : reasonCodes[0] ?? "") : "";
  const reason = picked ?? preset;
  const setReason = setPicked;
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
    if (DECISION_ACTIONS.has(name)) out.payload = { decision_ref: letter.decision_ref };
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
    && (!LETTER_ACTIONS[name] || (letter.f_no.trim() && letter.decision_ref && application?.academic_year))
    && (!DECISION_ACTIONS.has(name) || letter.decision_ref)
    && (name !== "issue_lor" || note.trim());

  const submit = async (e) => {
    e.preventDefault();
    if (await act.run(name, extra())) onDone();
  };

  return (
    <form className="action-form" onSubmit={submit} aria-label={actionLabel(name)}>
      {name === "record_deficiency" && (
        <fieldset>
          <legend>Items the institution must answer</legend>
          {itemKeys.map((k) => (
            <label key={k} className="inline">
              <input type="checkbox" checked={items.includes(k)}
                onChange={(e) => setItems((s) => (e.target.checked ? [...s, k] : s.filter((x) => x !== k)))} />
              {itemLabel(k)}
            </label>
          ))}
          {!vocabulary.data && !vocabulary.error && <p className="muted small">Loading the ruleset's items…</p>}
          <p className="muted small">Items and reasons are the pinned ruleset's demo vocabulary (DEMO ASSUMPTION); the server validates them.</p>
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
        <LetterFields committees={committees} letter={letter} setLetter={setLetter} application={application} />
      )}
      {DECISION_ACTIONS.has(name) && (
        <fieldset>
          <legend>SAC recommendation</legend>
          <DecisionCited committees={committees} letter={letter} setLetter={setLetter} />
          <p className="muted small">The system records the SAC's recommendation; the Council decides (APH cl. 1.11(d)-(e)).</p>
        </fieldset>
      )}
      {(action.reason_codes_required || ["reject", "withdraw", "revert"].includes(name)) && (
        <>
          <ReasonPicker value={reason} onChange={setReason} required={action.reason_codes_required} codes={reasonCodes} />
          <ErrorBox error={refusal(vocabulary.error)} />
        </>
      )}
      <label>
        {NOTE_LABEL[name] ?? "Note (optional, stored as a protected note)"}
        <textarea rows={name === "issue_lor" ? 4 : 2} value={note} required={name === "issue_lor"}
          onChange={(e) => setNote(e.target.value)} />
      </label>
      <ErrorBox error={refusal(act.failure)} />
      {act.failure && act.retrying(name) && <p className="muted small">Trying again sends the same request, so it cannot be applied twice.</p>}
      <div className="actions">
        <button disabled={!ready || Boolean(act.busy)}>{act.busy === name ? "Working…" : actionLabel(name)}</button>
      </div>
    </form>
  );
}

// A letter cites the committee decision it carries out: the latest report version of a committee on this case
// (GET /cases/{id}/committees lists each committee with its latest report).
function LetterFields({ committees, letter, setLetter, application }) {
  return (
    <fieldset>
      <legend>Letter details</legend>
      <DecisionCited committees={committees} letter={letter} setLetter={setLetter} />
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

function DecisionCited({ committees, letter, setLetter }) {
  const reports = (committees ?? []).filter((c) => c.latest_report);
  return (
    <label>
      Decision cited
      <select value={letter.decision_ref} onChange={(e) => setLetter((l) => ({ ...l, decision_ref: e.target.value }))}>
        <option value="">Choose a committee report</option>
        {reports.map((c) => <option key={c.latest_report.id} value={c.latest_report.id}>
          {sentence(c.type)} committee {c.ordinal} · latest report, version {c.latest_report.version_no}
        </option>)}
      </select>
    </label>
  );
}
