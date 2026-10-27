import { useMemo, useState } from "react";
import { sentence } from "../nav.js";
import { stageLabel } from "./RouteJourney.jsx";
import { dateIST } from "./ui.jsx";
import { INTERNAL_REF_TITLE, internalRef } from "../provenance.js";

const FILTERS = [
  ["all", "All"],
  ["IN_PROCESS", "In process"],
  ["DRAFT", "Drafts"],
];

// The case list: a reference to tell cases apart, the stage in words, the date filed (or started, for a draft). Status filters and a text
// filter narrow the rows; counts on the chips are computed from the rows the server returned.
export default function ApplicationList({ apps, selected, onSelect }) {
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [newestFirst, setNewestFirst] = useState(true);
  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const kept = apps.filter((a) => (filter === "all" || a.status === filter)
      && (!q || internalRef(a.id).includes(q) || sentence(a.category).toLowerCase().includes(q) || String(a.academic_year).includes(q)));
    return [...kept].sort((a, b) => (newestFirst ? -1 : 1) * String(a.created_at).localeCompare(String(b.created_at)));
  }, [apps, filter, query, newestFirst]);
  const count = (f) => (f === "all" ? apps.length : apps.filter((a) => a.status === f).length);

  return (
    <section className="card cases" aria-labelledby="cases-title">
      <header className="card-head">
        <h2 id="cases-title">Applications <span className="count num">{apps.length}</span></h2>
        <button className="ghost small" onClick={() => setNewestFirst((v) => !v)} aria-label={`Sort by date started, ${newestFirst ? "newest" : "oldest"} first`}>
          {newestFirst ? "Newest first" : "Oldest first"}
        </button>
      </header>
      <div className="list-tools">
        <div className="chips" role="group" aria-label="Filter by status">
          {FILTERS.map(([key, label]) => (
            <button key={key} className={`chip${filter === key ? " on" : ""}`} aria-pressed={filter === key} onClick={() => setFilter(key)}>
              {label} <span className="num">{count(key)}</span>
            </button>
          ))}
        </div>
        {apps.length > 3 && (
          <label className="list-search">
            <span className="sr-only">Find a case by reference, category or year</span>
            <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Find by reference, category or year" autoComplete="off" />
          </label>
        )}
      </div>
      {apps.length === 0 && <p className="empty">None yet.</p>}
      {apps.length > 0 && rows.length === 0 && <p className="muted small">No applications match.</p>}
      <ul className="list case-rows" key={`${filter}-${newestFirst}`}>
        {rows.map((a, i) => (
          <li key={a.id} style={{ "--row": i }}>
            <button className={a.id === selected ? "row active" : "row"} aria-pressed={a.id === selected} onClick={() => onSelect(a.id)}>
              <span className={`row-status ${a.status === "DRAFT" ? "draft" : "live"}`} aria-hidden="true" />
              <span className="row-main">
                <span className="row-title">{sentence(a.category)}</span>
                <span className="row-sub">
                  <code title={INTERNAL_REF_TITLE}>{internalRef(a.id)}</code>{a.academic_year ? ` · ${a.academic_year}` : ""}{a.submitted_at ? ` · filed ${dateIST(a.submitted_at)}` : a.created_at ? ` · started ${dateIST(a.created_at)}` : ""}
                </span>
              </span>
              <span className={`badge ${a.status === "DRAFT" ? "draft" : "info"}`}>
                {a.current_stage ? stageLabel(a.current_stage) : sentence(a.status)}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
