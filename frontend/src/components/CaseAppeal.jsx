import { useEffect, useState } from "react";
import { api } from "../api.js";
import { letterLabel } from "../recordText.js";
import { refusal } from "../workflowText.js";
import { Badge, ErrorBox, dateIST, when } from "./ui.jsx";

const STATUS = {
  WINDOW_OPEN: { tone: "warn", label: "Appeal window open" },
  FILED: { tone: "info", label: "Appeal filed; awaiting the SAC" },
  RECOMMENDED: { tone: "info", label: "SAC recommends; awaiting the Council" },
  NOT_RECOMMENDED: { tone: "info", label: "SAC does not recommend; awaiting the Council" },
  REFERRED_BACK: { tone: "info", label: "Referred back by the SAC" },
  LAPSED: { tone: "bad", label: "Window lapsed; LoD stands" },
  DECIDED: { tone: "ok", label: "Council decision recorded" },
};
const RECOMMENDATION = {
  RECOMMEND: "Recommend", NOT_RECOMMEND: "Do not recommend",
  REFER_SCRUTINY: "Refer for Scrutiny", REFER_EVC: "Refer for an expert visit",
};
const short = (id) => String(id).slice(0, 8);
const fingerprint = (hash) => <code title={`SHA-256 ${hash}`}>{hash.slice(0, 12)}…</code>;

// The appeal against the case's LoD (GET /cases/{id}/appeal; APH cl. 1.11 / 2.24): the 7-day window and days left,
// the filing, the SAC's recommendation and the Council's decision. Filing, recommending and deciding are case
// actions listed under "What you can do now" for the role that may take them; this panel shows the record. Notes
// (grounds, speaking order) appear only as fingerprints.
export default function CaseAppeal({ who, caseRec }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const relevant = caseRec.stage === "SAC" || (caseRec.stage_history ?? []).some((v) => v.outcome === "ISSUE_LOD");
  useEffect(() => {
    if (!relevant) return undefined;
    let live = true;
    api(who, `/cases/${caseRec.case_id}/appeal`)
      .then((out) => live && setData(out), (e) => live && setError(e));
    return () => { live = false; };
  }, [who, caseRec.case_id, caseRec.version]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!relevant) return null;
  const a = data?.appeal;
  const s = a ? STATUS[a.status] ?? { tone: "neutral", label: a.status } : null;
  return (
    <section className="case-zone case-appeal" aria-labelledby={`appeal-${caseRec.case_id}`}>
      <h3 id={`appeal-${caseRec.case_id}`}>Appeal against the LoD</h3>
      <ErrorBox error={refusal(error)} />
      {data && !a && <p className="muted">No appeal window was opened on this case.</p>}
      {a && (
        <>
          <dl className="facts">
            <dt>Status</dt><dd><Badge tone={s.tone}>{s.label}</Badge></dd>
            <dt>Window</dt>
            <dd>
              {a.window.days_left != null && (
                <><strong className="num">{a.window.days_left}</strong> day{a.window.days_left === 1 ? "" : "s"} left · </>
              )}
              due <span className="num">{dateIST(a.window.due_date)}</span>
              {a.window.source_status === "verified" && <Badge tone="ok">APH cl. {a.window.clause}</Badge>}
            </dd>
            <dt>Appeals allowed</dt><dd>Once ({a.max_appeals}), within 7 days of the LoD</dd>
            {a.filed_at && <><dt>Filed</dt><dd>{when(a.filed_at)}{a.grounds_note_hash && <> · grounds {fingerprint(a.grounds_note_hash)}</>}</dd></>}
            {a.hearing_no > 1 && <><dt>SAC hearing</dt><dd>Hearing <span className="num">{a.hearing_no}</span>, after a referral</dd></>}
            {a.recommendation && (
              <><dt>SAC recommendation</dt>
                <dd>{RECOMMENDATION[a.recommendation] ?? a.recommendation} · {when(a.recommended_at)}
                  {a.recommendation_report_ref && <> · report <code>{short(a.recommendation_report_ref)}</code></>}</dd></>
            )}
            {a.outcome && (
              <><dt>Council decision</dt><dd>{letterLabel(a.outcome)} · {when(a.decided_at)}</dd></>
            )}
            {a.speaking_order_note_hash && <><dt>Speaking order</dt><dd>{fingerprint(a.speaking_order_note_hash)} (protected note)</dd></>}
            {a.closed_at && <><dt>Lapsed</dt><dd>{when(a.closed_at)}</dd></>}
          </dl>
          <p className="muted small">
            The system records what people decide: the institution files, the Standing Appellate Committee recommends
            and the Council&apos;s decision is final (APH 2024-27 cl. 1.11, 2.24). Unappealed, the window closes when its
            clock runs out.
          </p>
        </>
      )}
    </section>
  );
}
