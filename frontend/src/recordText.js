// Plain-language wording for the document, compliance and alert records. Codes stay on the server; the screens
// show these sentences and keep the code only as a secondary detail where an officer may need to quote it.
import { sentence } from "./nav.js";

// Checklist item codes offered for upload. The ruleset does not publish a document checklist yet, so this list
// lives here; the server accepts any code shaped like LAND_DEED and stores it as the document's checklist item.
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
