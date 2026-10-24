import { ROLE_LABELS } from "../nav.js";
import TimeTravel from "./TimeTravel.jsx";

export function Sidebar({ items, current, onNavigate }) {
  return (
    <nav className="sidebar" aria-label="Main">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true">AW</span>
        <span>
          Approval Workflow
          <small>Compliance &amp; alerts</small>
        </span>
      </div>
      <ul>
        {items.map((item) => (
          <li key={item.key}>
            <button
              className={item.key === current ? "nav-item active" : "nav-item"}
              aria-current={item.key === current ? "page" : undefined}
              onClick={() => onNavigate(item.key)}
            >
              {item.label}
              {item.preview && <span className="nav-tag">preview</span>}
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );
}

export function TopBar({ me, who, config, identityControl }) {
  return (
    <header className="topbar">
      <div className="who-am-i">
        <strong>{ROLE_LABELS[me.role] ?? me.role}</strong>
        {me.region && <span className="muted"> · {me.region} region</span>}
        {config.mode === "demo" && <span className="badge warn">DEMO SIGN-IN</span>}
        <span className="badge neutral">Synthetic data</span>
      </div>
      <div className="topbar-actions">
        {config.demo_mode && <TimeTravel who={who} />}
        {identityControl}
      </div>
    </header>
  );
}
