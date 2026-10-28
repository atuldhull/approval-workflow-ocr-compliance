// Plain-language wording for the workflow, intake, committee and EVC records. The server decides every action and
// refuses with a code; these sentences say what the code means for the person looking at the screen. An unknown
// code falls back to the code itself in readable words, never to a guess about why.
import { sentence } from "./nav.js";

// ---- checklist (GET /rulesets/{key}/checklists/{category}, GET /applications/{id}/checklist) ----

// The ruleset's item keys are DEMO ASSUMPTION stand-ins for Annexure 2. Known keys get a plain label; any other key
// the server sends is shown in readable words.
const ITEM_LABELS = {
  DEMO_CORE_REFERENCE: "Core reference document",
  DEMO_OPTIONAL_REFERENCE: "Optional reference document",
  DEMO_ADDITIONAL_REFERENCE: "Additional reference document",
  DEMO_FACILITY_REFERENCE: "Facility reference document",
  DEMO_STAFF_REFERENCE: "Staff reference document",
  DEMO_SAFETY_REFERENCE: "Safety reference document",
  DSC: "Digital signature certificate (DSC) confirmation",
};
export const itemLabel = (key) => ITEM_LABELS[key] ?? (key ? sentence(key) : "Item not named");

export const missingText = (key) => key === "DSC"
  ? "The digital signature certificate (DSC) has not been confirmed. Tick the DSC box before submitting."
  : `"${itemLabel(key)}" is mandatory and has no document linked yet.`;

// ---- deficiency vocabulary (GET /rulesets/{key}/deficiency-vocabulary) ----
// The item keys and reason codes come from the case's pinned ruleset (DEMO ASSUMPTION). These are only the plain
// labels for the codes known today; a code the server adds later is shown in readable words.
const REASON_LABELS = {
  DEMO_MISSING_EVIDENCE: "Evidence is missing",
  DEMO_REASON: "Other recorded reason",
  DEMO_ACCEPTANCE: "Accepted on review",
  DEMO_RESPONSE_ACCEPTED: "The response is accepted",
  DEMO_RESPONSE_REJECTED: "The response is not sufficient",
};
export const workflowReasonLabel = (code) => REASON_LABELS[code] ?? (code ? sentence(code) : "");

// ---- case actions (available_actions on GET /cases/{id}) ----

export const ACTION_LABELS = {
  submit: "Submit application",
  advance: "Complete this stage",
  advance_to_evc: "Send for expert visit (EVC)",
  advance_to_shc: "Send to the SHC",
  complete_evc: "Complete the expert visit",
  record_deficiency: "Record a deficiency",
  submit_compliance: "Send the compliance response",
  start_rescrutiny: "Start re-scrutiny",
  issue_loa: "Issue Letter of Approval",
  issue_eoa: "Issue Extension of Approval",
  issue_lod: "Issue Letter of Deficiency",
  reject: "Reject the application",
  withdraw: "Withdraw the application",
  revert: "Send back to an earlier stage",
  file_appeal: "File an appeal to the Council",
  close_appeal_window: "Close the lapsed appeal window",
  sac_recommend: "Record SAC recommendation: recommend",
  sac_not_recommend: "Record SAC recommendation: do not recommend",
  sac_refer_scrutiny: "Record SAC referral for Scrutiny",
  sac_refer_evc: "Record SAC referral for an expert visit",
  return_to_sac: "Return to the SAC after referral",
  issue_lor: "Issue Letter of Rejection",
};
export const actionLabel = (action) => ACTION_LABELS[action] ?? sentence(action);

export const LETTER_ACTIONS = { issue_loa: "LOA", issue_eoa: "EOA", issue_lod: "LOD", issue_lor: "LOR" };
// SAC recommendations cite the SAC's latest report, as a letter cites the deciding committee's.
export const DECISION_ACTIONS = new Set(["sac_recommend", "sac_not_recommend", "sac_refer_scrutiny", "sac_refer_evc"]);

// Guard and refusal codes from the workflow engine (backend/app/workflow/guards.py, engine.py, deficiency.py,
// committee.py), intake and the EVC scheduler, in plain words.
export const REASONS = {
  APPEAL_WINDOW_OPEN: "The LoD's appeal window is open: only the institution's appeal, or the window's lapse, can follow.",
  APPEAL_WINDOW_NOT_OPEN: "No appeal window is open on this case.",
  APPEAL_WINDOW_CLOSED: "The 7-day appeal window has passed (APH cl. 1.11(a) / 2.24(a)).",
  APPEAL_WINDOW_STILL_OPEN: "The appeal window has not lapsed yet.",
  APPEAL_NOT_AWAITING_SAC: "The SAC has already recorded its recommendation for this hearing.",
  APPEAL_REFERRED_BACK: "The SAC referred this case back; the decision returns to the SAC and the Council.",
  APPEAL_NOT_REFERRED_BACK: "The SAC has not referred this case back.",
  SAC_RECOMMENDATION_REQUIRED: "The SAC's recommendation must be recorded before the Council's decision.",
  SPEAKING_ORDER_REQUIRED: "A Letter of Rejection needs its speaking order with the specific reasons (APH cl. 1.10(b)).",
  ASSIGNMENT_REQUIRED: "You are not on an active committee for this stage. Form or join the committee for this stage first.",
  EVC_SCHEDULE_NOT_PUBLISHED: "The expert visit has not been published yet. The bureau must publish the visit schedule first.",
  EVC_REQUEST_NOT_ACTIVE: "There is no open expert-visit request for this case (it is not queued, proposed or published).",
  DECISION_NOT_AUTHORISED: "The decision cited is not the latest report of an active committee for this stage.",
  DECISION_CONTEXT_UNAVAILABLE: "No committee decision is on record for this stage, so a letter cannot cite one.",
  LETTER_DATA_NOT_CONFIRMED: "The letter details do not match the confirmed record (academic year or issue date).",
  LETTER_DECISION_MISMATCH: "This letter type does not match the decision this action records.",
  LETTER_DATA_REQUIRED: "The letter details are missing.",
  LETTER_CONTEXT_UNAVAILABLE: "The confirmed letter details could not be read, so the letter was refused.",
  LETTER_ISSUANCE_DISABLED: "Letter issuance is switched off on this server (WF_ENABLE_LETTER_ISSUANCE). Letters are registered from the Compliance screen instead.",
  APPROVAL_POLICY_UNAVAILABLE: "The second-approval policy for this case could not be read, so the action was refused.",
  APPROVAL_CONTEXT_UNAVAILABLE: "A second approver is required, but there is no approver directory to check one against yet.",
  SECOND_APPROVAL_REQUIRED: "A second approver is required for this action.",
  SECOND_APPROVER_MUST_DIFFER: "The second approver must be a different person.",
  GUARD_CONTEXT_UNAVAILABLE: "A fact this action depends on could not be read from the record, so it was refused rather than assumed.",
  INVALID_TRANSITION: "This action does not apply to the case at its current stage.",
  MANDATORY_ITEMS_MISSING: "Mandatory checklist items are missing.",
  CHECKLIST_INCOMPLETE: "The checklist is not complete.",
  APPLICATION_NOT_DRAFT: "The application has already been submitted.",
  OPEN_DEFICIENCY_ITEMS: "Deficiency items are still open. They must all be accepted before this stage can be completed.",
  REASON_CODE_REQUIRED: "Choose a reason for this action.",
  REASON_CODE_INVALID: "The reason chosen is not one this ruleset accepts.",
  REASON_CATALOG_UNAVAILABLE: "The list of reasons could not be read, so the action was refused.",
  DEFICIENCY_ROUND_UNRESOLVED: "A deficiency round is still open or awaiting review.",
  DEFICIENCY_ITEMS_REQUIRED: "Choose at least one deficiency item.",
  DEFICIENCY_ITEMS_DUPLICATED: "The same item was listed twice.",
  DEFICIENCY_ITEM_INVALID: "An item chosen is not in this ruleset's deficiency list.",
  DEFICIENCY_ITEM_ALREADY_ACCEPTED: "An item chosen was already accepted in an earlier round.",
  ITEM_CONTEXT_UNAVAILABLE: "The deficiency items could not be read, so the action was refused.",
  DEFICIENCY_NOT_RESPONDED: "The institution has not responded to the deficiency yet.",
  RESPONSE_REQUIRED: "A response document is needed for each item.",
  RESPONSE_CONTEXT_UNAVAILABLE: "The responses on record could not be read, so the action was refused.",
  NO_OPEN_DEFICIENCY: "There is no open deficiency to respond to.",
  DEFICIENCY_RESPONSES_INCOMPLETE: "Answer every open deficiency item, each exactly once.",
  RESCRUTINY_USES_STORED_RESPONSES: "Re-scrutiny reviews the responses already on record; it does not take new ones.",
  INVALID_REVIEW_STAGE: "Responses can be reviewed only during re-scrutiny.",
  DEFICIENCY_ITEM_NOT_RESPONDED: "An item reviewed has no response to review.",
  NOT_LAST_APPLICABLE_STAGE: "The case is not at the last stage of its route yet.",
  REVERT_TARGET_NOT_VISITED: "The case can only be sent back to a stage it has already been through.",
  ROLE_NOT_ALLOWED: "Your role may not take this action.",
  APPLICABILITY_UNAVAILABLE: "Whether an optional stage applies is not on record yet.",
  AMBIGUOUS_TRANSITION: "More than one route step matches; the rule set needs attention.",
  CLOCK_CONTEXT_UNAVAILABLE: "The deadline clocks for this case could not be read, so the action was refused.",
  VERSION_CONFLICT: "The case changed since you opened it. It has been reloaded; check it and try again.",
  INTAKE_RULESET_NOT_LOADED: "The checklist for this category is not loaded on the server.",
  ITEMS_LOCKED_AFTER_SUBMIT: "The checklist is locked once the application is submitted.",
  INVALID_APPLICATION_ITEMS: "An item sent is not on this category's checklist, or was sent twice.",
  DOCUMENT_REF_UNKNOWN: "The linked document was not found among this application's documents. Link one of its own uploaded versions.",
  DOCUMENT_REF_NOT_AVAILABLE: "The linked document has not passed its virus scan yet (or was rejected). Link a scanned-clean version.",
  COMMITTEE_MEMBERSHIP_REQUIRED: "Only a member of the committee may do this, and you must include yourself when forming one.",
  COMMITTEE_MEMBERS_DUPLICATED: "A member was listed twice.",
  COMMITTEE_CLOSED: "This committee is closed.",
  TASK_ASSIGNEE_NOT_MEMBER: "Tasks can be assigned only to members of this committee.",
  REPORT_PARENT_CONFLICT: "Someone added a report version meanwhile. Reload and write on top of the latest version.",
  EMPTY_COMMITTEE_NOTE: "Write something before saving.",
  // EVC scheduling and pool
  SCHEDULE_RUN_ALREADY_EXISTS: "This proposal run was already made. Start a new proposal.",
  EVC_EXPERT_DOUBLE_BOOKED: "An expert in this run is already published for the same date and half-day elsewhere. Nothing was published.",
  EVC_SLOT_CAPACITY_EXHAUSTED: "A slot in this run is already full with published visits. Nothing was published.",
  EVC_PUBLISH_RECHECK_FAILED: "A proposed panel no longer passes the checks (availability, conflict of interest, region, expertise, panel size or visit window). Nothing was published.",
  EVC_RUN_NOT_PUBLISHABLE: "This run is not awaiting publication (it is already published, or not a proposal).",
  EVC_RUN_NOT_DISCARDABLE: "Only a proposal that is not published can be discarded; this run is already published or discarded.",
  EVC_EXPERT_DAILY_CAP_EXCEEDED: "An expert in this run would make more visits on one day than the daily limit allows. Nothing was published.",
  SCHEDULE_REGION_UNKNOWN: "No expert or visit request names that region. Check the spelling.",
  EVC_RUN_EMPTY: "This run proposes no visits, so there is nothing to publish.",
  EVC_RUN_NOT_FOUND: "This proposal run was not found.",
  EVC_REQUEST_NOT_PROPOSED: "A request in this run is no longer proposed, so the run cannot be published.",
  SCHEDULE_REQUEST_ALREADY_ASSIGNED: "A request already has a proposed or published visit.",
  SCHEDULE_REGION_FORBIDDEN: "Regional officers may plan only their own region.",
  SCHEDULE_CROSS_REGION_SCOPE_FORBIDDEN: "Cross-region planning needs a bureau role.",
  SCHEDULER_HORIZON_BEFORE_CLOCK: "The planning window starts in the past. Start it today or later.",
  SCHEDULER_HORIZON_TOO_LONG: "The planning window is too long.",
  SCHEDULER_HORIZON_INVALID: "The planning window is not valid.",
  EVC_EXPERT_ALREADY_REGISTERED: "This expert reference is already registered.",
  EVC_EXPERT_REGION_FORBIDDEN: "Regional officers manage only experts in their own region.",
  EVC_EXPERT_NOT_FOUND: "That expert is not registered.",
  EVC_INSTITUTION_REFERENCE_NOT_FOUND: "That institution is not known.",
  EXPERT_AVAILABLE_ON_REQUIRED: "Choose a date before filtering by half-day.",
  EVC_DATE_RANGE_INVALID: "The 'from' date is after the 'to' date.",
  SELECTOR_CROSS_REGION_SCOPE_FORBIDDEN: "Cross-region panel previews need a bureau role.",
  SELECTOR_REQUEST_NOT_SCHEDULABLE: "Only queued or proposed requests can be previewed.",
};
export const reasonText = (code) => (code ? REASONS[code] ?? `Refused: ${sentence(code)}.` : null);

// The message for a failed request: the coded reason in plain words when there is one, with the per-item list for a
// missing-checklist refusal; otherwise the client's own message (timeouts, 403 wording, field problems).
export function refusalText(error) {
  if (!error) return null;
  if (error.reason === "MANDATORY_ITEMS_MISSING") {
    const keys = error.body?.missing_item_keys ?? [];
    return keys.length ? `Not submitted. ${keys.map(missingText).join(" ")}` : REASONS.MANDATORY_ITEMS_MISSING;
  }
  if (error.reason && REASONS[error.reason]) return REASONS[error.reason];
  // An unlisted code is shown in readable words; a 403 keeps the client's "Not permitted" wording.
  if (error.reason && error.status !== 403) return reasonText(error.reason);
  return error.message;
}

// An Error for <ErrorBox>: plain text, original status and reason kept (a 403 still reads as a refusal).
export function refusal(error) {
  if (!error) return null;
  const out = new Error(refusalText(error));
  out.status = error.status;
  out.reason = error.reason;
  out.body = error.body;
  return out;
}

// ---- committees ----
export const COMMITTEE_TYPES = ["SCRUTINY", "RESCRUTINY", "EVC", "SHC", "EC", "COUNCIL", "SAC"];
// GF-001 (docs/p1/ASSUMPTIONS.md, DEMO ASSUMPTION): which committee type staffs each stage.
export const STAFFING = {
  SCRUTINY: ["SCRUTINY"], DEFICIENT: ["SCRUTINY", "RESCRUTINY"], RESCRUTINY: ["RESCRUTINY", "SCRUTINY"],
  SELF_DISCLOSURE: ["SCRUTINY"], EVC: ["EVC"], SHC: ["SHC"], EC: ["EC"], COUNCIL: ["COUNCIL"],
  SAC: ["SAC"],
};
export const MEMBER_ROLES = ["CHAIR", "MEMBER", "SECRETARY"];
export const TASK_TITLES = [
  ["REVIEW_DOCUMENTS", "Review the documents"],
  ["REVIEW_RESPONSES", "Review the responses"],
  ["PREPARE_REPORT", "Prepare the report"],
];
export const taskLabel = (key) => TASK_TITLES.find(([k]) => k === key)?.[1] ?? sentence(key);

export const DEFICIENCY_STATE = {
  OPEN: { tone: "warn", label: "Open: response needed" },
  RESPONDED: { tone: "info", label: "Responded: awaiting review" },
  ACCEPTED: { tone: "ok", label: "Accepted" },
  REJECTED: { tone: "bad", label: "Not accepted" },
  CLOSED: { tone: "ok", label: "Closed" },
};
export const deficiencyStateOf = (s) => DEFICIENCY_STATE[s] ?? { tone: "neutral", label: sentence(s) || "State not supplied" };

// ---- EVC ----
export const EVC_STATUS = {
  QUEUED: { tone: "warn", label: "Queued: no visit planned yet" },
  PROPOSED: { tone: "info", label: "Visit proposed, not published" },
  PUBLISHED: { tone: "ok", label: "Visit published" },
  DONE: { tone: "ok", label: "Visit completed" },
  CANCELLED: { tone: "neutral", label: "Cancelled" },
};
export const evcStatusOf = (s) => EVC_STATUS[s] ?? { tone: "neutral", label: sentence(s) || "Status not supplied" };
export const SELECTOR_LABEL = "SIMULATED authorised selector (stand-in)";
export const SELECTOR_NOTE = "Panels are formed by a labelled simulated selector standing in for the authorised selection. "
  + "Under APH 1.8(a) the real selection of experts happens on AICTE's own portal; nothing here appoints anyone.";
export const COI_CODES = [
  ["INSTITUTION_LINK", "Linked to the institution"],
  ["PRIOR_ENGAGEMENT", "Earlier engagement with the institution"],
  ["RECUSAL", "Expert recused"],
];
export const SLOT_PARTS = [["AM", "Morning"], ["PM", "Afternoon"]];
export const slotPartLabel = (p) => SLOT_PARTS.find(([k]) => k === p)?.[1] ?? p;

// Why a request was left out of a proposal (explanation_code, backend/app/evc/explanations.py), judged against the
// final plan. Every unplanned request also carries the umbrella reason NO_FEASIBLE_SLOT.
export const EXPLANATIONS = {
  NO_AVAILABILITY: "no qualified expert declared any free half-day in its visit window.",
  PANEL_INCOMPLETE: "some qualified experts are free, but never enough at the same date and half-day to form a full panel.",
  COI_ONLY: "a full panel is free at some point, but conflicts of interest with the institution always leave it short.",
  CAPACITY_EXHAUSTED: "a conflict-free panel exists, but the slots or the experts' time are taken by other visits.",
  EXPERT_DAILY_CAP: "a free panel exists only if experts made more visits on one day than the daily limit allows.",
  NO_FEASIBLE_SLOT: "no slot in its visit window could take it.",
};
export const explanationText = (code) => EXPLANATIONS[code] ?? (code ? `${sentence(code)}.` : EXPLANATIONS.NO_FEASIBLE_SLOT);

// Timeline events written by the workflow, intake, committee and EVC modules.
export const EVENT_TEXT = {
  "wf.application_created": "Draft created",
  "wf.application_submitted": "Submitted; route fixed",
  "wf.application_item_updated": "Checklist item updated",
  "wf.transition_applied": "Case moved on its route",
  "wf.committee_formed": "Committee formed",
  "wf.task_assigned": "Committee task assigned",
  "wf.observation_added": "Committee observation added",
  "wf.report_version_added": "Committee report version added",
  "wf.deficiency_recorded": "Deficiency recorded",
  "wf.deficiency_item_responded": "Deficiency item answered",
  "wf.compliance_submitted": "Compliance response sent",
  "wf.deficiency_item_decided": "Response reviewed",
  "wf.deficiency_closed": "Deficiency closed",
  "wf.deficiency_superseded": "Deficiency carried to a new round",
  "wf.appeal_window_opened": "Appeal window opened by the LoD",
  "wf.appeal_filed": "Appeal filed",
  "wf.appeal_recommended": "SAC recommendation recorded",
  "wf.appeal_decided": "Council decision on the appeal recorded",
  "wf.appeal_lapsed": "Appeal window lapsed unappealed",
  "dl.deadline_opened": "Deadline started",
  "dl.deadline_paused": "Deadline paused",
  "dl.deadline_resumed": "Deadline resumed with a new due date",
  "dl.deadline_breached": "Deadline passed without being met",
  "dl.deadline_closed": "Deadline closed",
  "wf.stage_entered": "Stage entered",
  "wf.stage_exited": "Stage left",
  "evc.request_created": "Expert visit requested",
  "evc.assignment_proposed": "Expert visit proposed",
  "evc.assignment_published": "Expert visit published",
  "evc.request_completed": "Expert visit completed",
  "evc.request_cancelled": "Expert visit request cancelled",
};
