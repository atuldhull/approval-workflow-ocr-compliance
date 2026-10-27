import { useEffect, useRef, useState } from "react";
import { apiFile } from "../api.js";
import { explain } from "../recordText.js";
import { Icon } from "./Icons.jsx";
import { ErrorBox, useSingleFlight } from "./ui.jsx";

// Opens a version's stored file (GET /api/document-versions/{id}/content, docs/SECURITY.md). The API only serves
// versions scanned clean; anything else is a 409 DocumentNotViewable. The file is fetched with the caller's own
// identity headers, so it cannot be a plain link: it becomes a blob: URL opened in a new tab, or offered as a
// download when the browser blocks the tab. Each URL is revoked once the tab has had time to load it, and every
// one still held is revoked when the button goes away.
export const VIEWABLE_TYPES = new Set(["application/pdf", "image/png", "image/jpeg"]);
export const NOT_VIEWABLE_MESSAGE =
  "This version cannot be opened. Only versions that passed the malware scan are served; it may still be waiting for its scan or have been blocked.";
const VIEW_ERRORS = { 503: "Document storage is unavailable right now, so the file cannot be opened. Try again shortly." };
const VIEW_CODES = {
  DocumentNotViewable: NOT_VIEWABLE_MESSAGE,
  StoredContentMismatch: "The stored file no longer matches what was uploaded, so it is not shown. Tell the bureau.",
};
export const REVOKE_AFTER_MS = 60_000;

export default function ViewDocument({ who, versionId, filename, label = "View document" }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [fallback, setFallback] = useState(null);
  const held = useRef(new Set());
  const once = useSingleFlight();

  const revoke = (url) => {
    if (!held.current.delete(url)) return;
    URL.revokeObjectURL(url);
  };
  useEffect(() => () => { for (const url of held.current) URL.revokeObjectURL(url); held.current.clear(); }, []);

  const open = () => once(async () => {
    setBusy(true);
    setError(null);
    if (fallback) { revoke(fallback); setFallback(null); }
    try {
      const blob = await apiFile(who, `/document-versions/${versionId}/content`, VIEWABLE_TYPES);
      const url = URL.createObjectURL(blob);
      held.current.add(url);
      const tab = window.open(url, "_blank");
      if (tab) {
        tab.opener = null;
        setTimeout(() => revoke(url), REVOKE_AFTER_MS);
      } else {
        setFallback(url); // the tab was blocked: offer the file as a download instead
      }
    } catch (e) {
      setError(explain(e, VIEW_ERRORS, VIEW_CODES));
    } finally {
      setBusy(false);
    }
  });

  return (
    <span className="view-document">
      <button type="button" className="ghost small" onClick={open} disabled={busy}
        aria-label={filename ? `${label}: ${filename}` : label}>
        <Icon name="documents" /> {busy ? "Opening…" : label}
      </button>
      {fallback && (
        <a className="small" href={fallback} download={filename || "document"} onClick={() => setTimeout(() => {
          revoke(fallback);
          setFallback(null);
        }, REVOKE_AFTER_MS)}>
          The browser blocked the new tab. Download {filename || "the file"} instead
        </a>
      )}
      <ErrorBox error={error} />
    </span>
  );
}
