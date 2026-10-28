import { useState } from "react";
import { apiFile } from "../api.js";
import { Icon } from "../components/Icons.jsx";
import { stageLabel } from "../components/RouteJourney.jsx";
import { Badge, Card, Empty, ErrorBox, Loading, Toast, useApi, useSingleFlight } from "../components/ui.jsx";
import { ROLE_LABELS, sentence } from "../nav.js";
import { checklistLabel, daysLeftText, deadlineStatusOf, obligationStatusOf, ruleLabel, validityStateOf } from "../recordText.js";

const CSV = new Set(["text/csv"]);
const pct = (r) => (r == null ? "—" : `${Math.round(r * 100)}%`);
const num = (v) => (v == null ? "—" : v);
const VALIDITY_BASIS = { DOCUMENT_FACT: "The document, confirmed by two officers", OFFICER_RECORDED: "Recorded by an officer", APH_PERIOD: "APH period from the issue date" };

// How each column reads on screen. The CSV keeps the server's own values; only the table is put into words.
const CELLS = {
  stage: stageLabel,
  rule_id: ruleLabel,
  owner_role: (r) => (r ? ROLE_LABELS[r] ?? sentence(r) : "—"),
  kind: sentence,
  completion_rate: pct,
  alerts_acknowledged_on_time: pct,
  validity_basis: (b) => VALIDITY_BASIS[b] ?? (b ? sentence(b) : "—"),
  days_left: daysLeftText,
  live_lease_ok: (v) => (v == null ? "—" : v ? "Yes" : "No"),
};
const STATUS_OF = { overdue: deadlineStatusOf, undertakings: obligationStatusOf };
// Columns shown as a badge whatever the report: a validity record's state and the state of its clock.
const BADGES = { validity_state: validityStateOf, deadline_status: deadlineStatusOf };
const NUMERIC = (key) => !["region", "stage", "rule_id", "owner_role", "kind", "status", "case_ref", "due_date", "document",
  "valid_until", "validity_basis", "days_left", "validity_state", "eoa_stop_year", "live_lease_ok", "deadline_status"].includes(key);

// Reports computed from the event log, each with the ledger entry and snapshot hash it was computed at, so a
// figure here can be recomputed and checked. The table shows the same rows as the CSV download.
export default function ReportsView({ who, me, onNavigate }) {
  const list = useApi(who, "/reports");
  const [type, setType] = useState("pendency");
  const report = useApi(who, `/reports/${type}`);
  const [downloadError, setDownloadError] = useState(null);
  const [notice, setNotice] = useState(null);
  const once = useSingleFlight();

  const download = () => once(async () => {
    setDownloadError(null);
    setNotice(null);
    try {
      const blob = await apiFile(who, `/reports/${type}?format=csv`, CSV);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${type}-${(report.data?.scope?.region || "all").toLowerCase().replace(/\s+/g, "-")}.csv`;
      a.click();
      URL.revokeObjectURL(url);
      setNotice("CSV downloaded. Its last lines name the ledger entry and snapshot hash shown here.");
    } catch (e) {
      setDownloadError(e);
    }
  });

  const r = report.data?.type === type ? report.data : null;
  const columns = (r?.columns ?? []).filter((c) => c.key !== "application_id");
  const cell = (row, c) => {
    if (c.key === "case_ref" && row.application_id) {
      return (
        <button className="ghost small" onClick={() => onNavigate?.("applications", { caseId: row.application_id })}
          aria-label={`Open case ${row.case_ref}`} title={row.application_id}>
          <code>{row.case_ref}</code>
        </button>
      );
    }
    if (c.key === "status" && STATUS_OF[type]) {
      const s = STATUS_OF[type](row.status);
      return <Badge tone={s.tone}>{s.label}</Badge>;
    }
    if (BADGES[c.key]) {
      if (row[c.key] == null) return "—";
      const s = BADGES[c.key](row[c.key]);
      return <Badge tone={s.tone}>{s.label}</Badge>;
    }
    if (c.key === "document" && row.doc_type) return checklistLabel(row.doc_type);
    return (CELLS[c.key] ?? num)(row[c.key]);
  };

  return (
    <div className="reports">
      <Card title="Report" actions={
        <button className="secondary small" onClick={download} disabled={!r}>
          <Icon name="download" /> Download CSV
        </button>
      }>
        <ErrorBox error={list.error} onRetry={list.reload} />
        {list.data && (
          <div className="chips" role="group" aria-label="Choose a report">
            {list.data.map((item) => (
              <button key={item.type} className={`chip${type === item.type ? " on" : ""}`} aria-pressed={type === item.type}
                onClick={() => setType(item.type)}>
                {item.title}
              </button>
            ))}
          </div>
        )}
        <div className="freshness">
          <span className="scope-chip">{me?.role === "RO_OFFICER" ? `${me.region ?? "Your"} region only` : "All regions"}</span>
          {r?.scope?.as_of && <span className="muted small">days counted to {r.scope.as_of} (IST)</span>}
        </div>
        {report.loading && !r && <Loading what="Computing report" rows={4} />}
        <ErrorBox error={report.error} onRetry={report.reload} />
        <ErrorBox error={downloadError} />
        {notice && <Toast>{notice}</Toast>}
        {r && r.rows.length === 0 && <Empty>Nothing to report in this scope.</Empty>}
        {r && r.rows.length > 0 && (
          <div className="table-wrap">
            <table className="table" tabIndex={0} aria-label={r.title}>
              <thead>
                <tr>{columns.map((c) => <th key={c.key} scope="col" className={NUMERIC(c.key) ? "num" : undefined}>{c.label}</th>)}</tr>
              </thead>
              <tbody>
                {r.rows.map((row, i) => (
                  <tr key={row.application_id ? `${row.application_id}-${row.rule_id}-${i}` : i}>
                    {columns.map((c) => <td key={c.key} className={NUMERIC(c.key) ? "num" : undefined}>{cell(row, c)}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {r && (
          <>
            {r.coverage?.note && <p className="muted small">{r.coverage.note}</p>}
            {Object.keys(r.coverage?.unhandled_event_types ?? {}).length > 0 && (
              <p className="muted small">Some recorded events are not understood by this report and are not reflected in it.</p>
            )}
            <p className="source">
              Source: {r.source}. Computed at ledger entry #{r.ledger_head?.seq}, snapshot <code>{String(r.snapshot_hash).slice(0, 12)}</code>;
              the same ledger {r.scope?.as_of ? "on the same day " : ""}gives the same hash.
            </p>
          </>
        )}
      </Card>
    </div>
  );
}
