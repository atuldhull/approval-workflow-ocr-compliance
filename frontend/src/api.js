import { accessToken, clearSession } from "./auth/oidc.js";

export const SESSION_EXPIRED = "awoc:session-expired";

// In real sign-in mode a 401 means the session is over: drop it and let the app return to the sign-in screen.
function endSession(who) {
  if (who?.mode !== "oidc") return;
  clearSession();
  window.dispatchEvent(new Event(SESSION_EXPIRED));
}

// Demo users - only offered when the backend reports demo sign-in (DEMO_AUTH=true).
// In real sign-in mode the backend refuses these headers outright.
export const DEMO_USERS = [
  {
    key: "sunrise",
    label: "Institution - Sunrise Institute of Technology (DEMO)",
    user: "00000000-0000-4000-9000-000000000001",
    role: "INSTITUTION",
    institution: "00000000-0000-4000-8000-000000000001",
  },
  {
    key: "northfield",
    label: "Institution - Northfield College of Engineering (DEMO)",
    user: "00000000-0000-4000-9000-000000000004",
    role: "INSTITUTION",
    institution: "00000000-0000-4000-8000-000000000002",
  },
  { key: "scrutiny", label: "Scrutiny committee", user: "00000000-0000-4000-9000-000000000002", role: "SCRUTINY_COMMITTEE" },
  {
    key: "ro-southern",
    label: "Regional officer - Southern",
    user: "00000000-0000-4000-9000-000000000005",
    role: "RO_OFFICER",
    region: "Southern",
  },
  { key: "bureau-officer", label: "Bureau officer", user: "00000000-0000-4000-9000-000000000006", role: "BUREAU_OFFICER" },
  { key: "bureau-head", label: "Bureau head", user: "00000000-0000-4000-9000-000000000007", role: "BUREAU_HEAD" },
  { key: "auditor", label: "Auditor", user: "00000000-0000-4000-9000-000000000003", role: "AUDITOR" },
];

export class ApiError extends Error {
  constructor(status, detail) {
    super(detail);
    this.status = status;
  }
}

// `who` is either a DEMO_USERS entry or { mode: "oidc", config } for a signed-in user.
async function identityHeaders(who) {
  if (who?.mode === "oidc") {
    const token = await accessToken(who.config);
    if (!token) {
      endSession(who);
      throw new ApiError(401, "Your session has ended. Please sign in again.");
    }
    return { Authorization: `Bearer ${token}` };
  }
  const headers = { "X-Demo-User": who.user, "X-Demo-Role": who.role };
  if (who.institution) headers["X-Demo-Institution"] = who.institution;
  if (who.region) headers["X-Demo-Region"] = who.region;
  return headers;
}

// A request that has not answered by then is abandoned, so no screen waits forever.
export const REQUEST_TIMEOUT_MS = 20_000;

export async function api(who, path, { method = "GET", body, headers: extra = {}, timeoutMs = REQUEST_TIMEOUT_MS } = {}) {
  const headers = { ...(await identityHeaders(who)), ...extra };
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), timeoutMs);
  let res;
  try {
    res = await fetch(`/api${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), signal: abort.signal });
  } catch {
    // A change that timed out may still have been applied; say so rather than invite a blind retry.
    const write = method !== "GET";
    throw new ApiError(0, abort.signal.aborted
      ? (write ? "The server did not answer in time. The change may or may not have been saved; refresh before trying again."
        : "The server did not answer in time. Try again shortly.")
      : "The server cannot be reached. Check your connection and try again.");
  } finally {
    clearTimeout(timer);
  }
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    let detail = typeof data?.detail === "string" ? data.detail : JSON.stringify(data?.detail ?? res.statusText);
    if (res.status === 401) {
      detail = "Your session has ended or is not valid. Please sign in again.";
      endSession(who);
    }
    if (res.status === 403) detail = `Not permitted: ${detail}`;
    if (res.status === 503) detail = "A security service is unavailable, so the request was refused. Try again shortly.";
    if (res.status === 502 || res.status === 504) detail = "The server is unavailable right now. Try again shortly.";
    throw new ApiError(res.status, detail);
  }
  return data;
}

export async function publicApi(path) {
  const res = await fetch(`/api${path}`);
  if (!res.ok) throw new ApiError(res.status, res.statusText);
  return res.json();
}

// A fresh key per user action; a retry of the same action reuses it (see docs/IDEMPOTENCY.md).
export const newIdempotencyKey = () => crypto.randomUUID();
