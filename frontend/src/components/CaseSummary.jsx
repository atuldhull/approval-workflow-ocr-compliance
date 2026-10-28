import { useEffect, useState } from "react";
import { api } from "../api.js";
import { sentence } from "../nav.js";
import { INTERNAL_REF_TITLE, internalRef } from "../provenance.js";
import { letterLabel, ruleLabel } from "../recordText.js";
import { actionLabel, itemLabel, refusal, workflowReasonLabel } from "../workflowText.js";
import { stageLabel } from "./RouteJourney.jsx";
import { Badge, ErrorBox, Loading, dateIST, when } from "./ui.jsx";

const short = (id) => String(id).slice(0, 8);
const fingerprint = (hash) => <code title={`SHA-256 ${hash}`}>{hash.slice(0, 12)}…</code>;
const outcomeText = (o) => (o ? actionLabel(o.toLowerCase()) : "In this stage now");
const citationText = (c) => {
  if (!c) return "Not supplied";
  const where = [c.locator === "TABLE_2_3" ? "Table 2.3" : c.locator && sentence(c.locator), c.clause && `cl. ${c.clause}`, c.row && `row ${c.row}`, c.page && `p.${c.page}`]
    .filter(Boolean).join(", ");
  return `APH 2024-27 ${where}`;
};

function Section({ title, children }) {
  return (
    <section className="summary-section">
      <h4>{title}</h4>
      {children}
    </section>
  );
}

function Withheld() {
  return <p className="muted small">Not shown: your role may not read this part of the case.</p>;
}

// The electronic case summary (GET /cases/{id}/summary): one printable record of the case's route, stage visits,
// deficiencies, committee reports, expert visits, open deadlines, obligations, letters and appeal. Written notes
// and reports are shown only by their fingerprints, as everywhere else. Printing uses the browser's own print
// (print styles in styles.css keep only this document); nothing is generated outside the page.
export default function CaseSummary({ who, caseId, onClose }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let live = true;
    api(who, `/cases/${caseId}/summary`).then((out) => live && setData(out), (e) => live && setError(e));
    return () => { live = false; };
  }, [who, caseId]);

  return (
    <article className="card case-summary" aria-labelledby={`summary-${caseId}`}>
      <header className="summary-head">
        <div>
          <p className="case-ref">Electronic case summary · Internal ref <code title={INTERNAL_REF_TITLE}>{internalRef(caseId)}</code></p>
          <h3 id={`summary-${caseId}`}>{data ? data.route_label ?? sentence(data.route_id) : "Case summary"}</h3>
          {data && <p className="muted small">Prepared {when(data.generated_at)} · case version <span className="num">{data.version}</span></p>}
        </div>
        <div className="actions no-print">
          <button type="button" onClick={() => window.print()} disabled={!data}>Print</button>
          <button type="button" className="secondary" onClick={onClose}>Close summary</button>
        </div>
      </header>
      <ErrorBox error={refusal(error)} />
      {!data && !error && <Loading what="Preparing the case summary" rows={4} />}
      {data && (
        <>
          <Section title="Case">
            <dl className="facts">
              <dt>Status</dt><dd>{sentence(data.status)}{data.stage ? ` · ${stageLabel(data.stage)}` : ""}</dd>
              <dt>Academic year</dt><dd>{data.academic_year ?? "Not supplied"}</dd>
              <dt>Region</dt><dd>{data.region}</dd>
              <dt>Institution</dt><dd><code>{short(data.institution_id)}</code></dd>
              <dt>Submitted</dt><dd>{when(data.submitted_at)}</dd>
              <dt>Rules</dt><dd>{data.ruleset_key ? <code>{data.ruleset_key}</code> : "Not pinned yet"}</dd>
              <dt>Route source</dt>
              <dd>
                {citationText(data.clause_citation)}{" "}
                {data.clause_citation?.status === "VERIFIED" ? <Badge tone="ok">Verified</Badge> : <Badge tone="sample">Demo assumption</Badge>}
              </dd>
              <dt>Route</dt>
              <dd>{data.route.map((s) => `${stageLabel(s.stage)}${s.when === "as_applicable" ? " (if applicable)" : ""}`).join(" → ") || "—"}</dd>
            </dl>
            {data.assumption_status && <p className="muted small">Workflow policies on this route are demo assumptions.</p>}
          </Section>

          <Section title="Stages">
            {data.stage_visits.length === 0 ? <p className="muted small">Not submitted yet.</p> : (
              <table className="summary-table">
                <thead><tr><th scope="col">Stage</th><th scope="col">Entered</th><th scope="col">Left</th><th scope="col">Outcome</th><th scope="col">Reason</th></tr></thead>
                <tbody>
                  {data.stage_visits.map((v) => (
                    <tr key={v.id}>
                      <td>{stageLabel(v.stage)}</td><td>{when(v.entered_at)}</td><td>{v.exited_at ? when(v.exited_at) : "—"}</td>
                      <td>{outcomeText(v.outcome)}</td><td>{v.reason_code ? workflowReasonLabel(v.reason_code) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Section>

          <Section title="Deficiencies">
            {data.deficiencies.length === 0 ? <p className="muted small">None recorded.</p> : data.deficiencies.map((r) => (
              <p key={r.round_no}>
                Round <span className="num">{r.round_no}</span> · {sentence(r.status)} · opened {dateIST(r.opened_at)}
                {r.closed_at ? `, closed ${dateIST(r.closed_at)}` : ""}:{" "}
                {r.items.map((i) => `${itemLabel(i.item_key)} (${sentence(i.state).toLowerCase()})`).join("; ")}
              </p>
            ))}
          </Section>

          <Section title="Committees and reports">
            {data.committees.length === 0 ? <p className="muted small">No committee formed.</p> : (
              <ul className="summary-list">
                {data.committees.map((c) => (
                  <li key={c.id}>
                    {sentence(c.type)} committee {c.ordinal} · {sentence(c.status).toLowerCase()} · {c.member_count} member{c.member_count === 1 ? "" : "s"}
                    {c.reports.length === 0 ? " · no report" : c.reports.map((r) => (
                      <span key={r.id}> · report v{r.version_no}, {dateIST(r.created_at)}, {fingerprint(r.content_note_hash)}</span>
                    ))}
                  </li>
                ))}
              </ul>
            )}
            <p className="muted small">Reports are protected notes; the summary shows their fingerprints, not their text.</p>
          </Section>

          <Section title="Expert visits (EVC)">
            {data.evc_requests.length === 0 ? <p className="muted small">No expert visit requested.</p> : (
              <ul className="summary-list">
                {data.evc_requests.map((r) => (
                  <li key={r.id}>
                    {sentence(r.status)} · requested {dateIST(r.requested_at)}, due by {dateIST(r.due_by)}
                    {r.rule_id ? ` · ${ruleLabel(r.rule_id)}` : ""}{r.duration_days ? ` (${r.duration_days} days, demo assumption)` : ""}
                    {r.visit ? ` · visit ${dateIST(r.visit.date)} ${r.visit.slot_part}, panel of ${r.visit.panel_size} (simulated selector)` : ""}
                  </li>
                ))}
              </ul>
            )}
          </Section>

          <Section title="Open deadlines">
            {data.open_deadlines == null ? <Withheld /> : data.open_deadlines.length === 0 ? <p className="muted small">None running.</p> : (
              <ul className="summary-list">
                {data.open_deadlines.map((d) => (
                  <li key={d.id}>
                    {ruleLabel(d.rule_id)} · due {dateIST(d.due_date)} · {sentence(d.status).toLowerCase()} ·{" "}
                    {d.clock_kind === "LEGAL" ? "legal clock" : "internal clock"}
                    {d.clause ? ` · APH cl. ${d.clause}` : ""} {d.source_status === "verified" ? <Badge tone="ok">Verified</Badge> : <Badge tone="sample">Demo assumption</Badge>}
                  </li>
                ))}
              </ul>
            )}
          </Section>

          <Section title="Obligations">
            {data.obligations == null ? <Withheld /> : data.obligations.length === 0 ? <p className="muted small">None.</p> : (
              <ul className="summary-list">
                {data.obligations.map((o) => (
                  <li key={o.id}>
                    {sentence(o.kind)} · {sentence(o.status).toLowerCase()}{o.due_date ? ` · due ${dateIST(o.due_date)}` : ""}
                    {o.source_clause ? ` · APH cl. ${o.source_clause}` : ""}
                  </li>
                ))}
              </ul>
            )}
          </Section>

          <Section title="Letters">
            {data.letters == null ? <Withheld /> : data.letters.length === 0 ? <p className="muted small">None issued.</p> : (
              <ul className="summary-list">
                {data.letters.map((l) => (
                  <li key={l.id}>{letterLabel(l.letter_type)} · {l.academic_year} · issued {dateIST(l.issue_date)}{l.valid_until ? ` · valid until ${dateIST(l.valid_until)}` : ""}</li>
                ))}
              </ul>
            )}
          </Section>

          <Section title="Appeal">
            {!data.appeal ? <p className="muted small">No appeal window was opened.</p> : (
              <p>
                {sentence(data.appeal.status)} · window due {dateIST(data.appeal.window.due_date)}
                {data.appeal.filed_at ? ` · filed ${dateIST(data.appeal.filed_at)}` : ""}
                {data.appeal.recommendation ? ` · SAC: ${sentence(data.appeal.recommendation).toLowerCase()}` : ""}
                {data.appeal.outcome ? ` · Council: ${letterLabel(data.appeal.outcome)}` : ""}
                {data.appeal.speaking_order_note_hash && <> · speaking order {fingerprint(data.appeal.speaking_order_note_hash)}</>}
              </p>
            )}
          </Section>
          <p className="muted small">
            A record of what was decided and by which step; the decisions are the officers&apos; and committees&apos;, not
            the system&apos;s. Demo data is fictional.
          </p>
        </>
      )}
    </article>
  );
}
