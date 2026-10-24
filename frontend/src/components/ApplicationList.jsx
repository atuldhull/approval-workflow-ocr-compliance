export default function ApplicationList({ apps, selected, onSelect }) {
  return (
    <div className="card">
      <h2>Applications</h2>
      {apps.length === 0 && <p className="muted">None yet.</p>}
      <ul className="list">
        {apps.map((a) => (
          <li key={a.id}>
            <button className={a.id === selected ? "row active" : "row"} onClick={() => onSelect(a.id)}>
              <span>{a.category.replaceAll("_", " ").toLowerCase()}</span>
              <span className={`badge ${a.status.toLowerCase()}`}>{a.current_stage ?? a.status}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
