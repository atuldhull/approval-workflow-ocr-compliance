import { useEffect, useState } from "react";
import { apiFile } from "../api.js";
import { explain, fileSize } from "../recordText.js";
import { VIEWABLE_TYPES } from "./ViewDocument.jsx";
import { ErrorBox } from "./ui.jsx";

const PREVIEW_ERRORS = { 503: "Document storage is unavailable right now, so the page cannot be shown. Try again shortly." };

// The reading surface of the evidence workbench. A scanned image (PNG/JPEG) of a version that passed the malware
// scan is fetched with the caller's own identity (the same content endpoint and type check as View document) and
// shown inline from a blob: URL, which the site's image policy allows; the URL is revoked when the version changes
// or the panel closes. A PDF is not embedded: the page's security policy forbids frames and plug-ins, so a PDF opens
// in its own tab through View document. Nothing is fetched for a version that is not AVAILABLE.
export default function DocumentPreview({ who, version, children, caption }) {
  const image = version && version.status === "AVAILABLE" && String(version.media_type).startsWith("image/");
  const [state, setState] = useState({ url: null, error: null, loading: false });

  useEffect(() => {
    if (!image || typeof URL.createObjectURL !== "function") return undefined;
    let url = null;
    let alive = true;
    setState({ url: null, error: null, loading: true });
    apiFile(who, `/document-versions/${version.version_id}/content`, VIEWABLE_TYPES)
      .then((blob) => {
        if (!alive) return;
        url = URL.createObjectURL(blob);
        setState({ url, error: null, loading: false });
      })
      .catch((e) => alive && setState({ url: null, error: explain(e, PREVIEW_ERRORS), loading: false }));
    return () => {
      alive = false;
      if (url) URL.revokeObjectURL(url);
    };
  }, [who, image, version?.version_id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!version) {
    return (
      <div className="paper paper-empty">
        <p>No version is selected. Choose a version that passed the malware scan to read it here.</p>
      </div>
    );
  }
  return (
    <figure className="paper-frame">
      <div className={`paper${state.url ? " has-image" : ""}`} tabIndex={0} role="region" aria-label={`Reading surface: ${version.original_filename}`}>
        {state.url && <img src={state.url} alt={`Page image of ${version.original_filename}`} />}
        {image && state.loading && <p className="paper-note" role="status">Loading the page image…</p>}
        {state.error && <ErrorBox error={state.error} />}
        {!image && (
          <div className="paper-placard">
            <p className="paper-file">{version.original_filename}</p>
            <p className="paper-note">
              {version.status !== "AVAILABLE"
                ? "This version has not passed the malware scan, so it is never served or shown."
                : "PDF files open in their own tab: this site's security policy does not allow embedded document viewers."}
            </p>
          </div>
        )}
      </div>
      <figcaption>
        <span className="paper-meta">
          <code>{version.original_filename}</code> · {version.media_type} · {fileSize(version.size_bytes)}
        </span>
        {caption}
        {children}
      </figcaption>
    </figure>
  );
}
