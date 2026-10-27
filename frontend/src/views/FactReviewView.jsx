import World from "../operations/World.jsx";
import { useRef, useState } from "react";
import { api, newIdempotencyKey } from "../api.js";
import { Icon } from "../components/Icons.jsx";
import ViewDocument from "../components/ViewDocument.jsx";
import { Badge, Card, Empty, ErrorBox, Loading, useApi, useSingleFlight, when } from "../components/ui.jsx";
import { internalRef } from "../provenance.js";
import { actorText, checklistLabel, explain, factStatusOf, fieldLabel, isAvailable } from "../recordText.js";

// Type before reveal, then four eyes (backend/app/documents/README.md):
//   1. the reviewer types their own reading; the server records it before returning the machine suggestion,
//   2. only then is the suggestion shown, and the reviewer accepts, corrects or rejects it,
//   3. a different officer confirms the reviewed value. The server refuses a confirmation by the reviewer.
// The machine value never reaches the screen for a reviewer before step 1: the server withholds it, and this
// screen renders it only from the server's answer. The server says who acted only as {role, is_you}, and returns
// the caller's own blind entry (my_entry), so a reload mid-review picks up where the reviewer was.

const REVIEWERS = new Set(["SCRUTINY_COMMITTEE", "RO_OFFICER"]);
const CONFIRMERS = new Set(["SCRUTINY_COMMITTEE", "RO_OFFICER", "BUREAU_OFFICER", "BUREAU_HEAD"]);

export const FOUR_EYES_MESSAGE =
  "You reviewed this value, so you cannot also confirm it. A different officer must confirm it (four-eyes rule).";
export const FOUR_EYES_AHEAD =
  "After you record your review, a different officer must confirm it. You cannot confirm your own review (four-eyes rule).";
const EXTRACT_ERRORS = { 503: "No text reader is configured on the server yet, so facts cannot be extracted from this document." };
const CONFIRM_CODES = { FourEyesViolation: FOUR_EYES_MESSAGE };
const DECISION_TEXT = { ACCEPTED: "Machine reading accepted", CORRECTED: "Corrected by the reviewer", REJECTED: "Rejected" };

function cleanVersions(docs) {
  const out = [];
  for (const d of docs ?? []) {
    for (const v of d.versions) {
      if (!isAvailable(v)) continue;
      out.push({ id: v.version_id, label: `${checklistLabel(d.doc_type)} · v${v.version_no} · case ${internalRef(d.application_id)}`,
        filename: v.original_filename });
    }
  }
  return out;
}

export default function FactReviewView({ who, me }) {
  const docs = useApi(who, "/documents");
  const [picked, setPicked] = useState(null);
  const versions = cleanVersions(docs.data);
  const versionId = picked ?? versions[0]?.id ?? null;
  const current = versions.find((v) => v.id === versionId);
  const facts = useApi(who, versionId ? `/document-versions/${versionId}/facts` : null);
  const canReview = REVIEWERS.has(me.role);
  const canConfirm = CONFIRMERS.has(me.role);

  // Only state and page reach the visual register: never a machine value, so the blind step stays blind.
  const records = (facts.data?.facts ?? []).map((f) => ({
    id: f.fact_id, label: fieldLabel(f.field_key), state: f.status === "confirmed" ? "checked" : f.status === "rejected" ? "broken" : "active",
    detail: factStatusOf(f.status).label, facts: [["Page", f.page_number ?? "Not supplied"], ["Status", factStatusOf(f.status).label]],
  }));

  if (docs.loading && !docs.data) return <Loading what="Loading documents to review" />;
  if (docs.error) return <ErrorBox error={docs.error} onRetry={docs.reload} />;

  return (
    <div>
      <World kind="facts" records={records} />
      <Card title="Document" actions={<button className="secondary small" onClick={() => { docs.reload(); facts.reload(); }}><Icon name="refresh" /> Refresh</button>}>
        {versions.length === 0 ? (
          <Empty>No document in your scope has a version that passed the malware scan, so there is nothing to review.</Empty>
        ) : (
          <>
            <label>
              Version to review
              <select value={versionId ?? ""} onChange={(e) => setPicked(e.target.value)}>
                {versions.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
              </select>
            </label>
            <div className="actions">
              {current && <ViewDocument who={who} versionId={current.id} filename={current.filename} />}
            </div>
            <p className="muted small">
              Read each value from the original document: open it in its own tab. The machine reading stays hidden
              until you commit your own.
            </p>
          </>
        )}
      </Card>
      {versionId && (
        <FactList key={versionId} who={who} versionId={versionId} state={facts}
          canReview={canReview} canConfirm={canConfirm} />
      )}
    </div>
  );
}

function FactList({ who, versionId, state, canReview, canConfirm }) {
  const [extractError, setExtractError] = useState(null);
  const [extracting, setExtracting] = useState(false);
  const once = useSingleFlight();

  const extract = () => once(async () => {
    setExtracting(true);
    setExtractError(null);
    try {
      await api(who, `/document-versions/${versionId}/extract`, { method: "POST" });
      state.reload();
    } catch (e) {
      setExtractError(explain(e, EXTRACT_ERRORS));
    } finally {
      setExtracting(false);
    }
  });

  if (state.loading && !state.data) return <Loading what="Loading facts" />;
  if (state.error) return <ErrorBox error={state.error} onRetry={state.reload} />;
  if (!state.data) return null;
  const readOnly = !canReview && !canConfirm;
  if (state.data.version_status && state.data.version_status !== "AVAILABLE") {
    return <Card title="Facts from this version"><Empty>This version is no longer available, so its facts cannot be reviewed.</Empty></Card>;
  }

  return (
    <Card title="Facts from this version">
      {readOnly && <p className="muted small" role="note">Read-only: your role can see the review record but not change it.</p>}
      {!canReview && canConfirm && (
        <p className="muted small" role="note">Your role confirms values another officer reviewed; it does not enter or review readings.</p>
      )}
      {state.data.facts.length === 0 && (
        <>
          <Empty>No facts have been extracted from this version yet.</Empty>
          {canReview && (
            <button onClick={extract} disabled={extracting}>{extracting ? "Extracting…" : "Extract facts"}</button>
          )}
          <ErrorBox error={extractError} />
        </>
      )}
      {state.data.facts.map((f) => (
        <FactCard key={f.fact_id} fact={f} who={who} canReview={canReview} canConfirm={canConfirm} onChanged={state.reload} />
      ))}
    </Card>
  );
}

const shownValue = (s) => s?.normalized_value ?? s?.candidate_text ?? null;
const sentenceCase = (t) => (t ? t[0].toUpperCase() + t.slice(1) : t);

export function FactCard({ fact, who, canReview, canConfirm, onChanged }) {
  const [reading, setReading] = useState("");
  const [typed, setTyped] = useState(null); // what this reviewer typed in this page view
  const [suggestion, setSuggestion] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(null);
  const once = useSingleFlight();
  const legend = fieldLabel(fact.field_key);
  const status = factStatusOf(fact.status);
  // The reviewer's own entry: from this page view, or as the server recorded it (after a reload).
  const mine = fact.my_entry ?? null;
  const committed = typed ?? mine?.value ?? null;
  // The server says whether this caller may see the machine reading; for reviewers, only after their own entry.
  const visible = suggestion ?? (fact.suggestion_visible ? fact : null);
  // An in-review fact names who entered its reading; only that reviewer may reveal and review it.
  const enteredByMe = mine != null || fact.entered_by?.is_you === true;

  const run = (name, fn) => once(async () => {
    setBusy(name);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  });

  const commit = (e) => {
    e.preventDefault();
    const value = reading.trim();
    if (!value) return undefined;
    return run("entry", async () => {
      const s = await api(who, `/document-facts/${fact.fact_id}/entry`, { method: "POST", body: { value } });
      setTyped(value);
      setSuggestion(s);
      onChanged?.();
    });
  };

  const reveal = () => run("reveal", async () => {
    setSuggestion(await api(who, `/document-facts/${fact.fact_id}/reveal`, { method: "POST" }));
  });

  return (
    <fieldset className="ocr-field fact-card">
      <legend>{legend}</legend>
      <p className="fact-meta">
        <Badge tone={status.tone}>{status.label}</Badge>
        <span className="muted small"> page {fact.page_number ?? "not supplied"}</span>
      </p>

      {canReview && fact.status === "proposed" && !visible && (
        <form onSubmit={commit} className="blind-entry">
          <label>
            Your reading
            <input value={reading} onChange={(e) => setReading(e.target.value)} disabled={busy !== null}
              name={`reading-${fact.fact_id}`} autoComplete="off" spellCheck={false} aria-describedby={`${fact.fact_id}-hint`} />
          </label>
          <p id={`${fact.fact_id}-hint`} className="muted small">
            Type the value as the document shows it. The machine reading is revealed only after the server records yours.
          </p>
          <button disabled={!reading.trim() || busy !== null}>{busy === "entry" ? "Committing…" : "Commit my reading"}</button>
        </form>
      )}

      {canReview && fact.status === "in_review" && !visible && enteredByMe && (
        <div>
          <p className="small">
            Your reading{committed != null && <> <strong>{committed}</strong></>} is recorded
            {mine?.entered_at && <> ({when(mine.entered_at)})</>}. Open the machine reading to complete your review.
          </p>
          <button className="secondary small" onClick={reveal} disabled={busy !== null}>
            {busy === "reveal" ? "Opening…" : "Show the machine reading"}
          </button>
        </div>
      )}

      {canReview && fact.status === "in_review" && !visible && !enteredByMe && (
        <p className="small" role="note">
          {fact.entered_by ? `${sentenceCase(actorText(fact.entered_by))} entered a reading` : "A reviewer's reading is recorded"}.
          Only that reviewer can see the machine reading and complete the review.
        </p>
      )}

      {visible && (fact.status === "proposed" || fact.status === "in_review") && (
        <Suggestion suggestion={visible} committed={committed} />
      )}

      {canReview && visible && (fact.status === "proposed" || fact.status === "in_review") && (
        <ReviewDecision fact={fact} who={who} suggestion={visible} committed={committed} onChanged={onChanged} />
      )}

      {(fact.status === "reviewed" || fact.status === "confirmed" || fact.status === "rejected") && (
        <dl className="facts">
          <dt>Decision</dt><dd>{DECISION_TEXT[fact.review_decision] ?? status.label}</dd>
          {fact.status !== "rejected" && <><dt>Reviewed value</dt><dd><strong>{fact.reviewed_value ?? "—"}</strong></dd></>}
          <dt>Reviewed</dt><dd>{when(fact.reviewed_at)}{fact.reviewed_by && ` · by ${actorText(fact.reviewed_by)}`}</dd>
          {fact.status === "confirmed" && (
            <><dt>Confirmed</dt><dd>{when(fact.confirmed_at)}{fact.confirmed_by && ` · by ${actorText(fact.confirmed_by)}`}</dd></>
          )}
        </dl>
      )}

      {canConfirm && fact.status === "reviewed" && <ConfirmFact fact={fact} who={who} onChanged={onChanged} />}
      <ErrorBox error={error} />
    </fieldset>
  );
}

function Suggestion({ suggestion, committed }) {
  const value = shownValue(suggestion);
  const agrees = committed != null && value != null && value === committed;
  return (
    <div className="reveal" aria-live="polite">
      <p>
        Machine reading: <strong>{value ?? "none"}</strong>
        {suggestion.confidence != null && ` (confidence ${Math.round(suggestion.confidence * 100)}%, uncalibrated)`}{" "}
        {committed != null && (
          <Badge tone={agrees ? "ok" : "warn"}>{agrees ? "Agrees with your reading" : "Differs from your reading - check the document"}</Badge>
        )}
      </p>
      {committed != null && <p className="small">Your reading: <strong>{committed}</strong></p>}
      {suggestion.candidate_text && suggestion.candidate_text !== value && (
        <p className="muted small">Text the machine read at that spot: <code>{suggestion.candidate_text}</code></p>
      )}
    </div>
  );
}

function ReviewDecision({ fact, who, suggestion, committed, onChanged }) {
  const normalised = suggestion.normalization_status === "NORMALIZED" && suggestion.normalized_value != null;
  const agrees = normalised && committed === suggestion.normalized_value;
  const [decision, setDecision] = useState(agrees || (normalised && committed == null) ? "ACCEPTED" : "CORRECTED");
  const [value, setValue] = useState(committed && committed !== suggestion.normalized_value ? committed : "");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const pendingKey = useRef(null);
  const once = useSingleFlight();
  const edited = (fn) => (e) => { fn(e.target.value); pendingKey.current = null; };

  const corrected = value.trim();
  const valid = decision === "ACCEPTED" ? normalised
    : decision === "CORRECTED" ? Boolean(corrected) && corrected !== suggestion.normalized_value : true;
  const name = `decision-${fact.fact_id}`;

  const submit = (e) => {
    e.preventDefault();
    return once(async () => {
      if (!valid) return;
      setBusy(true);
      setError(null);
      pendingKey.current ??= newIdempotencyKey();
      const body = { decision, ...(decision === "CORRECTED" ? { value: corrected } : {}), ...(note.trim() ? { note: note.trim() } : {}) };
      try {
        await api(who, `/document-facts/${fact.fact_id}/review`, { method: "POST", body, headers: { "Idempotency-Key": pendingKey.current } });
        pendingKey.current = null;
        onChanged?.();
      } catch (err) {
        if (err.status && err.status < 500) pendingKey.current = null;
        setError(err);
      } finally {
        setBusy(false);
      }
    });
  };

  return (
    <form onSubmit={submit} className="review-decision">
      <div role="radiogroup" aria-label={`Decision for ${fieldLabel(fact.field_key)}`} className="choice">
        <label className="inline">
          <input type="radio" name={name} value="ACCEPTED" checked={decision === "ACCEPTED"} disabled={!normalised}
            onChange={edited(setDecision)} />
          Accept the machine reading{normalised ? ` (${suggestion.normalized_value})` : ""}
        </label>
        {!normalised && <p className="muted small">The machine reading could not be put in a standard form, so it must be corrected or rejected.</p>}
        <label className="inline">
          <input type="radio" name={name} value="CORRECTED" checked={decision === "CORRECTED"} onChange={edited(setDecision)} />
          Correct it to the value on the document
        </label>
        <label className="inline">
          <input type="radio" name={name} value="REJECTED" checked={decision === "REJECTED"} onChange={edited(setDecision)} />
          Reject: the document does not support this value
        </label>
      </div>
      {decision === "CORRECTED" && (
        <label>
          Correct value
          <input value={value} onChange={edited(setValue)} autoComplete="off" spellCheck={false} />
        </label>
      )}
      {decision === "CORRECTED" && corrected && corrected === suggestion.normalized_value && (
        <p className="muted small">This is the machine reading unchanged; choose Accept instead.</p>
      )}
      <label>
        Note (optional, kept in the note store)
        <textarea value={note} onChange={edited(setNote)} rows={2} maxLength={4000} />
      </label>
      <p className="muted small four-eyes-ahead" role="note"><Icon name="lock" /> {FOUR_EYES_AHEAD}</p>
      <ErrorBox error={error} />
      <button disabled={!valid || busy}>{busy ? "Saving…" : "Record my review"}</button>
    </form>
  );
}

function ConfirmFact({ fact, who, onChanged }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const pendingKey = useRef(null);
  const once = useSingleFlight();
  const ownReview = fact.reviewed_by?.is_you === true;

  const confirm = () => once(async () => {
    setBusy(true);
    setError(null);
    pendingKey.current ??= newIdempotencyKey();
    try {
      await api(who, `/document-facts/${fact.fact_id}/confirm`, { method: "POST", headers: { "Idempotency-Key": pendingKey.current } });
      pendingKey.current = null;
      onChanged?.();
    } catch (e) {
      if (e.status && e.status < 500) pendingKey.current = null;
      setError(explain(e, {}, CONFIRM_CODES));
    } finally {
      setBusy(false);
    }
  });

  if (ownReview) {
    return <p className="four-eyes" role="note"><Icon name="lock" /> {FOUR_EYES_MESSAGE}</p>;
  }
  return (
    <div className="confirm-fact">
      <p className="small">Check the reviewed value against the document, then confirm it. Confirmed values can drive deadlines and obligations.</p>
      <button onClick={confirm} disabled={busy}>{busy ? "Confirming…" : `Confirm ${fieldLabel(fact.field_key).toLowerCase()}`}</button>
      {error?.code === "FourEyesViolation" ? (
        <div className="alert forbidden four-eyes" role="alert">
          <span className="alert-icon"><Icon name="lock" /></span>
          <span><strong>Refused by the four-eyes rule.</strong> {error.message}</span>
        </div>
      ) : <ErrorBox error={error} />}
    </div>
  );
}

