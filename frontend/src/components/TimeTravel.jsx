import { useEffect, useState } from "react";
import { api } from "../api.js";
import { dateIST, useSingleFlight } from "./ui.jsx";

// Fired after the demo timer run, so open screens (alerts) fetch again.
export const TIMERS_RAN = "awoc:timers-ran";

// Demo-only: moves the system clock forward so deadlines and ageing can be shown, and runs the deadline timers
// straight away instead of waiting for the worker. The server refuses both unless DEMO_MODE is on, and this
// control is only rendered when the server reports demo mode.
export default function TimeTravel({ who }) {
  const [clock, setClock] = useState(null);
  const [error, setError] = useState(null);
  const [ran, setRan] = useState(null);
  const [running, setRunning] = useState(false);
  const once = useSingleFlight();

  useEffect(() => {
    api(who, "/sim/clock").then(setClock).catch((e) => setError(e.message));
  }, [who]);

  async function advance(days) {
    try {
      setClock(await api(who, "/sim/clock", { method: "POST", body: { days } }));
      setError(null);
      setRan(null);
      window.dispatchEvent(new Event("awoc:clock-changed"));
    } catch (e) {
      setError(e.message);
    }
  }

  const runTimers = () => once(async () => {
    setRunning(true);
    try {
      const out = await api(who, "/sim/timers/run", { method: "POST" });
      setRan(out.processed);
      setError(null);
      window.dispatchEvent(new Event(TIMERS_RAN));
    } catch (e) {
      setError(e.message);
    } finally {
      setRunning(false);
    }
  });

  return (
    <div className="time-travel" aria-label="Demo time travel">
      <span className="badge warn">SIMULATED TIME</span>
      <span className="muted">
        {clock ? `${dateIST(clock.now)} (IST)` : "…"}
        {clock?.offset_days ? ` (+${Math.round(clock.offset_days)} d)` : ""}
      </span>
      <button className="secondary small" onClick={() => advance(7)}>
        +7 days
      </button>
      <button className="secondary small" onClick={() => advance(30)}>
        +30 days
      </button>
      <button className="secondary small" onClick={runTimers} disabled={running}>
        {running ? "Running timers…" : "Run timers now"}
      </button>
      <span className="muted small" role="status">{ran != null ? `Timers ran: ${ran} processed` : ""}</span>
      {error && <span className="error small">{error}</span>}
    </div>
  );
}
