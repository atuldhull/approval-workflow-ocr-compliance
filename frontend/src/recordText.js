// Plain-language wording for the document, compliance and alert records. Codes stay on the server; the screens
// show these sentences and keep the code only as a secondary detail where an officer may need to quote it.
import { ROLE_LABELS, sentence } from "./nav.js";

// Checklist item codes offered for upload. There is no checklist endpoint on the server: which documents a case
// needs depends on ruleset data (rulesets/) that does not list them yet, so until it does this list lives here.
// The server accepts any code shaped like LAND_DEED and stores it as the document's checklist item, so nothing
// here is enforced; replace this list with the server's once the ruleset publishes one.
export const CHECKLIST = [
  ["LAND_DEED", "Land ownership or registered lease deed"],
  ["BUILDING_PLAN", "Approved building plan"],
  ["BUILDING_COMPLETION", "Building completion certificate"],
  ["FIRE_NOC", "Fire safety no-objection certificate"],
  ["AFFIDAVIT", "Affidavit on stamp paper"],
  ["UNDERTAKING", "Signed undertaking"],
  ["FDR_DEPOSIT", "Fixed deposit receipt (security deposit)"],
  ["APPROVAL_LETTER", "Approval letter issued for the institution"],
];
export const checklistLabel = (code) => CHECKLIST.find(([c]) => c === code)?.[1] ?? (code ? sentence(code) : "No checklist item");

// What each malware-scan state means for the person looking at it.
export const SCAN = {
  scan_pending: { tone: "warn", label: "Waiting for malware scan",
    meaning: "Held in quarantine until the scanner checks it. It cannot be reviewed or used as evidence yet." },
  clean: { tone: "ok", label: "Scanned clean",
    meaning: "No malware was found. This version can be reviewed and used as evidence." },
  infected: { tone: "bad", label: "Blocked by malware scan",
    meaning: "The scanner found a threat. This version stays in quarantine and can never be used; upload a fresh copy." },
};
export const scanOf = (status) => SCAN[status] ?? { tone: "neutral", label: "Scan state not supplied", meaning: "The server did not report a scan state." };

// A version's own status decides what may be done with it: only AVAILABLE versions can be viewed, reviewed or
// used as evidence. The scan wording explains why a version is in that status.
export const VERSION_STATE = { QUARANTINED: SCAN.scan_pending, AVAILABLE: SCAN.clean, REJECTED: SCAN.infected };
export const versionStateOf = (v) => VERSION_STATE[v?.status] ?? scanOf(v?.scan_status);
export const isAvailable = (v) => v?.status === "AVAILABLE";

// Who reviewed or confirmed a fact, as the server reports it ({role, is_you}); never a user id.
export function actorText(actor) {
  if (!actor) return null;
  if (actor.is_you) return "you";
  const role = ROLE_LABELS[actor.role] ?? (actor.role ? sentence(actor.role) : null);
  return role ? `another officer (${role.toLowerCase()})` : "another officer";
}

export const FIELD_LABELS = {
  lease_end_date: "Lease end date",
  letter_issue_date: "Letter issue date",
  letter_file_number: "Letter file number",
};
export const fieldLabel = (key) => FIELD_LABELS[key] ?? sentence(key);

export const FACT_STATUS = {
  proposed: { tone: "neutral", label: "Awaiting a reviewer" },
  in_review: { tone: "warn", label: "Reviewer's reading entered" },
  reviewed: { tone: "warn", label: "Reviewed, awaiting confirmation" },
  rejected: { tone: "bad", label: "Rejected by the reviewer" },
  confirmed: { tone: "ok", label: "Confirmed by a second officer" },
};
export const factStatusOf = (s) => FACT_STATUS[s] ?? { tone: "neutral", label: sentence(s) || "Status not supplied" };

export const LETTER_TYPES = [
  ["LOA", "Letter of Approval (LoA)"],
  ["EOA", "Extension of Approval (EoA)"],
  ["LOD", "Letter of Deficiency (LoD)"],
  ["LOR", "Letter of Rejection (LoR)"],
  ["CORRIGENDUM", "Corrigendum"],
];
export const letterLabel = (t) => LETTER_TYPES.find(([c]) => c === t)?.[1] ?? sentence(t);

export const OBLIGATION_STATUS = {
  OPEN: { tone: "warn", label: "Open: evidence needed" },
  EVIDENCE_SUBMITTED: { tone: "neutral", label: "Evidence awaiting verification" },
  MET: { tone: "ok", label: "Met: evidence accepted" },
};
export const obligationStatusOf = (s) => OBLIGATION_STATUS[s] ?? { tone: "neutral", label: sentence(s) || "Status not supplied" };

export const EVIDENCE_STATUS = {
  SUBMITTED: { tone: "neutral", label: "Awaiting an officer" },
  ACCEPTED: { tone: "ok", label: "Accepted" },
  REJECTED: { tone: "bad", label: "Rejected" },
};
export const evidenceStatusOf = (s) => EVIDENCE_STATUS[s] ?? { tone: "neutral", label: sentence(s) || "Status not supplied" };

// Mirrors backend/app/compliance/vocab.py RejectionReason (a proposed list, pending team approval).
export const REASON_CODES = [
  ["DOCUMENT_ILLEGIBLE", "The document cannot be read"],
  ["DOCUMENT_INCOMPLETE", "Pages or sections are missing"],
  ["WRONG_DOCUMENT", "This is not the document the obligation asks for"],
  ["AMOUNT_MISMATCH", "The amount does not match what is required"],
  ["DATE_MISMATCH", "A date does not match the record"],
  ["DOCUMENT_EXPIRED", "The document has expired"],
  ["SIGNATURE_OR_ATTESTATION_MISSING", "A signature or attestation is missing"],
  ["OTHER_SEE_NOTE", "Another reason, explained in the note"],
];
export const reasonLabel = (code) => REASON_CODES.find(([c]) => c === code)?.[1] ?? (code ? sentence(code) : "");

export const ORIGIN = {
  OFFICER_CONFIRMED: "Created from a fact an officer confirmed",
  RULE_DEFAULT: "Created by the configured rules for this letter type",
};

export const ALERT_STATUS = {
  OPEN: { tone: "warn", label: "Open" },
  ESCALATED: { tone: "bad", label: "Escalated to the next level" },
  ACKNOWLEDGED: { tone: "ok", label: "Acknowledged" },
  VACANT: { tone: "neutral", label: "No one holds this role" },
};
export const alertStatusOf = (s) => ALERT_STATUS[s] ?? { tone: "neutral", label: sentence(s) || "Status not supplied" };

// Deadline rules in rulesets/aph-2024-27, in plain words. Unknown ids fall back to the id itself, readable.
export const RULES = {
  AICTE_PROCESSING: "AICTE's processing time for a submitted application",
  INSTITUTION_RESPONSE: "Institution's time to answer a deficiency",
  APPEAL_7D: "Seven days to appeal a decision",
  DEPOSIT_15D: "Fifteen days to pay the security deposit",
  EOA_DEFICIENCY_6M: "Six months to clear the deficiencies an EoA lists",
  LEASE_EOA_STOP: "Last year an extension can be granted before the lease ends",
  LOA_DEPOSIT_AFFIDAVIT_15D: "Fifteen days after an LoA for the deposit proof and affidavit",
  NO_ADMISSION_AFFIDAVIT_7D: "Seven days for the no-admission affidavit",
  LOA_VALIDITY_2Y: "The LoA's two-year validity",
};
export const ruleLabel = (id) => RULES[id] ?? (id ? sentence(id) : "Rule not supplied");

export const ALERT_REASON = {
  WINDOW_ELAPSED: "The previous level was not acknowledged in time.",
  VACANCY: "Nobody held the role the previous level was addressed to.",
};

export const ALERT_TEMPLATES = {
  "deadline.reminder": "A deadline is approaching.",
  "deadline.breached": "A deadline has passed.",
  "deadline.escalated": "An overdue deadline has been escalated.",
  "obligation.due": "A compliance item is due.",
};
export const alertMeaning = (t) => ALERT_TEMPLATES[t] ?? "A deadline alert from the approval system.";

const KB = 1024;
export const fileSize = (n) => (n == null ? "—" : n < KB ? `${n} B` : n < KB * KB ? `${(n / KB).toFixed(1)} KB` : `${(n / KB / KB).toFixed(1)} MB`);

// Replaces a server error's message with a plain one for this screen, keeping its status (so a 403 still reads as
// a refusal) and code. The api client's generic wording for 503 is about security services, which is wrong for
// a scanner, storage or text-reader outage.
export function explain(error, byStatus = {}, byCode = {}) {
  if (!error) return error;
  const message = byCode[error.code] ?? byStatus[error.status];
  if (!message) return error;
  const out = new Error(message);
  out.status = error.status;
  out.code = error.code;
  return out;
}
