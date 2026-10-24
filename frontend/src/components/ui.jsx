import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { Icon, RouteGlyph } from "./Icons.jsx";
import { sentence } from "../nav.js";

// Loads `path` for `who`; reload() fetches again. Pass path=null to skip.
export function useApi(who, path) {
  const [state, setState] = useState({ data: null, error: null, loading: Boolean(path) });
  const load = useCallback(async () => {
    if (!path) return;
    setState((s) => ({ ...s, loading: true }));
    try {
      setState({ data: await api(who, path), error: null, loading: false });
    } catch (e) {
      setState({ data: null, error: e, loading: false });
    }
  }, [who, path]);
  useEffect(() => {
    load();
  }, [load]);
  return { ...state, reload: load };
}

// Loading keeps the shape of what is coming: flat bars at real sizes with a slow pulse, no shimmer.
export function Loading({ what = "Loading", rows = 3 }) {
  return (
    <div className="loading" role="status" aria-live="polite">
      <span className="sr-only">{what}…</span>
      <span className="skeleton sk-title" aria-hidden="true" />
      {Array.from({ length: rows }, (_, i) => (
        <span key={i} className="skeleton sk-row" style={{ "--w": `${92 - i * 14}%` }} aria-hidden="true" />
      ))}
      <span className="loading-text" aria-hidden="true">{what}…</span>
    </div>
  );
}

export function Empty({ children }) {
  return (
    <div className="empty">
      <RouteGlyph />
      <p>{children}</p>
    </div>
  );
}

export function ErrorBox({ error, onRetry }) {
  if (!error) return null;
  if (error.status === 403) {
    // A refusal is a rule, not a failure: calm, explained, no retry.
    return (
      <div className="alert forbidden" role="alert">
        <span className="alert-icon"><Icon name="lock" /></span>
        <span>
          <strong>Not available to your role.</strong> {error.message}
        </span>
      </div>
    );
  }
  // 401 is not fixed by trying again; everything else (network, 5xx) may be
  const retryable = onRetry && error.status !== 401;
  return (
    <div className="alert error" role="alert">
      <span>{error.message || String(error)}</span>
      {retryable && (
        <button className="secondary small retry" onClick={onRetry}>
          <Icon name="refresh" /> Try again
        </button>
      )}
    </div>
  );
}

export function Badge({ tone = "neutral", children }) {
  return <span className={`badge ${tone}`}>{children}</span>;
}

export function NotAvailable({ dependsOn, children }) {
  return (
    <div className="not-available">
      <strong>Not available yet.</strong> {children}
      {dependsOn && <p className="muted">Waiting for: {dependsOn}</p>}
    </div>
  );
}

export function PreviewBanner({ owner, api: apiName }) {
  return (
    <div className="alert preview" role="note">
      <strong>Preview with sample data.</strong> This screen is built and tested, but the backend it needs ({apiName}) is
      still being built by {owner}. Nothing here is saved or sent.
    </div>
  );
}

export function StatTile({ label, value, hint }) {
  return (
    <div className="stat">
      <span className="stat-label">{label}</span>
      <span className="stat-value num">{value}</span>
      {hint && <span className="stat-hint">{hint}</span>}
    </div>
  );
}

// Horizontal bars for a {label: count} map. Plain markup, readable by screen readers.
export function BarList({ data, label }) {
  const entries = Object.entries(data || {});
  if (entries.length === 0) return <Empty>No records.</Empty>;
  const max = Math.max(...entries.map(([, v]) => v), 1);
  return (
    <table className="bars" aria-label={label}>
      <tbody>
        {entries.map(([k, v]) => (
          <tr key={k}>
            <th scope="row">{/^[A-Z0-9_]+$/.test(k) ? sentence(k) : k}</th>
            <td>
              <span className="bar" style={{ width: `${(v / max) * 100}%` }} aria-hidden="true" />
            </td>
            <td className="num">{v}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function Card({ title, actions, children, className = "" }) {
  return (
    <section className={`card ${className}`.trim()}>
      {(title || actions) && (
        <header className="card-head">
          {title && <h2>{title}</h2>}
          {actions}
        </header>
      )}
      {children}
    </section>
  );
}

// All times are shown in Indian Standard Time, whatever the viewer's computer is set to, so they line up with
// due dates (which the deadline engine computes as IST calendar dates).
const IST_DATETIME = new Intl.DateTimeFormat("en-IN", {
  timeZone: "Asia/Kolkata", day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false,
});
const IST_DATE = new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", year: "numeric" });

export const when = (iso) => (iso ? `${IST_DATETIME.format(new Date(iso))} IST` : "—");
export const dateIST = (iso) => (iso ? IST_DATE.format(new Date(iso)) : "—");

// Runs an async action at most once at a time. A ref, not state: two clicks in the same tick both see stale state.
export function useSingleFlight() {
  const inFlight = useRef(false);
  return useCallback(async (fn) => {
    if (inFlight.current) return undefined;
    inFlight.current = true;
    try {
      return await fn();
    } finally {
      inFlight.current = false;
    }
  }, []);
}
