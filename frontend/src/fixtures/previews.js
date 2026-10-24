// SAMPLE DATA for preview screens whose backend is not built yet. Synthetic, never sent anywhere.

export const OCR_SAMPLE = {
  document: "Lease deed (SAMPLE) - Riverbend Institute of Management (DEMO)",
  text: "This lease is granted for a term of thirty years commencing on 01-04-2001 and ending on 31-03-2031, in respect of the land described in Schedule A.",
  fields: [
    { key: "lease_start", label: "Lease start date", span: [63, 73], suggestion: "2001-04-01", confidence: 0.94 },
    { key: "lease_end", label: "Lease end date", span: [88, 98], suggestion: "2031-03-31", confidence: 0.91 },
  ],
};

export const EVC_SAMPLE = [
  { request: "EVC-SAMPLE-01", institution: "Sunrise Institute of Technology (DEMO)", slot: "2027-02-11 10:00", experts: 3, conflicts: 0 },
  { request: "EVC-SAMPLE-02", institution: "Northfield College of Engineering (DEMO)", slot: "2027-02-12 14:00", experts: 3, conflicts: 1 },
];

export const OBLIGATION_SAMPLE = [
  { kind: "AFFIDAVIT", title: "Affidavit 3 with deposit (SAMPLE)", due: "2027-03-15", evidence: "affidavit-sample.pdf", state: "AWAITING_REVIEW" },
  { kind: "UNDERTAKING", title: "Anti-ragging undertaking (SAMPLE)", due: "2027-06-30", evidence: null, state: "OPEN" },
];
