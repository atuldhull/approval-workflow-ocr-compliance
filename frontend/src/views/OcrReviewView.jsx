import { useState } from "react";
import { Badge, Card, PreviewBanner } from "../components/ui.jsx";
import { OCR_SAMPLE } from "../fixtures/previews.js";

// Commit before reveal: the officer types what the document says BEFORE seeing the machine's reading, so the
// suggestion cannot anchor their judgement. Only then are both shown side by side.
export function FieldReview({ field, text, onDone }) {
  const [value, setValue] = useState("");
  const [committed, setCommitted] = useState(false);
  const [start, end] = field.span;
  const matches = committed && value.trim() === field.suggestion;

  return (
    <fieldset className="ocr-field">
      <legend>{field.label}</legend>
      <p className="ocr-text">
        {text.slice(0, start)}
        <mark>{text.slice(start, end)}</mark>
        {text.slice(end)}
      </p>
      <label>
        Your reading (YYYY-MM-DD)
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          disabled={committed}
          pattern="\d{4}-\d{2}-\d{2}"
          aria-describedby={`${field.key}-hint`}
        />
      </label>
      <p id={`${field.key}-hint`} className="muted small">
        The machine suggestion stays hidden until you commit your own reading.
      </p>
      {!committed ? (
        <button type="button" disabled={!/^\d{4}-\d{2}-\d{2}$/.test(value)} onClick={() => { setCommitted(true); onDone?.(); }}>
          Commit my reading
        </button>
      ) : (
        <div className="reveal" aria-live="polite">
          Machine suggestion: <strong>{field.suggestion}</strong> (confidence {Math.round(field.confidence * 100)}%, uncalibrated){" "}
          <Badge tone={matches ? "ok" : "warn"}>{matches ? "Agrees with you" : "Differs - check the document"}</Badge>
        </div>
      )}
    </fieldset>
  );
}

export default function OcrReviewView() {
  return (
    <div>
      <PreviewBanner owner="Person 2" api="document facts and confirmation API" />
      <Card title={OCR_SAMPLE.document}>
        {OCR_SAMPLE.fields.map((f) => (
          <FieldReview key={f.key} field={f} text={OCR_SAMPLE.text} />
        ))}
        <button disabled title="Saving needs the fact-confirmation API from Person 2">
          Confirm facts
        </button>
      </Card>
    </div>
  );
}
