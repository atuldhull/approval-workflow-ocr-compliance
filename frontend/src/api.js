// Demo users. Real sign-in (Keycloak) replaces these; the backend refuses them when DEMO_AUTH=false.
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
  { key: "auditor", label: "Auditor", user: "00000000-0000-4000-9000-000000000003", role: "AUDITOR" },
];

export class ApiError extends Error {
  constructor(status, detail) {
    super(detail);
    this.status = status;
  }
}

export async function api(who, path, { method = "GET", body } = {}) {
  const headers = { "X-Demo-User": who.user, "X-Demo-Role": who.role };
  if (who.institution) headers["X-Demo-Institution"] = who.institution;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const res = await fetch(`/api${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = typeof data?.detail === "string" ? data.detail : JSON.stringify(data?.detail ?? res.statusText);
    throw new ApiError(res.status, detail);
  }
  return data;
}
