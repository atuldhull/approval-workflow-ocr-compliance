import World from "../nebula/World.jsx";
import { useEffect, useRef, useState } from "react";
import { api, newIdempotencyKey } from "../api.js";
import { Icon } from "../components/Icons.jsx";
import ViewDocument from "../components/ViewDocument.jsx";
import { Badge, Card, Empty, ErrorBox, Loading, useApi, useSingleFlight, when } from "../components/ui.jsx";
import { sentence } from "../nav.js";
import { INTERNAL_REF_TITLE, internalRef } from "../provenance.js";
import {
  CHECKLIST, checklistLabel, explain, factStatusOf, fieldLabel, fileSize, isAvailable, versionStateOf,
} from "../recordText.js";

// The server's cap (backend/app/documents/config.py). Checked here only to save a pointless upload.
export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
const ACCEPT = "application/pdf,image/png,image/jpeg";
// While a version waits for its scan, the list is fetched again a few times so the verdict appears by itself.
const SCAN_POLL_MS = 4000;
const SCAN_POLLS = 5;

const UPLOAD_ERRORS = { 503: "Document storage is unavailable right now, so nothing was stored. Try again shortly." };
const SCAN_ERRORS = { 503: "The malware scanner did not answer. The file stays in quarantine; try the scan again shortly." };
// policy.py document.rescan: the owning institution and the case officers who can chase a stuck scan
const RESCANNERS = new Set(["INSTITUTION", "RO_OFFICER", "BUREAU_OFFICER", "BUREAU_HEAD"]);
const isQuarantined = (v) => v.status === "QUARANTINED";

export function ScanBadge({ version }) {
  const s = versionStateOf(version);
  return <Badge tone={s.tone}>{s.label}</Badge>;
}

export default function DocumentsView({ who, me }) {
  return me.role === "INSTITUTION" ? <InstitutionDocuments who={who} /> : <ScopeDocuments who={who} canScan={RESCANNERS.has(me.role)} />;
}

function documentRecords(docs) {
  return (docs ?? []).map((d) => {
    const newest = d.versions[0];
    return {
      id: d.document_id, label: checklistLabel(d.doc_type),
      state: newest?.status === "REJECTED" ? "broken" : newest?.status === "QUARANTINED" ? "active" : "checked",
      detail: newest ? `Version ${newest.version_no} · ${versionStateOf(newest).label}` : "No versions",
      facts: [["Checklist item", d.doc_type || "Not supplied"], ["Case", internalRef(d.application_id)],
        ["Versions", d.versions.length], ["Usable version", d.current_version_id ? "Yes, scanned clean" : "None scanned clean yet"]],
    };
  });
}

// ---- institution: its own applications, upload, versions and confirmed facts ----

function InstitutionDocuments({ who }) {
  const apps = useApi(who, "/applications");
  const [appId, setAppId] = useState(null);
  const chosen = appId ?? apps.data?.[0]?.id ?? null;
  const docs = useApi(who, chosen ? `/applications/${chosen}/documents` : null);
  const polls = useRef(0);
  const pending = (docs.data ?? []).some((d) => d.versions.some(isQuarantined));

  useEffect(() => {
    if (!pending || polls.current >= SCAN_POLLS) return undefined;
    const t = setTimeout(() => { polls.current += 1; docs.reload(); }, SCAN_POLL_MS);
    return () => clearTimeout(t);
  }, [pending, docs.data]); // eslint-disable-line react-hooks/exhaustive-deps

  const changed = () => { polls.current = 0; docs.reload(); };

  if (apps.loading && !apps.data) return <Loading what="Loading your applications" />;
  if (apps.error) return <ErrorBox error={apps.error} onRetry={apps.reload} />;
  if (!apps.data?.length) return <Empty>You have no applications yet. Create one under My applications, then add its documents here.</Empty>;

  return (
    <div>
      <World kind="documents" records={documentRecords(docs.data)} />
      <div className="grid two">
        <Card title="Add a document">
          <label>
            Application
            <select value={chosen ?? ""} onChange={(e) => setAppId(e.target.value)}>
              {apps.data.map((a) => (
                <option key={a.id} value={a.id}>{sentence(a.category)} · {a.academic_year} · ref {internalRef(a.id)}</option>
              ))}
            </select>
          </label>
          <UploadForm key={chosen} who={who} appId={chosen} onUploaded={changed} />
        </Card>
        <Card title="Documents for this application"
          actions={<button className="secondary small" onClick={changed}><Icon name="refresh" /> Refresh</button>}>
          <DocumentList who={who} state={docs} canScan onChanged={changed} showFacts />
        </Card>
      </div>
    </div>
  );
}

export function UploadForm({ who, appId, onUploaded }) {
  const [docType, setDocType] = useState(CHECKLIST[0][0]);
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  // One key per upload; a retry of the same file for the same item reuses it, so the server can replay its answer.
  const pendingKey = useRef(null);
  const once = useSingleFlight();

  const edited = (fn) => (e) => { fn(e); pendingKey.current = null; setResult(null); setError(null); };
  const tooBig = file && file.size > MAX_UPLOAD_BYTES;

  const submit = (e) => {
    e.preventDefault();
    return once(send);
  };

  async function send() {
    if (!file || tooBig) return;
    setBusy(true);
    setError(null);
    pendingKey.current ??= newIdempotencyKey();
    const form = new FormData();
    form.append("doc_type", docType);
    form.append("file", file, file.name);
    try {
      const body = await api(who, `/applications/${appId}/documents`, {
        method: "POST", form, headers: { "Idempotency-Key": pendingKey.current },
      });
      pendingKey.current = null;
      setResult(body);
      onUploaded?.();
    } catch (err) {
      // a refusal is not retried as-is; a lost answer or server failure keeps the key for the retry
      if (err.status && err.status < 500) pendingKey.current = null;
      setError(explain(err, UPLOAD_ERRORS));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} aria-label="Upload a document">
      <label>
        Checklist item
        <select value={docType} onChange={edited((e) => setDocType(e.target.value))}>
          {CHECKLIST.map(([code, label]) => <option key={code} value={code}>{label}</option>)}
        </select>
      </label>
      <label>
        File (PDF, PNG or JPEG, up to 10 MB)
        <input type="file" accept={ACCEPT} onChange={edited((e) => setFile(e.target.files?.[0] ?? null))} />
      </label>
      <p className="muted small">
        Use synthetic files only. Each upload of a changed file adds a new version; older versions are kept.
        A new version stays in quarantine until the malware scan is clean.
      </p>
      {tooBig && <p className="error small" role="alert">This file is larger than 10 MB, which the server does not accept.</p>}
      <ErrorBox error={error} />
      {error && error.status !== 403 && pendingKey.current && (
        <p className="muted small">Trying again sends the same upload, so it cannot be stored twice.</p>
      )}
      {result && (
        <p className="ok" role="status">
          {result.created
            ? `Uploaded as version ${result.version.version_no} of "${checklistLabel(result.doc_type)}". It is waiting for the malware scan.`
            : `This exact file is already version ${result.version.version_no} of "${checklistLabel(result.doc_type)}". Nothing new was stored.`}
        </p>
      )}
      <button disabled={!file || tooBig || busy}>
        {busy ? "Uploading…" : error && pendingKey.current ? "Try the upload again" : "Upload"}
      </button>
    </form>
  );
}

export function DocumentList({ who, state, canScan, onChanged, showFacts, showCase }) {
  const [scanError, setScanError] = useState(null);
  const [scanning, setScanning] = useState(null);
  const [factsFor, setFactsFor] = useState(null);
  const once = useSingleFlight();

  const scan = (versionId) => once(async () => {
    setScanning(versionId);
    setScanError(null);
    try {
      await api(who, `/document-versions/${versionId}/scan`, { method: "POST" });
      onChanged?.();
    } catch (e) {
      setScanError(explain(e, SCAN_ERRORS));
    } finally {
      setScanning(null);
    }
  });

  if (state.loading && !state.data) return <Loading what="Loading documents" />;
  if (state.error) return <ErrorBox error={state.error} onRetry={state.reload} />;
  if (!state.data) return null;
  if (state.data.length === 0) return <Empty>No documents yet.</Empty>;

  return (
    <div className="doc-list">
      <ErrorBox error={scanError} />
      {state.data.map((d) => (
        <section key={d.document_id} className="doc-item" aria-label={checklistLabel(d.doc_type)}>
          <header className="doc-head">
            <h3>{checklistLabel(d.doc_type)}</h3>
            <span className="muted small">
              {d.doc_type && <code>{d.doc_type}</code>}
              {showCase && <> · case <code title={INTERNAL_REF_TITLE}>{internalRef(d.application_id)}</code></>}
            </span>
          </header>
          <ul className="version-list">
            {d.versions.map((v) => {
              const s = versionStateOf(v);
              return (
                <li key={v.version_id} className="version">
                  <div className="version-main">
                    <span className="version-no num">v{v.version_no}</span>
                    <span className="version-name">{v.original_filename}</span>
                    <ScanBadge version={v} />
                  </div>
                  <p className="muted small">{s.meaning}</p>
                  <p className="muted small">
                    {fileSize(v.size_bytes)} · uploaded {when(v.uploaded_at)}
                    {v.scanned_at && <> · scanned {when(v.scanned_at)}</>}
                    {d.current_version_id === v.version_id && <> · <strong>current usable version</strong></>}
                  </p>
                  <div className="actions">
                    {canScan && isQuarantined(v) && (
                      <button className="secondary small" disabled={scanning !== null} onClick={() => scan(v.version_id)}
                        aria-label={`Run the malware scan again for version ${v.version_no} of ${checklistLabel(d.doc_type)}`}>
                        {scanning === v.version_id ? "Scanning…" : "Scan again"}
                      </button>
                    )}
                    {isAvailable(v) && <ViewDocument who={who} versionId={v.version_id} filename={v.original_filename} />}
                    {showFacts && isAvailable(v) && (
                      <button className="ghost small" aria-expanded={factsFor === v.version_id}
                        onClick={() => setFactsFor(factsFor === v.version_id ? null : v.version_id)}>
                        {factsFor === v.version_id ? "Hide confirmed facts" : "Confirmed facts"}
                      </button>
                    )}
                  </div>
                  {factsFor === v.version_id && <ConfirmedFacts who={who} versionId={v.version_id} />}
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}

// Institutions see only values a second officer has confirmed, plus how many are still in review.
export function ConfirmedFacts({ who, versionId }) {
  const { data, error, loading, reload } = useApi(who, `/document-versions/${versionId}/facts`);
  if (loading && !data) return <Loading what="Loading confirmed facts" rows={2} />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (!data) return null;
  const counts = data.review_status ?? {};
  const waiting = (counts.proposed ?? 0) + (counts.in_review ?? 0) + (counts.reviewed ?? 0);
  return (
    <div className="confirmed-facts">
      <p className="small">
        Review status: <strong className="num">{counts.confirmed ?? 0}</strong> confirmed ·{" "}
        <span className="num">{waiting}</span> still with officers · <span className="num">{counts.rejected ?? 0}</span> rejected
      </p>
      {data.facts.length === 0 ? (
        <p className="muted small">No value from this version has been confirmed yet. Officers' working readings are not shown.</p>
      ) : (
        <dl className="facts">
          {data.facts.map((f) => (
            <div key={f.fact_id} className="fact-row">
              <dt>{fieldLabel(f.field_key)}</dt>
              <dd>
                <strong>{f.value}</strong> <Badge tone={factStatusOf(f.status).tone}>{factStatusOf(f.status).label}</Badge>
                <span className="muted small"> · page {f.page_number} · {when(f.confirmed_at)}</span>
              </dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}

// ---- officers and auditors: documents across the applications in their scope ----

function ScopeDocuments({ who, canScan }) {
  const [docType, setDocType] = useState("");
  const path = docType ? `/documents?doc_type=${encodeURIComponent(docType)}` : "/documents";
  const docs = useApi(who, path);
  return (
    <div>
      <World kind="documents" records={documentRecords(docs.data)} />
      <Card title="Documents in your scope"
        actions={<button className="secondary small" onClick={docs.reload}><Icon name="refresh" /> Refresh</button>}>
        <label className="inline">
          Checklist item
          <select value={docType} onChange={(e) => setDocType(e.target.value)}>
            <option value="">All items</option>
            {CHECKLIST.map(([code, label]) => <option key={code} value={code}>{label}</option>)}
          </select>
        </label>
        <p className="muted small">
          Each version and its scan result. Only versions that passed the malware scan can be opened; quarantined and
          blocked files are never served.
        </p>
        <DocumentList who={who} state={docs} canScan={canScan} onChanged={docs.reload} showCase />
      </Card>
    </div>
  );
}
