import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api.js";

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

export function Loading({ what = "Loading" }) {
  return (
    <p className="muted" role="status" aria-live="polite">
      {what}…
    </p>
  );
}

export function Empty({ children }) {
  return <p className="empty">{children}</p>;
}

export function ErrorBox({ error, onRetry }) {
  if (!error) return null;
  // 401 and 403 are not fixed by trying again; everything else (network, 5xx) may be
  const retryable = onRetry && error.status !== 401 && error.status !== 403;
  return (
    <div className="alert error" role="alert">
      {error.message || String(error)}
      {retryable && (
        <button className="secondary small retry" onClick={onRetry}>
          Try again
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
      <span className="stat-value">{value}</span>
      <span className="stat-label">{label}</span>
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
            <th scope="row">{k.replaceAll("_", " ")}</th>
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

export function Card({ title, actions, children }) {
  return (
    <section className="card">
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

export const when = (iso) => (iso ? new Date(iso).toLocaleString() : "—");

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
