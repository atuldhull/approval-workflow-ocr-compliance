// Where a fact on screen comes from. This system is not connected to the AICTE portal: nothing it shows is an
// AICTE record, identifier or decision. See docs/handoffs/AICTE_INTEGRATION_READINESS.md.

// Our case identifier. A UUID minted by this system, never an AICTE Application Id or Permanent Id.
export const internalRef = (id) => String(id ?? "").slice(0, 8);
export const INTERNAL_REF_TITLE = "Internal case reference in this system. Not an AICTE Application Id.";

// Identifiers printed on real AICTE letters. None is held by this system yet; they would arrive only through an
// authorised AICTE interface and belong to the workflow module (Person 1).
export const OFFICIAL_REFERENCES = [
  ["AICTE Permanent Id", "Not linked"],
  ["AICTE Application Id", "Not linked"],
  ["AICTE file number", "Not issued in this system"],
];

// Workflow status here is this system's record of the route, not AICTE's decision (which is issued as an LoA, EoA,
// LoD or LoR on the AICTE portal).
export const STATUS_NOTE = "Status in this system. AICTE's decision is issued only through the AICTE portal.";

// Deadline provenance from the deadline API's source_status and clause fields. The frontend never computes dates.
const SOURCES = {
  verified: { tone: "ok", label: "Handbook clause" },
  verified_letter_text: { tone: "ok", label: "Approval-letter text" },
  demo_assumption: { tone: "warn", label: "Demo assumption" },
};

export function deadlineSource(d) {
  const known = SOURCES[d?.source_status];
  const rules = d?.ruleset ? `${d.ruleset}${d.revision ? ` ${d.revision}` : ""}` : null;
  if (!known) {
    return { tone: "neutral", label: "Source not supplied", detail: rules ? `Rule set ${rules}` : "Rule set not supplied" };
  }
  const where = d.source_status === "verified" ? (d.clause ? `APH 2024-27 clause ${d.clause}` : "APH 2024-27, clause not supplied")
    : d.source_status === "verified_letter_text" ? "Wording found in issued approval letters"
    : "No handbook figure; configurable, not an AICTE date";
  return { tone: known.tone, label: known.label, detail: [where, rules && `rule set ${rules}`].filter(Boolean).join(" · ") };
}

// The deadline API does not return the working-day calendar version a deadline used, and AICTE's annual
// public-notice and academic-calendar dates are not modelled yet.
export const CALENDAR_NOTE = "Calendar version: not supplied by the deadline service. AICTE public-notice and academic-calendar dates are not modelled yet.";
