import { useState } from "react";
import { Badge, Inspector, PreviewBanner } from "../components/ui.jsx";
import { EVC_SAMPLE } from "../fixtures/previews.js";

const DAY_START = 9, DAY_END = 18;
const parse = (slot) => {
  const [d, t] = slot.split(" ");
  const [h, m] = t.split(":").map(Number);
  return { day: d, hour: h + m / 60 };
};
const dayLabel = (iso) => new Intl.DateTimeFormat("en-IN", { timeZone: "UTC", weekday: "short", day: "2-digit", month: "short" }).format(new Date(`${iso}T00:00:00Z`));
// Monday to Friday of the week holding the first sample slot.
function weekOf(slots) {
  const first = new Date(`${slots.map((s) => parse(s.slot).day).sort()[0]}T00:00:00Z`);
  const monday = new Date(first);
  monday.setUTCDate(first.getUTCDate() - ((first.getUTCDay() + 6) % 7));
  return Array.from({ length: 5 }, (_, i) => {
    const d = new Date(monday);
    d.setUTCDate(monday.getUTCDate() + i);
    return d.toISOString().slice(0, 10);
  });
}

// EVC scheduling, a preview: the backend for expert visits does not exist yet, so every slot here is sample data
// from fixtures/previews.js, nothing can be approved, and the screen says so on every surface.
export function EvcView() {
  const [picked, setPicked] = useState(EVC_SAMPLE[0]?.request ?? null);
  const days = weekOf(EVC_SAMPLE);
  const hours = Array.from({ length: DAY_END - DAY_START }, (_, i) => DAY_START + i);
  const chosen = EVC_SAMPLE.find((r) => r.request === picked);
  return (
    <div className="evc">
      <PreviewBanner owner="Person 1" api="EVC scheduling API" />
      <div className="split evc-layout">
        <section className="card evc-week" aria-labelledby="evc-title">
          <header className="card-head">
            <h2 id="evc-title">Proposed visit slots <Badge tone="sample">Sample</Badge></h2>
            <span className="muted small">Week of {dayLabel(days[0])} · times in IST</span>
          </header>
          <div className="calendar" style={{ "--rows": hours.length }}>
            <div className="cal-corner" aria-hidden="true" />
            {days.map((d) => <div key={d} className="cal-day" aria-hidden="true">{dayLabel(d)}</div>)}
            <div className="cal-hours" aria-hidden="true">
              {hours.map((h) => <span key={h}>{String(h).padStart(2, "0")}:00</span>)}
            </div>
            {days.map((d) => (
              <div key={d} className="cal-col">
                {EVC_SAMPLE.filter((r) => parse(r.slot).day === d).map((r) => {
                  const { hour } = parse(r.slot);
                  return (
                    <button key={r.request} className={`cal-slot${r.conflicts ? " has-conflict" : ""}${picked === r.request ? " is-selected" : ""}`}
                      style={{ "--start": hour - DAY_START, "--len": 2 }} aria-pressed={picked === r.request}
                      onClick={() => setPicked(r.request)}
                      aria-label={`Sample slot ${r.slot} IST for ${r.institution}, ${r.experts} experts, ${r.conflicts ? `${r.conflicts} conflict` : "no conflicts"}`}>
                      <span className="cal-time">{r.slot.split(" ")[1]}</span>
                      <span className="cal-inst">{r.institution}</span>
                      <span className="cal-meta">{r.experts} experts{r.conflicts ? ` · ${r.conflicts} conflict` : ""}</span>
                    </button>
                  );
                })}
              </div>
            ))}
          </div>
          <p className="source">Slot length is drawn as two hours for legibility; the sample does not state a duration.</p>
        </section>

        {chosen && (
          <Inspector label="Slot detail" eyebrow="Sample candidate · not confirmed" title={chosen.institution} className="evc-inspector">
            <dl className="facts">
              <dt>Request</dt><dd><code>{chosen.request}</code></dd>
              <dt>Proposed slot</dt><dd>{chosen.slot} IST</dd>
              <dt>Experts</dt><dd>{chosen.experts} (identities not part of the sample)</dd>
              <dt>Conflicts</dt><dd>{chosen.conflicts ? <Badge tone="warn">{chosen.conflicts} conflict</Badge> : <Badge tone="ok">none</Badge>}</dd>
            </dl>
            <div className="actions">
              <button className="small" disabled title="Needs the EVC scheduling API">Approve slot</button>
              <button className="secondary small" disabled title="Needs the EVC scheduling API">Propose another time</button>
            </div>
            <p className="muted small">Approving and rescheduling need the EVC scheduling API, which is not built yet. Nothing here is saved or sent.</p>
          </Inspector>
        )}
      </div>

      <section className="card" aria-labelledby="evc-table-title">
        <header className="card-head"><h2 id="evc-table-title">Proposed EVC slots (sample)</h2></header>
        <div className="table-wrap">
          <table className="table" tabIndex={0}>
            <thead>
              <tr>
                <th scope="col">Request</th>
                <th scope="col">Institution</th>
                <th scope="col">Proposed slot</th>
                <th scope="col" className="num">Experts</th>
                <th scope="col">Conflicts</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {EVC_SAMPLE.map((r) => (
                <tr key={r.request} className={picked === r.request ? "current" : undefined}>
                  <td><code>{r.request}</code></td>
                  <td>{r.institution}</td>
                  <td className="nowrap">{r.slot} IST</td>
                  <td className="num">{r.experts}</td>
                  <td>{r.conflicts ? <Badge tone="warn">{r.conflicts} conflict</Badge> : <Badge tone="ok">none</Badge>}</td>
                  <td>
                    <button className="small" disabled title="Needs the EVC scheduling API">
                      Approve slot
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
