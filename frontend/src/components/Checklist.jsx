import { useEffect, useState } from "react";
import { api } from "../api.js";
import { useActionKey } from "../actionKey.js";
import { isAvailable } from "../recordText.js";
import { itemLabel, missingText, refusal } from "../workflowText.js";
import { Badge, ErrorBox, Loading, useSingleFlight } from "./ui.jsx";

// Every AVAILABLE (scanned clean) document version of a case, labelled for a picker. Versions uploaded under an
// item's own code come first for that item.
export function versionOptions(docs) {
  const out = [];
  for (const d of docs ?? []) {
    for (const v of d.versions ?? []) {
      out.push({ id: v.version_id, docType: d.doc_type, available: isAvailable(v),
        label: `${itemLabel(d.doc_type)} · v${v.version_no} · ${v.original_filename}` });
    }
  }
  return out;
}

export function VersionPicker({ id, value, onChange, options, preferType, label }) {
  const usable = options.filter((o) => o.available);
  const own = usable.filter((o) => o.docType === preferType);
  const other = usable.filter((o) => o.docType !== preferType);
  return (
    <select id={id} value={value ?? ""} onChange={(e) => onChange(e.target.value || null)} aria-label={label}>
      <option value="">No document linked</option>
      {own.length > 0 && <optgroup label="Uploaded for this item">{own.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}</optgroup>}
      {other.length > 0 && <optgroup label="Other documents of this case">{other.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}</optgroup>}
    </select>
  );
}

const nameOf = (options, ref) => options.find((o) => o.id === ref)?.label ?? null;

// The institution's checklist for one application (GET /applications/{id}/checklist). While the application is a
// draft and the viewer is the institution, each item links one of its own uploaded document versions
// (document_ref), the DSC flag is confirmed, and the application is submitted; otherwise it is read-only.
export default function Checklist({ who, me, appId, draft, onChanged, onNavigate }) {
  const [list, setList] = useState(null);
  const [docs, setDocs] = useState(null);
  const [error, setError] = useState(null);
  const [links, setLinks] = useState({});
  const [dsc, setDsc] = useState(false);
  const [busy, setBusy] = useState(null);
  const [failure, setFailure] = useState(null);
  const [saved, setSaved] = useState(false);
  const saveKey = useActionKey();
  const submitKey = useActionKey();
  const once = useSingleFlight();
  const editable = draft && me.role === "INSTITUTION";

  const load = () => Promise.all([
    api(who, `/applications/${appId}/checklist`),
    api(who, `/applications/${appId}/documents`).catch(() => null),
  ]).then(([c, d]) => {
    setList(c);
    setDocs(d);
    setLinks(Object.fromEntries(c.items.map((i) => [i.item_key, i.document_ref])));
    setDsc(c.dsc_present);
  }).catch(setError);
  useEffect(() => { load(); }, [who, appId]); // eslint-disable-line react-hooks/exhaustive-deps

  if (error) return <ErrorBox error={refusal(error)} onRetry={() => { setError(null); load(); }} />;
  if (!list) return <Loading what="Loading the checklist" rows={2} />;

  const options = versionOptions(docs);
  const changes = list.items
    .filter((i) => (links[i.item_key] ?? null) !== (i.document_ref ?? null))
    .map((i) => (links[i.item_key]
      ? { item_key: i.item_key, state: "PROVIDED", document_ref: links[i.item_key] }
      : { item_key: i.item_key, state: "MISSING", document_ref: null }));
  const missingKeys = failure?.reason === "MANDATORY_ITEMS_MISSING" ? failure.body?.missing_item_keys ?? [] : [];
  const stillNeeded = list.items.filter((i) => i.mandatory && !links[i.item_key]).map((i) => i.item_key)
    .concat(list.dsc_required && !dsc ? ["DSC"] : []);

  async function saveItems() {
    if (!changes.length) return;
    const body = { items: changes };
    const key = saveKey.for(JSON.stringify(body));
    try {
      await api(who, `/applications/${appId}/items`, { method: "POST", body, headers: { "Idempotency-Key": key } });
      saveKey.settle(null);
    } catch (e) {
      saveKey.settle(e);
      throw e;
    }
  }

  const save = () => once(async () => {
    setBusy("save");
    setFailure(null);
    try {
      await saveItems();
      setSaved(true);
      await load();
    } catch (e) {
      setFailure(e);
    } finally {
      setBusy(null);
    }
  });

  const submit = () => once(async () => {
    setBusy("submit");
    setFailure(null);
    try {
      await saveItems();
      const body = { dsc_present: dsc };
      const key = submitKey.for(JSON.stringify(body));
      try {
        await api(who, `/applications/${appId}/submit`, { method: "POST", body, headers: { "Idempotency-Key": key } });
        submitKey.settle(null);
      } catch (e) {
        submitKey.settle(e);
        throw e;
      }
      onChanged?.(appId);
    } catch (e) {
      setFailure(e);
      load();
    } finally {
      setBusy(null);
    }
  });

  return (
    <section className="case-zone checklist" aria-labelledby={`cl-${appId}`}>
      <h3 id={`cl-${appId}`}>Checklist</h3>
      <p className="muted small">
        <Badge tone="sample">{list.label}</Badge> Items are stand-ins for Annexure 2 set by the ruleset{" "}
        <code>{list.ruleset_key}</code>{list.pinned ? " (fixed at submission)" : ""}; they are not an official list.
      </p>
      <ul className="checklist-items">
        {list.items.map((item) => {
          const linked = links[item.item_key] ?? null;
          const flagged = missingKeys.includes(item.item_key);
          return (
            <li key={item.item_key} className={`checklist-item${flagged ? " flagged" : ""}`}>
              <div className="checklist-row">
                <span className="checklist-name">
                  <strong>{itemLabel(item.item_key)}</strong> <code className="muted small">{item.item_key}</code>
                </span>
                <span className="checklist-tags">
                  <Badge tone={item.mandatory ? "warn" : "neutral"}>{item.mandatory ? "Mandatory" : "Optional"}</Badge>
                  <Badge tone={item.state === "PROVIDED" ? "ok" : "neutral"}>{item.state === "PROVIDED" ? "Provided" : "Not provided"}</Badge>
                </span>
              </div>
              {editable ? (
                <label className="checklist-pick">
                  <span className="sr-only">Document for {itemLabel(item.item_key)}</span>
                  <VersionPicker value={linked} options={options} preferType={item.item_key} label={`Document for ${itemLabel(item.item_key)}`}
                    onChange={(v) => { setLinks((l) => ({ ...l, [item.item_key]: v })); setSaved(false); }} />
                </label>
              ) : (
                <p className="muted small">{item.document_ref ? `Linked: ${nameOf(options, item.document_ref) ?? "a document version of this case"}` : "No document linked."}</p>
              )}
              {flagged && <p className="error small" role="alert">{missingText(item.item_key)}</p>}
            </li>
          );
        })}
        {list.dsc_required && (
          <li className={`checklist-item${missingKeys.includes("DSC") ? " flagged" : ""}`}>
            {editable ? (
              <label className="inline">
                <input type="checkbox" checked={dsc} onChange={(e) => setDsc(e.target.checked)} required aria-describedby={`dsc-${appId}`} />
                I confirm the application is signed with a valid digital signature certificate (DSC)
              </label>
            ) : (
              <p><strong>DSC</strong> {list.dsc_present ? <Badge tone="ok">Confirmed</Badge> : <Badge tone="neutral">Not confirmed</Badge>}</p>
            )}
            <p id={`dsc-${appId}`} className="muted small">Required for this category. The server records only that you confirmed it.</p>
            {missingKeys.includes("DSC") && <p className="error small" role="alert">{missingText("DSC")}</p>}
          </li>
        )}
      </ul>
      {editable && (
        <>
          {options.every((o) => !o.available) && (
            <p className="muted small">
              No scanned-clean document yet. Upload the documents under{" "}
              {onNavigate ? <button type="button" className="link-button" onClick={() => onNavigate("documents", { caseId: appId })}>My documents</button> : "My documents"},
              then link them here.
            </p>
          )}
          {stillNeeded.length > 0 && !failure && (
            <p className="muted small" aria-live="polite">Still needed before submitting: {stillNeeded.map(itemLabel).join(", ")}.</p>
          )}
          <ErrorBox error={refusal(failure)} />
          {failure && (saveKey.pending() || submitKey.pending()) && (
            <p className="muted small">Trying again sends the same request, so it cannot be applied twice.</p>
          )}
          {saved && !changes.length && !failure && <p className="ok small" role="status">Checklist saved.</p>}
          <div className="actions">
            <button type="button" onClick={submit} disabled={Boolean(busy)}>{busy === "submit" ? "Submitting…" : "Submit application"}</button>
            <button type="button" className="secondary" onClick={save} disabled={Boolean(busy) || !changes.length}>
              {busy === "save" ? "Saving…" : "Save checklist"}
            </button>
          </div>
        </>
      )}
    </section>
  );
}
