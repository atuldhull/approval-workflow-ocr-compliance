// Static, illustrative material for the public showcase. Nothing here is fetched and nothing here is a case.
//
// ROUTES is copied from rulesets/aph-2024-27/r1/routes.yaml (ruleset aph-2024-27, revision r1, Table 2.3 plus the
// Chapter I new-institution route). It is a snapshot for illustration: the workspace reads the live rule set from
// the API, and that remains the source of truth.

export const RULESET = { id: "aph-2024-27", revision: "r1", source: "APH 2024-25 to 2026-27, Table 2.3 (p. 30)" };

const S = "SCRUTINY";
const FULL = [S, "EVC", "SHC?"];

// "SHC?" marks a stage the rule set lists with `when: as_applicable`.
export const ROUTES = [
  { key: "NEW_PROGRAMME", label: "New programme / level in existing institution", stages: FULL },
  { key: "NEW_INSTITUTION", label: "Setting up a new institution", stages: [S, "EVC", "SHC?", "EC", "COUNCIL"], note: "Chapter I route (sections 1.3–1.12), not part of Table 2.3" },
  { key: "INCREASE_INTAKE", label: "Increase in intake / additional course(s)", stages: FULL },
  { key: "CHANGE_OF_NAME", label: "Change of name of institution / affiliating university / board / type", stages: [S] },
  { key: "EOA_SELF_DISCLOSURE", label: "Extension of Approval based on self-disclosure", stages: ["SELF_DISCLOSURE"] },
  { key: "NRI_SEATS", label: "Introduction/continuation of NRI seats", stages: ["SELF_DISCLOSURE"] },
  { key: "CONVERSION_LEVEL", label: "Conversion diploma to degree level or vice versa", stages: FULL },
  { key: "MERGER", label: "Merger of institutions", stages: FULL },
  { key: "RESTORATION", label: "EoA after a break / restoration of intake / hibernation", stages: FULL },
  { key: "SUPERNUMERARY_SEATS", label: "Supernumerary seats (foreign nationals / OCI / children of Indian workers in Gulf)", stages: [S] },
  { key: "INTEGRATED_DUAL", label: "Integrated / dual degree course", stages: FULL },
  { key: "FELLOW_PROGRAMME", label: "Fellow Programme in Management", stages: FULL },
  { key: "COURSE_CHANGE_REDUCTION", label: "Change of course name / merger of courses / reduction in intake", stages: [S] },
  { key: "COLLABORATION_TWINNING", label: "Collaboration and twinning programme", stages: FULL },
  { key: "CHANGE_OF_SITE", label: "Change of site / location", stages: FULL },
  { key: "CLOSURE_INSTITUTION", label: "Closure of the institution", stages: [S] },
  { key: "CONVERSION_COED", label: "Conversion women's to co-ed institution or vice versa", stages: [S] },
  { key: "CLOSURE_PROGRAMME", label: "Closure of programme(s) / course(s)", stages: [S] },
  { key: "BANK_DETAILS", label: "Change in bank details", stages: [S] },
  { key: "TRUST_NAME", label: "Change of name of trust / society / company", stages: [S] },
  { key: "DEEMED_UNIVERSITY", label: "Conversion into a deemed-to-be university", stages: FULL },
  { key: "ODL", label: "Online Learning / ODL courses", stages: FULL },
];

// Quick picks: one of each route shape, so the difference between shapes is one click away.
export const ROUTE_PICKS = ["EOA_SELF_DISCLOSURE", "CHANGE_OF_NAME", "NEW_PROGRAMME", "NEW_INSTITUTION"];

// What this repository can show about each stage. `built` is what the prototype actually implements; anything
// else is labelled. `actor` is filled only where the rule set names one; otherwise it says so.
export const STAGE_INFO = {
  SUBMITTED: {
    title: "Application submitted",
    purpose: "The institution files its application with the checklist documents for the chosen category.",
    evidence: "Checklist documents, each version malware-scanned before it can be used.",
    actor: "Institution (files and submits)",
    built: "built",
    builtNote: "Drafting, submission and document upload run in the workspace.",
  },
  SELF_DISCLOSURE: {
    title: "Self-disclosure",
    purpose: "The institution declares its particulars; the rule set lists no scrutiny stage for this category.",
    evidence: "The institution's own declaration and supporting documents.",
    actor: "Not named in the rule set",
    built: "illustrative",
    builtNote: "The stage is in the rule set; no stage-specific tooling is built for it.",
  },
  SCRUTINY: {
    title: "Scrutiny",
    purpose: "The application is checked against the checklist. Open deficiencies must be closed before the stage completes.",
    evidence: "Checklist documents and the facts confirmed from them by two officers.",
    actor: "Scrutiny committee (records deficiencies, per the rule set's transitions)",
    built: "built",
    builtNote: "Deficiency, compliance response and re-scrutiny transitions run in the workflow.",
  },
  EVC: {
    title: "Expert visit (EVC)",
    purpose: "An expert visit committee inspects the institution.",
    evidence: "Visit schedule and report (scheduling is a preview with sample slots).",
    actor: "Regional officer constitutes the committee (rule set: evc_constituted_by)",
    built: "preview",
    builtNote: "EVC scheduling is a labelled preview; its API is not built.",
  },
  SHC: {
    title: "SHC · as applicable",
    purpose: "Listed by the rule set as applicable exactly where an EVC is required. It may not apply to every case.",
    evidence: "Not modelled in this prototype.",
    actor: "Not named in the rule set",
    built: "illustrative",
    builtNote: "Conditional stage in the route; no dedicated tooling.",
  },
  EC: {
    title: "Executive Committee (EC)",
    purpose: "Part of the Chapter I new-institution route after the visit stages.",
    evidence: "Not modelled in this prototype.",
    actor: "Not named in the rule set",
    built: "illustrative",
    builtNote: "Stage in the route; no dedicated tooling.",
  },
  COUNCIL: {
    title: "Council",
    purpose: "Final stage of the Chapter I new-institution route.",
    evidence: "Not modelled in this prototype.",
    actor: "Not named in the rule set",
    built: "illustrative",
    builtNote: "Stage in the route; no dedicated tooling.",
  },
  RECORDED: {
    title: "Outcome recorded here",
    purpose: "This system records where its own route ends. The decision itself is issued only through the AICTE portal.",
    evidence: "Approval letters uploaded by officers create compliance obligations.",
    actor: "Officers record; AICTE decides on its own portal",
    built: "built",
    builtNote: "Letters and obligations run in the compliance screens.",
  },
};

export const BUILT_LABEL = { built: "Built in this prototype", preview: "Preview · sample data", illustrative: "Illustrative · in rule set only" };

// Expand a route into the stage stations the journey draws.
export function routeStations(route) {
  const stages = route.stages.map((s) => {
    const conditional = s.endsWith("?");
    const code = conditional ? s.slice(0, -1) : s;
    return { code, conditional, ...STAGE_INFO[code] };
  });
  return [{ code: "SUBMITTED", conditional: false, ...STAGE_INFO.SUBMITTED }, ...stages, { code: "RECORDED", conditional: false, ...STAGE_INFO.RECORDED }];
}

// From rulesets/aph-2024-27/r1/deadlines.yaml. Status words follow provenance.js.
export const CLOCKS = [
  { id: "AICTE_PROCESSING", kind: "Internal clock", owner: "AICTE side (alerts go to the regional officer)", days: 30, source: "demo", anchor: "Application submitted", note: "Paused while a deficiency is open; resumed on the compliance response." },
  { id: "INSTITUTION_RESPONSE", kind: "Internal clock", owner: "Institution", days: 15, source: "demo", anchor: "Deficiency recorded", note: "Stopped when the institution submits its compliance." },
  { id: "APPEAL_7D", kind: "Legal deadline", owner: "Institution", days: 7, source: "verified", clause: "2.24(a)", anchor: "Adverse decision uploaded", note: "Never paused. Calendar vs working days is not confirmed. Reminder only: not appealing is a choice, not a breach." },
];

export const SOURCE_LABEL = { verified: "Handbook clause", demo: "Demo assumption", letter: "Approval-letter text" };

// deadlines.yaml, alerts.ladders.standard. Every offset and role is a configurable demo assumption.
export const LADDER = [
  { level: 0, to: "Owner of the deadline", at: "2 days before due", template: "Reminder" },
  { level: 1, to: "Regional officer", at: "When due", template: "Breached" },
  { level: 2, to: "Bureau officer", at: "3 days after", template: "Escalated" },
  { level: 3, to: "Bureau head", at: "7 days after", template: "Escalated" },
];

export const CHAPTERS = [
  { id: "challenge", n: "01", title: "The Challenge" },
  { id: "route", n: "02", title: "A Route for Every Application" },
  { id: "evidence", n: "03", title: "Documents into Evidence" },
  { id: "deadlines", n: "04", title: "Deadlines and Responsibility" },
  { id: "audit", n: "05", title: "Trust Through Audit" },
  { id: "workspace", n: "06", title: "Enter the Workspace" },
];

// Guided tour: one step per beat. `target` is a chapter id or the hero; `hero` scrolls within the hero span.
export const TOUR = [
  { target: "top", title: "The dossier", say: "An application arrives as a bundle of documents. Scroll, or press Next, to open it." },
  { target: "hero-open", title: "From papers to evidence", say: "Each sheet becomes something a person can review, with fields marked for checking." },
  { target: "challenge", title: "01 The Challenge", say: "Twenty-two categories, three kinds of clocks, many hands. The problem is coordination, not paperwork." },
  { target: "route", title: "02 A Route for Every Application", say: "Pick a category: its stages come from the rule set. Conditional stages appear only where the route has them." },
  { target: "evidence", title: "03 Documents into Evidence", say: "A person types their reading before the machine's proposal is revealed. A second officer confirms." },
  { target: "deadlines", title: "04 Deadlines and Responsibility", say: "Every clock says who owns it and where its length comes from: handbook clause or demo assumption." },
  { target: "audit", title: "05 Trust Through Audit", say: "Three separate checks: continuity, signed checkpoints, replay. None stands in for another." },
  { target: "workspace", title: "06 Enter the Workspace", say: "The tour ends here. The workspace runs on the real API with synthetic data." },
];

export const TOUR_STEP_MS = 17000;
