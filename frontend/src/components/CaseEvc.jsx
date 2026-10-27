import { useEffect, useState } from "react";
import { api } from "../api.js";
import { evcStatusOf, refusal } from "../workflowText.js";
import { Badge, ErrorBox, dateIST, when } from "./ui.jsx";

// The expert-visit request(s) of one case, read from the role-scoped EVC queue (GET /evc/queue). The queue has no
// per-case filter yet, so the case's rows are picked out of the first page the caller may see.
export default function CaseEvc({ who, me, caseRec }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const onRoute = (caseRec.route ?? []).some((s) => s.stage === "EVC");
  const visited = caseRec.stage === "EVC" || (caseRec.stage_history ?? []).some((v) => v.stage === "EVC");

  useEffect(() => {
    if (!onRoute || !visited) return undefined;
    let live = true;
    const region = me.role === "RO_OFFICER" ? `&region=${encodeURIComponent(me.region)}` : "";
    api(who, `/evc/queue?limit=100${region}`)
      .then((page) => live && setRows(page.items.filter((r) => r.application_id === caseRec.case_id)))
      .catch((e) => live && setError(e));
    return () => { live = false; };
  }, [who, caseRec.case_id, caseRec.version]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!onRoute || !visited) return null;
  return (
    <section className="case-zone case-evc" aria-labelledby={`evc-${caseRec.case_id}`}>
      <h3 id={`evc-${caseRec.case_id}`}>Expert visit (EVC)</h3>
      <ErrorBox error={refusal(error)} />
      {rows?.length === 0 && <p className="muted">No expert-visit request is recorded for this case.</p>}
      {rows?.map((r) => {
        const s = evcStatusOf(r.status);
        return (
          <dl key={r.id} className="facts">
            <dt>Status</dt><dd><Badge tone={s.tone}>{s.label}</Badge></dd>
            <dt>Requested</dt><dd>{when(r.requested_at)}</dd>
            <dt>Visit window</dt><dd>{dateIST(r.earliest_date)} to {dateIST(r.due_by)}</dd>
            <dt>Waiting</dt><dd><span className="num">{r.days_waiting}</span> day{r.days_waiting === 1 ? "" : "s"}</dd>
            <dt>Time allowed</dt><dd>{r.duration_days} days <Badge tone="sample">Demo assumption</Badge></dd>
          </dl>
        );
      })}
      {rows?.some((r) => r.status === "QUEUED" || r.status === "PROPOSED") && (
        <p className="muted small">The visit is planned and published from the EVC scheduling screen. The visit can be completed only once it is published.</p>
      )}
    </section>
  );
}
