import { humanise } from "../nav.js";

export default function ApplicationList({ apps, selected, onSelect }) {
  return (
    <div className="card">
      <h2>Applications</h2>
      {apps.length === 0 && <p className="empty">None yet.</p>}
      <ul className="list">
        {apps.map((a) => (
          <li key={a.id}>
            <button
              className={a.id === selected ? "row active" : "row"}
              aria-pressed={a.id === selected}
              onClick={() => onSelect(a.id)}
            >
              <span>
                {humanise(a.category)} <small className="muted">{a.academic_year}</small>
              </span>
              <span className={`badge ${a.status.toLowerCase()}`}>{a.current_stage ?? a.status}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
