import { useState } from "react";
import { api } from "../api.js";
import { useActionKey } from "../actionKey.js";
import { sentence } from "../nav.js";
import { deficiencyStateOf, itemLabel, refusal, workflowReasonLabel } from "../workflowText.js";
import { versionOptions } from "./Checklist.jsx";
import { Badge, ErrorBox, useSingleFlight, when } from "./ui.jsx";

// policy.py: reviewing responses uses case.record_deficiency, which only the scrutiny committee holds. This only
// decides what is shown; the server authorises the review.
const REVIEWERS = new Set(["SCRUTINY_COMMITTEE"]);

// Deficiency rounds of a case (GET /cases/{id}/deficiencies): the items asked for, the institution's response to
// each, and, during re-scrutiny, the committee's per-item review (POST .../deficiencies/{round}/review).
export default function Deficiencies({ who, me, caseRec, data, docs, onChanged }) {
  if (!data || data.rounds.length === 0) return null;
  const names = Object.fromEntries(versionOptions(docs).map((o) => [o.id, o.label]));
  const w = data.response_window;
  return (
    <section className="case-zone deficiencies" aria-labelledby={`def-${caseRec.case_id}`}>
      <h3 id={`def-${caseRec.case_id}`}>Deficiencies</h3>
      <p className="muted small">
        Response window {w.value} {sentence(w.unit)} <Badge tone="sample">Demo assumption</Badge> ({w.assumption_code}).
      </p>
      {data.rounds.map((round) => (
        <article key={round.id} className="round" aria-label={`Round ${round.round_no}`}>
          <header className="round-head">
            <strong>Round {round.round_no}</strong>
            <Badge tone={deficiencyStateOf(round.status).tone}>{deficiencyStateOf(round.status).label}</Badge>
            <span className="muted small">opened {when(round.opened_at)}{round.closed_at ? ` · closed ${when(round.closed_at)}` : ""}
              {round.closure_kind === "SUPERSEDED" ? " · carried to the next round" : ""}</span>
          </header>
          <ul className="round-items">
            {round.items.map((item) => (
              <li key={item.id}>
                <span>{itemLabel(item.item_key)}</span>
                <Badge tone={deficiencyStateOf(item.state).tone}>{deficiencyStateOf(item.state).label}</Badge>
                {item.response_ref && <span className="muted small">Response: {names[item.response_ref] ?? "a document of this case"}</span>}
                {item.decision_reason_code && <span className="muted small">{workflowReasonLabel(item.decision_reason_code)}</span>}
              </li>
            ))}
          </ul>
          {round.status === "RESPONDED" && caseRec.stage === "RESCRUTINY" && REVIEWERS.has(me.role) && (
            <Review who={who} caseRec={caseRec} round={round} onChanged={onChanged} />
          )}
        </article>
      ))}
    </section>
  );
}

function Review({ who, caseRec, round, onChanged }) {
  const pending = round.items.filter((i) => i.state === "RESPONDED");
  const [decisions, setDecisions] = useState(() => Object.fromEntries(pending.map((i) => [i.id, "ACCEPTED"])));
  const [failure, setFailure] = useState(null);
  const [busy, setBusy] = useState(false);
  const key = useActionKey();
  const once = useSingleFlight();

  const submit = (e) => {
    e.preventDefault();
    return once(async () => {
      const body = {
        expected_version: caseRec.version,
        decisions: pending.map((i) => ({
          item_id: i.id, state: decisions[i.id],
          reason_code: decisions[i.id] === "ACCEPTED" ? "DEMO_RESPONSE_ACCEPTED" : "DEMO_RESPONSE_REJECTED",
        })),
      };
      setBusy(true);
      setFailure(null);
      try {
        await api(who, `/cases/${caseRec.case_id}/deficiencies/${round.id}/review`, {
          method: "POST", body, headers: { "Idempotency-Key": key.for(JSON.stringify(body)) },
        });
        key.settle(null);
        onChanged?.(caseRec.case_id);
      } catch (err) {
        key.settle(err);
        setFailure(err);
        if (err.reason === "VERSION_CONFLICT") onChanged?.(caseRec.case_id);
      } finally {
        setBusy(false);
      }
    });
  };

  return (
    <form className="action-form review" onSubmit={submit} aria-label={`Review round ${round.round_no}`}>
      <p className="small">Re-scrutiny: decide each response. All accepted closes the round and moves the case on; any not accepted opens a new round for those items.</p>
      {pending.map((i) => (
        <fieldset key={i.id} className="review-item">
          <legend>{itemLabel(i.item_key)}</legend>
          {["ACCEPTED", "REJECTED"].map((state) => (
            <label key={state} className="inline">
              <input type="radio" name={`review-${i.id}`} value={state} checked={decisions[i.id] === state}
                onChange={() => setDecisions((d) => ({ ...d, [i.id]: state }))} />
              {state === "ACCEPTED" ? "Accept the response" : "Not sufficient"}
            </label>
          ))}
        </fieldset>
      ))}
      <ErrorBox error={refusal(failure)} />
      <div className="actions"><button disabled={busy}>{busy ? "Recording…" : "Record the review"}</button></div>
    </form>
  );
}
