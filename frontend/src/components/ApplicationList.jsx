import { useMemo, useState } from "react";
import { sentence } from "../nav.js";
import { stageLabel } from "./RouteJourney.jsx";
import { dateIST } from "./ui.jsx";

const FILTERS = [
  ["all", "All"],
  ["IN_PROCESS", "In process"],
  ["DRAFT", "Drafts"],
];

// The case list as an operations table: a reference to tell cases apart, the stage in words, the date
// filed. Filters and sort re-order the rows; the counts on the chips are computed from the rows shown.
export default function ApplicationList({ apps, selected, onSelect }) {
  const [filter, setFilter] = useState("all");
  const [newestFirst, setNewestFirst] = useState(true);
  const rows = useMemo(() => {
    const kept = apps.filter((a) => filter === "all" || a.status === filter);
    return [...kept].sort((a, b) => (newestFirst ? -1 : 1) * a.created_at.localeCompare(b.created_at));
  }, [apps, filter, newestFirst]);
  const count = (f) => (f === "all" ? apps.length : apps.filter((a) => a.status === f).length);

  return (
    <section className="card cases" aria-labelledby="cases-title">
      <header className="card-head">
        <h2 id="cases-title">Applications <span className="count num">{apps.length}</span></h2>
        <button className="ghost small" onClick={() => setNewestFirst((v) => !v)} aria-label={`Sort by date filed, ${newestFirst ? "newest" : "oldest"} first`}>
          {newestFirst ? "Newest first" : "Oldest first"}
        </button>
      </header>
      <div className="chips" role="group" aria-label="Filter by status">
        {FILTERS.map(([key, label]) => (
          <button key={key} className={`chip${filter === key ? " on" : ""}`} aria-pressed={filter === key} onClick={() => setFilter(key)}>
            {label} <span className="num">{count(key)}</span>
          </button>
        ))}
      </div>
      {apps.length === 0 && <p className="empty">None yet.</p>}
      {apps.length > 0 && rows.length === 0 && <p className="muted">No applications with this status.</p>}
      <ul className="list" key={`${filter}-${newestFirst}`}>
        {rows.map((a, i) => (
          <li key={a.id} style={{ "--row": i }}>
            <button className={a.id === selected ? "row active" : "row"} aria-pressed={a.id === selected} onClick={() => onSelect(a.id)}>
              <span className="row-main">
                <span className="row-title">{sentence(a.category)}</span>
                <span className="row-sub muted">
                  <code>{a.id.slice(0, 8)}</code> · {a.academic_year} · filed {dateIST(a.created_at)}
                </span>
              </span>
              <span className={`badge ${a.status === "DRAFT" ? "draft" : "in_process"}`}>
                {a.current_stage ? stageLabel(a.current_stage) : sentence(a.status)}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
