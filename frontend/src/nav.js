// Navigation per role. This only decides what is SHOWN; every request is still authorised by the server
// (backend/app/platform/policy.py), so hiding a link is never the security boundary.

const OFFICERS = ["SCRUTINY_COMMITTEE", "RO_OFFICER", "BUREAU_OFFICER", "BUREAU_HEAD"];
const OVERSIGHT = ["AUDITOR", "BUREAU_OFFICER", "BUREAU_HEAD"];
const EVERYONE = ["INSTITUTION", ...OFFICERS, "AUDITOR"];

export const NAV = [
  { key: "overview", label: "Overview", roles: ["INSTITUTION"] },
  { key: "dashboard", label: "Dashboard", roles: [...OFFICERS, "AUDITOR"] },
  { key: "applications", label: "Cases", institutionLabel: "My applications", roles: EVERYONE },
  { key: "inbox", label: "Inbox", roles: EVERYONE },
  { key: "ocr", label: "Document review", roles: ["SCRUTINY_COMMITTEE", "RO_OFFICER", "BUREAU_OFFICER"], preview: true },
  { key: "evc", label: "EVC scheduling", roles: ["BUREAU_OFFICER", "BUREAU_HEAD"], preview: true },
  { key: "compliance", label: "Compliance", roles: ["INSTITUTION", "RO_OFFICER", "BUREAU_OFFICER", "BUREAU_HEAD"], preview: true },
  { key: "audit", label: "Audit", roles: OVERSIGHT },
  { key: "delivery", label: "Alert delivery", roles: OVERSIGHT },
  { key: "scorecard", label: "Scorecard", roles: OVERSIGHT },
];

export function navFor(role) {
  return NAV.filter((item) => item.roles.includes(role)).map((item) => ({
    ...item,
    label: role === "INSTITUTION" && item.institutionLabel ? item.institutionLabel : item.label,
  }));
}

export const ROLE_LABELS = {
  INSTITUTION: "Institution",
  SCRUTINY_COMMITTEE: "Scrutiny committee",
  RO_OFFICER: "Regional officer",
  BUREAU_OFFICER: "Bureau officer",
  BUREAU_HEAD: "Bureau head",
  AUDITOR: "Auditor",
};

export const humanise = (s) => (s ? s.replaceAll("_", " ").toLowerCase() : "");

const ACRONYMS = /\b(aicte|evc|shc|eoa|aph|nri|ro|ec)\b/g;
export const sentence = (s) => {
  const h = humanise(s)?.replace(ACRONYMS, (m) => m.toUpperCase());
  return h ? h[0].toUpperCase() + h.slice(1) : h;
};
