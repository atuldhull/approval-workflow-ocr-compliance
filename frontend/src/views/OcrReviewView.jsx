import { useEffect, useState } from "react";
import { Badge, Card, ErrorBox, Loading, PreviewBanner, useSingleFlight } from "../components/ui.jsx";
import { confirmedAll, fixtureAdapter } from "../integrations/documentReview.js";
import { Icon } from "../components/Icons.jsx";
import { useReducedMotion } from "../motion.js";

// Commit before reveal: the officer reads the page image and types the value BEFORE seeing anything the machine
// produced - no extracted value, no confidence, no highlighted location, no OCR text. Those appear only after the
// officer's reading is committed, so the suggestion cannot anchor their judgement.

// 3D (CSS): the page lies on a short stack of sheets and tilts a few degrees with the pointer, like a
// document on an inspection table. After a reading is committed, its machine box lifts off the page toward
// the viewer. Zoom (a button, so keyboards have it too) enlarges the page inside its frame. Reduced motion
// and phones get the flat page; the boxes still appear, without the lift.
export function PageView({ page, synthetic, boxes = [] }) {
  const reduced = useReducedMotion();
  const [tilt, setTilt] = useState({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(false);
  const onMove = (e) => {
    if (reduced || zoom) return;
    const r = e.currentTarget.getBoundingClientRect();
    setTilt({ x: ((e.clientY - r.top) / r.height - 0.5) * -5, y: ((e.clientX - r.left) / r.width - 0.5) * 7 });
  };
  return (
    <figure className="facsimile">
      <div className="inspect-tools">
        <button className="ghost small" aria-pressed={zoom} onClick={() => setZoom((z) => !z)}>
          <Icon name="zoom" /> {zoom ? "Fit page" : "Zoom in"}
        </button>
      </div>
      <div className={`inspect-stage${zoom ? " zoomed" : ""}`} onPointerMove={onMove} onPointerLeave={() => setTilt({ x: 0, y: 0 })}>
        <div className="inspect-page" style={{ "--tx": `${tilt.x}deg`, "--ty": `${tilt.y}deg` }}>
          <span className="sheet s2" aria-hidden="true" />
          <span className="sheet s1" aria-hidden="true" />
          <div className="facsimile-frame" style={{ aspectRatio: `${page.width} / ${page.height}` }}>
            <img src={page.imageUrl} width={page.width} height={page.height} alt={synthetic ? "Synthetic facsimile of the document page (demo only)" : "Document page"} />
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
        </div>
      </div>
      {synthetic && <figcaption className="small">Synthetic facsimile - demo only, not a real document.</figcaption>}
    </figure>
  );
}

export function FieldReview({ field, onCommit, suggestion, choice, onChoose, locked }) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const committed = Boolean(suggestion);
  const valid = /^\d{4}-\d{2}-\d{2}$/.test(value);

  async function commit() {
    setBusy(true);
    setError(null);
    try {
      await onCommit(field.key, value.trim());
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
          name={`reading-${field.key}`} autoComplete="off" spellCheck={false} placeholder="2031-03-31…"
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
          {!agrees && suggestion.value && (
            <div role="radiogroup" aria-label={`Value to confirm for ${field.label}`} className="choice">
              <label className="inline">
                <input type="radio" name={`${field.key}-choice`} checked={choice !== "MACHINE"} disabled={locked}
                  onChange={() => onChoose(field.key, "OFFICER")} />
                Keep my reading ({value.trim()})
              </label>
              <label className="inline">
                <input type="radio" name={`${field.key}-choice`} checked={choice === "MACHINE"} disabled={locked}
                  onChange={() => onChoose(field.key, "MACHINE")} />
                Use the machine reading ({suggestion.value}) after checking the page
              </label>
            </div>
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
  const [readings, setReadings] = useState({});
  const [choices, setChoices] = useState({});
  const [confirm, setConfirm] = useState({ state: "idle", error: null });
  const once = useSingleFlight();

  useEffect(() => {
    adapter.loadReview("SAMPLE-LEASE-001").then(setReview).catch(setError);
  }, [adapter]);

  async function commitReading(fieldKey, value) {
    const s = await adapter.commitReading(review.documentId, fieldKey, value);
    setReadings((prev) => ({ ...prev, [fieldKey]: value }));
    setSuggestions((prev) => ({ ...prev, [fieldKey]: s }));
  }

  // One request for all fields; success only if the server confirms every one of them.
  const confirmFacts = () => once(async () => {
    const decisions = review.fields.map((f) => {
      const source = choices[f.key] === "MACHINE" && suggestions[f.key]?.value ? "MACHINE" : "OFFICER";
      return { fieldKey: f.key, value: source === "MACHINE" ? suggestions[f.key].value : readings[f.key], source };
    });
    setConfirm({ state: "saving", error: null });
    try {
      const result = await adapter.confirmFacts(review.documentId, decisions);
      if (!confirmedAll(decisions, result)) throw new Error("The server did not confirm every field. Nothing is treated as saved; try again.");
      setConfirm({ state: "done", error: null });
    } catch (e) {
      setConfirm({ state: "idle", error: e });
    }
  });

  if (error) return <ErrorBox error={error} />;
  if (!review) return <Loading what="Loading document" />;
  const boxes = Object.entries(suggestions).filter(([, s]) => s.box).map(([key, s]) => ({ key, ...s.box }));
  const allCommitted = review.fields.every((f) => suggestions[f.key]);

  return (
    <div>
      {!adapter.live && <PreviewBanner owner="Person 2" api="document review and fact-confirmation API" />}
      <div className="grid two evidence-layout">
        <Card title={review.title}>
          <PageView page={review.pages[0]} synthetic={review.synthetic} boxes={boxes} />
        </Card>
        <Card title="Your readings">
          {review.fields.map((f) => (
            <FieldReview key={f.key} field={f} onCommit={commitReading} suggestion={suggestions[f.key]}
              choice={choices[f.key]} locked={confirm.state !== "idle"}
              onChoose={(key, source) => setChoices((prev) => ({ ...prev, [key]: source }))} />
          ))}
          <ErrorBox error={confirm.error} />
          {confirm.state === "done" ? (
            <p className="ok" role="status">Facts confirmed by the server.</p>
          ) : (
            <button onClick={confirmFacts} disabled={!adapter.confirmFacts || !allCommitted || confirm.state === "saving"}
              title={adapter.confirmFacts ? undefined : "Saving needs the fact-confirmation API from Person 2"}>
              {confirm.state === "saving" ? "Confirming…" : "Confirm facts"}
            </button>
          )}
          {!adapter.confirmFacts && <p className="muted small">Nothing is saved until Person 2's confirmation API exists.</p>}
        </Card>
      </div>
    </div>
  );
}
