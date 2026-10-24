import { useEffect, useState } from "react";
import { api } from "../api.js";

// Demo-only: moves the system clock forward so deadlines and ageing can be shown. The server refuses it
// unless DEMO_MODE is on, and this control is only rendered when the server reports demo mode.
export default function TimeTravel({ who }) {
  const [clock, setClock] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api(who, "/sim/clock").then(setClock).catch((e) => setError(e.message));
  }, [who]);

  async function advance(days) {
    try {
      setClock(await api(who, "/sim/clock", { method: "POST", body: { days } }));
      setError(null);
      window.dispatchEvent(new Event("awoc:clock-changed"));
    } catch (e) {
      setError(e.message);
    }
  }

  return (
    <div className="time-travel" aria-label="Demo time travel">
      <span className="badge warn">SIMULATED TIME</span>
      <span className="muted">
        {clock ? new Date(clock.now).toLocaleDateString() : "…"}
        {clock?.offset_days ? ` (+${Math.round(clock.offset_days)} d)` : ""}
      </span>
      <button className="secondary small" onClick={() => advance(7)}>
        +7 days
      </button>
      <button className="secondary small" onClick={() => advance(30)}>
        +30 days
      </button>
      {error && <span className="error small">{error}</span>}
    </div>
  );
}
