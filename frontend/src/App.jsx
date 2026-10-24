import { useCallback, useEffect, useState } from "react";
import { DEMO_USERS, api } from "./api.js";
import NewApplication from "./components/NewApplication.jsx";
import ApplicationList from "./components/ApplicationList.jsx";
import CaseDetail from "./components/CaseDetail.jsx";

export default function App() {
  const [who, setWho] = useState(DEMO_USERS[0]);
  const [apps, setApps] = useState([]);
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const load = useCallback(async () => {
    try {
      setApps(await api(who, "/applications"));
      setError(null);
    } catch (e) {
      setError(e.message);
    }
  }, [who]);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  const changed = (id) => {
    if (id) setSelected(id);
    setRefreshKey((k) => k + 1);
  };

  return (
    <div className="page">
      <header className="top">
        <div>
          <h1>Approval Workflow</h1>
          <p className="sub">Synthetic demo data only</p>
        </div>
        <label className="who">
          Acting as
          <select
            value={who.key}
            onChange={(e) => {
              setWho(DEMO_USERS.find((u) => u.key === e.target.value));
              setSelected(null);
            }}
          >
            {DEMO_USERS.map((u) => (
              <option key={u.key} value={u.key}>
                {u.label}
              </option>
            ))}
          </select>
        </label>
      </header>

      {error && <p className="error">{error}</p>}

      <main className="grid">
        <section>
          {who.role === "INSTITUTION" && <NewApplication who={who} onChanged={changed} />}
          <ApplicationList apps={apps} selected={selected} onSelect={setSelected} />
        </section>
        <section>
          {selected ? (
            <CaseDetail key={`${selected}-${refreshKey}`} who={who} id={selected} onChanged={changed} />
          ) : (
            <p className="muted">Select an application to see its route, clocks and audit timeline.</p>
          )}
        </section>
      </main>
    </div>
  );
}
