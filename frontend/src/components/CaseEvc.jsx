import { useEffect, useState } from "react";
import { api } from "../api.js";
import { evcStatusOf, refusal, slotPartLabel } from "../workflowText.js";
import { Badge, ErrorBox, dateIST, when } from "./ui.jsx";

const short = (id) => String(id).slice(0, 8);

// The expert-visit request(s) of one case from GET /applications/{id}/evc, scoped like the case itself. The
// published visit (date, half-day and panel references) is shown once the bureau has published it.
export default function CaseEvc({ who, caseRec }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const onRoute = (caseRec.route ?? []).some((s) => s.stage === "EVC");
  const visited = caseRec.stage === "EVC" || (caseRec.stage_history ?? []).some((v) => v.stage === "EVC");

  useEffect(() => {
    if (!onRoute || !visited) return undefined;
    let live = true;
    api(who, `/applications/${caseRec.case_id}/evc`)
      .then((out) => live && setData(out))
      .catch((e) => live && setError(e));
    return () => { live = false; };
  }, [who, caseRec.case_id, caseRec.version]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!onRoute || !visited) return null;
  const rows = data?.requests ?? null;
  return (
    <section className="case-zone case-evc" aria-labelledby={`evc-${caseRec.case_id}`}>
      <h3 id={`evc-${caseRec.case_id}`}>Expert visit (EVC)</h3>
      <ErrorBox error={refusal(error)} />
      {rows?.length === 0 && <p className="muted">No expert-visit request is recorded for this case.</p>}
      {rows?.map((r, index) => {
        const s = evcStatusOf(r.status);
        return (
          <div key={r.id} className="evc-request">
            {rows.length > 1 && <h4>{index === 0 ? "Latest request" : `Earlier request ${rows.length - index}`}</h4>}
            <dl className="facts">
              <dt>Status</dt><dd><Badge tone={s.tone}>{s.label}</Badge></dd>
              <dt>Requested</dt><dd>{when(r.requested_at)}</dd>
              <dt>Visit window</dt><dd>{dateIST(r.earliest_date)} to {dateIST(r.due_by)}</dd>
              <dt>Waiting</dt><dd><span className="num">{r.days_waiting}</span> day{r.days_waiting === 1 ? "" : "s"}</dd>
              <dt>Time allowed</dt><dd>{r.duration_days} days <Badge tone="sample">Demo assumption</Badge></dd>
              {r.visit && (
                <>
                  <dt>Visit</dt><dd>{dateIST(r.visit.date)} · {slotPartLabel(r.visit.slot_part)}</dd>
                  <dt>Panel</dt>
                  <dd>
                    {r.visit.expert_ids.map((x) => <code key={x} title={`expert reference ${x} (identity unverified)`}>{short(x)} </code>)}
                    <Badge tone="sample">Simulated</Badge>
                  </dd>
                </>
              )}
            </dl>
            {r.visit && (
              <p className="muted small">Panel formed by the {r.visit.selector_label}; references only, identities are not verified.</p>
            )}
          </div>
        );
      })}
      {rows?.some((r) => r.status === "QUEUED" || r.status === "PROPOSED") && (
        <p className="muted small">The visit is planned and published from the EVC scheduling screen. The visit can be completed only once it is published.</p>
      )}
    </section>
  );
}
