import { useEffect, useState } from "react";
import { api } from "../api.js";

export default function NewApplication({ who, onChanged }) {
  const [routes, setRoutes] = useState([]);
  const [category, setCategory] = useState("NEW_PROGRAMME");
  const [year, setYear] = useState("2027-28");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api(who, "/rulesets/aph-2024-27@r1")
      .then((rs) => setRoutes(rs.routes))
      .catch((e) => setError(e.message));
  }, [who]);

  const route = routes.find((r) => r.category === category);

  async function create(e) {
    e.preventDefault();
    setBusy(true);
    try {
      const app = await api(who, "/applications", {
        method: "POST",
        body: { institution_id: who.institution, category, academic_year: year },
      });
      setError(null);
      onChanged(app.id);
    } catch (err) {
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
        <select value={category} onChange={(e) => setCategory(e.target.value)}>
          {routes.map((r) => (
            <option key={r.category} value={r.category}>
              {r.label}
            </option>
          ))}
        </select>
      </label>
      <label>
        Academic year
        <input value={year} onChange={(e) => setYear(e.target.value)} pattern="[0-9]{4}-[0-9]{2}" />
      </label>
      {route && (
        <p className="muted">
          Route: {route.stages.map((s) => (s.when === "as_applicable" ? `(${s.stage})` : s.stage)).join(" → ")}
        </p>
      )}
      {error && <p className="error">{error}</p>}
      <button disabled={busy}>Create draft</button>
    </form>
  );
}
