import { useEffect, useRef, useState } from "react";
import { api, newIdempotencyKey } from "../api.js";

export default function NewApplication({ who, institution, onChanged }) {
  const [routes, setRoutes] = useState([]);
  const [category, setCategory] = useState("NEW_PROGRAMME");
  const [year, setYear] = useState("2027-28");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const pendingKey = useRef(null); // reused if this same submission is retried after a failure

  useEffect(() => {
    api(who, "/rulesets/aph-2024-27@r1")
      .then((rs) => setRoutes(rs.routes))
      .catch((e) => setError(e.message));
  }, [who]);

  const route = routes.find((r) => r.category === category);
  const edited = (setter) => (e) => {
    setter(e.target.value);
    pendingKey.current = null; // a different request needs a different key
  };

  async function create(e) {
    e.preventDefault();
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
    <form className="card" onSubmit={create}>
      <h2>New application</h2>
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
        <input value={year} onChange={edited(setYear)} pattern="[0-9]{4}-[0-9]{2}" required />
      </label>
      {route && (
        <p className="muted">
          Route: {route.stages.map((s) => (s.when === "as_applicable" ? `(${s.stage})` : s.stage)).join(" → ")}
        </p>
      )}
      {error && <p className="error" role="alert">{error}</p>}
      <button disabled={busy}>{busy ? "Creating…" : "Create draft"}</button>
    </form>
  );
}
