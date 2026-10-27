import { useEffect, useRef, useState } from "react";
import { api, newIdempotencyKey } from "../api.js";
import { useSingleFlight } from "./ui.jsx";
import { stageLabel } from "./RouteJourney.jsx";
import { itemLabel } from "../workflowText.js";

const RULESET = "aph-2024-27@r1";

export default function NewApplication({ who, institution, onChanged }) {
  const [routes, setRoutes] = useState([]);
  const [category, setCategory] = useState("NEW_PROGRAMME");
  const [year, setYear] = useState("2027-28");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [checklist, setChecklist] = useState(null);
  const pendingKey = useRef(null); // reused if this same submission is retried after a failure
  const once = useSingleFlight();

  useEffect(() => {
    api(who, `/rulesets/${RULESET}`)
      .then((rs) => setRoutes(rs.routes))
      .catch((e) => setError(e.message));
  }, [who]);

  // What the chosen category will ask for (GET /rulesets/{key}/checklists/{category}), before a draft exists.
  useEffect(() => {
    let live = true;
    setChecklist(null);
    api(who, `/rulesets/${RULESET}/checklists/${category}`).then((c) => live && setChecklist(c)).catch(() => live && setChecklist(null));
    return () => { live = false; };
  }, [who, category]);

  const route = routes.find((r) => r.category === category);
  const edited = (setter) => (e) => {
    setter(e.target.value);
    pendingKey.current = null; // a different request needs a different key
  };

  const create = (e) => {
    e.preventDefault();
    return once(() => send());
  };

  async function send() {
    setBusy(true);
    pendingKey.current ??= newIdempotencyKey();
    try {
      const app = await api(who, "/applications", {
        method: "POST",
        body: { institution_id: institution, category, academic_year: year },
        headers: { "Idempotency-Key": pendingKey.current },
      });
      pendingKey.current = null;
      setError(null);
      onChanged(app.id);
    } catch (err) {
      if (err.status && err.status < 500) pendingKey.current = null; // a rejected request is not retried as-is
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card new-application" onSubmit={create} aria-labelledby="new-app-title">
      <h2 id="new-app-title">New application</h2>
      <div className="new-app-fields">
      <label>
        Nature of application
        <select value={category} onChange={edited(setCategory)}>
          {routes.map((r) => (
            <option key={r.category} value={r.category}>
              {r.label}
            </option>
          ))}
        </select>
      </label>
      <label>
        Academic year
        <input name="academic_year" autoComplete="off" spellCheck={false} value={year} onChange={edited(setYear)} pattern="[0-9]{4}-[0-9]{2}" required />
      </label>
      <button disabled={busy}>{busy ? "Creating…" : "Create draft"}</button>
      </div>
      {route && (
        <p className="muted small">
          Prescribed route: {route.stages.map((s) => (s.when === "as_applicable" ? `${stageLabel(s.stage)} (if applicable)` : stageLabel(s.stage))).join(" → ")}
        </p>
      )}
      {checklist && (
        <p className="muted small checklist-preview">
          Checklist ({checklist.label}): {checklist.items.map((i) => `${itemLabel(i.item_key)}${i.mandatory ? "" : " (optional)"}`).join(", ")}
          {checklist.dsc_required ? ", and a DSC confirmation" : ""}. You link your uploaded documents to it before submitting.
        </p>
      )}
      {error && <p className="error" role="alert">{error}</p>}
    </form>
  );
}
