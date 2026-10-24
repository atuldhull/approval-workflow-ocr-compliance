import { useEffect, useState } from "react";
import { Badge, Card, ErrorBox, Loading, PreviewBanner } from "../components/ui.jsx";
import { fixtureAdapter } from "../integrations/documentReview.js";

// Commit before reveal: the officer reads the page image and types the value BEFORE seeing anything the machine
// produced - no extracted value, no confidence, no highlighted location, no OCR text. Those appear only after the
// officer's reading is committed, so the suggestion cannot anchor their judgement.

export function PageView({ page, synthetic, boxes = [] }) {
  return (
    <figure className="facsimile">
      <div className="facsimile-frame" style={{ aspectRatio: `${page.width} / ${page.height}` }}>
        <img src={page.imageUrl} alt={synthetic ? "Synthetic facsimile of the document page (demo only)" : "Document page"} />
        {boxes.map((b) => (
          <span
            key={b.key}
            className="ocr-box"
            data-testid={`box-${b.key}`}
            style={{
              left: `${(b.x / page.width) * 100}%`,
              top: `${(b.y / page.height) * 100}%`,
              width: `${(b.w / page.width) * 100}%`,
              height: `${(b.h / page.height) * 100}%`,
            }}
          />
        ))}
      </div>
      {synthetic && <figcaption className="small">Synthetic facsimile - demo only, not a real document.</figcaption>}
    </figure>
  );
}

export function FieldReview({ field, onCommit, suggestion }) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const committed = Boolean(suggestion);
  const valid = /^\d{4}-\d{2}-\d{2}$/.test(value);

  async function commit() {
    setBusy(true);
    setError(null);
    try {
      await onCommit(field.key, value);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  const agrees = committed && suggestion.value === value.trim();
  return (
    <fieldset className="ocr-field">
      <legend>{field.label}</legend>
      <label>
        Your reading ({field.format})
        <input value={value} onChange={(e) => setValue(e.target.value)} disabled={committed || busy}
          aria-describedby={`${field.key}-hint`} />
      </label>
      <p id={`${field.key}-hint`} className="muted small">
        Read it from the page image. The machine reading stays hidden until you commit yours.
      </p>
      <ErrorBox error={error} />
      {!committed ? (
        <button type="button" disabled={!valid || busy} onClick={commit}>
          {busy ? "Committing…" : "Commit my reading"}
        </button>
      ) : (
        <div className="reveal" aria-live="polite">
          <p>
            Machine reading: <strong>{suggestion.value ?? "none"}</strong>
            {suggestion.confidence != null && ` (confidence ${Math.round(suggestion.confidence * 100)}%, uncalibrated)`}{" "}
            <Badge tone={agrees ? "ok" : "warn"}>{agrees ? "Agrees with you" : "Differs - check the document"}</Badge>
          </p>
          {suggestion.sourceText && (
            <p className="muted small">
              OCR text at that spot (machine output, shown on the page): <code>{suggestion.sourceText}</code>
            </p>
          )}
        </div>
      )}
    </fieldset>
  );
}

export default function OcrReviewView({ adapter = fixtureAdapter }) {
  const [review, setReview] = useState(null);
  const [error, setError] = useState(null);
  const [suggestions, setSuggestions] = useState({});

  useEffect(() => {
    adapter.loadReview("SAMPLE-LEASE-001").then(setReview).catch(setError);
  }, [adapter]);

  async function commitReading(fieldKey, value) {
    const s = await adapter.commitReading(review.documentId, fieldKey, value);
    setSuggestions((prev) => ({ ...prev, [fieldKey]: s }));
  }

  if (error) return <ErrorBox error={error} />;
  if (!review) return <Loading what="Loading document" />;
  const boxes = Object.entries(suggestions).filter(([, s]) => s.box).map(([key, s]) => ({ key, ...s.box }));
  const allCommitted = review.fields.every((f) => suggestions[f.key]);

  return (
    <div>
      {!adapter.live && <PreviewBanner owner="Person 2" api="document review and fact-confirmation API" />}
      <div className="grid two">
        <Card title={review.title}>
          <PageView page={review.pages[0]} synthetic={review.synthetic} boxes={boxes} />
        </Card>
        <Card title="Your readings">
          {review.fields.map((f) => (
            <FieldReview key={f.key} field={f} onCommit={commitReading} suggestion={suggestions[f.key]} />
          ))}
          <button disabled={!adapter.confirmFact || !allCommitted}
            title={adapter.confirmFact ? undefined : "Saving needs the fact-confirmation API from Person 2"}>
            Confirm facts
          </button>
          {!adapter.confirmFact && <p className="muted small">Nothing is saved until Person 2's confirmation API exists.</p>}
        </Card>
      </div>
    </div>
  );
}
