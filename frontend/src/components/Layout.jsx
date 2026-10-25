import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { ROLE_LABELS } from "../nav.js";
import { Icon, Mark } from "./Icons.jsx";
import TimeTravel from "./TimeTravel.jsx";
import { setMotionPaused, useReducedMotion, motionPaused } from "../motion.js";

// The sidebar: product mark, the role's screens, a sliding active indicator, collapse to a rail.
// On phones (CSS, < 860px) it folds to a top bar; the menu button opens the same list as a sheet.
export function Sidebar({ items, current, onNavigate, collapsed, onToggleCollapse, title, extra }) {
  const listRef = useRef(null);
  const [indicator, setIndicator] = useState(null);
  const [open, setOpen] = useState(false);
  const menuButton = useRef(null);

  useLayoutEffect(() => {
    const el = listRef.current?.querySelector('[aria-current="page"]');
    if (el) setIndicator({ y: el.offsetTop, h: el.offsetHeight });
  }, [current, items, collapsed]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === "Escape") {
        setOpen(false);
        menuButton.current?.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  const go = (key) => {
    setOpen(false);
    onNavigate(key);
  };

  return (
    <nav className={`sidebar${open ? " open" : ""}`} aria-label="Main">
      <div className="brand">
        <Mark />
        <span className="brand-name">
          NEBULA
          <small>AICTE · Approval observatory</small>
        </span>
        <span className="phone-title" aria-hidden="true">{title}</span>
        <button ref={menuButton} className="ghost icon-only menu-button" aria-expanded={open}
          aria-label={open ? "Close menu" : "Open menu"} onClick={() => setOpen((o) => !o)}>
          <Icon name={open ? "close" : "menu"} />
        </button>
      </div>
      <div className="nav-body">
        <ul ref={listRef}>
          {indicator && (
            <span className="nav-indicator" aria-hidden="true"
              style={{ transform: `translateY(${indicator.y}px)`, height: indicator.h }} />
          )}
          {items.map((item) => (
            <li key={item.key}>
              <button
                className={item.key === current ? "nav-item active" : "nav-item"}
                aria-current={item.key === current ? "page" : undefined}
                title={collapsed ? item.label : undefined}
                onClick={() => go(item.key)}
              >
                <Icon name={item.key} />
                <span className="nav-label">{item.label}</span>
                {item.preview && <span className="nav-tag">preview</span>}
              </button>
            </li>
          ))}
        </ul>
        <div className="sheet-extra">{extra}</div>
        <MotionSwitch />
        <button className="ghost collapse-button" aria-pressed={collapsed} onClick={onToggleCollapse}>
          <Icon name={collapsed ? "expand" : "collapse"} />
          <span className="nav-label">{collapsed ? "Expand" : "Collapse sidebar"}</span>
        </button>
      </div>
    </nav>
  );
}

export function TopBar({ me, who, config, identityControl, title, view }) {
  return (
    <header className="topbar">
      <div className="topbar-title">
        <span className="crumb">{ROLE_LABELS[me.role] ?? me.role}{me.region ? ` · ${me.region} region` : ""}</span>
        <span className="crumb-sep" aria-hidden="true">/</span>
        <span key={view} className="crumb-page">{title}</span>
      </div>
      <div className="topbar-context">
        {config.mode === "demo" && <span className="badge warn">DEMO SIGN-IN</span>}
        <span className="badge neutral">Synthetic data</span>
        {config.demo_mode && <TimeTravel who={who} />}
        <div className="identity">{identityControl}</div>
      </div>
    </header>
  );
}

// Pauses every animation loop (pulses, flows, the ledger's slow turn). Hidden when the OS already asks for
// reduced motion, because then nothing loops anyway.
function MotionSwitch() {
  const reduced = useReducedMotion();
  const paused = motionPaused();
  if (reduced && !paused) return null;
  return (
    <button className="ghost collapse-button motion-switch" aria-pressed={paused} onClick={() => setMotionPaused(!paused)}>
      <Icon name={paused ? "play" : "pause"} />
      <span className="nav-label">{paused ? "Play animations" : "Pause animations"}</span>
    </button>
  );
}
