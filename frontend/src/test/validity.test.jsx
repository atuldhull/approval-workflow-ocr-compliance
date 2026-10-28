import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DEMO_USERS } from "../api.js";
import ComplianceView from "../views/ComplianceView.jsx";
import DocumentsView from "../views/DocumentsView.jsx";
import OverviewView from "../views/OverviewView.jsx";
import { fakeServer } from "./fakeServer.js";

const user = (key) => DEMO_USERS.find((u) => u.key === key);
const SUNRISE = user("sunrise");
const RO = user("ro-southern");
const AUDITOR = user("auditor");
const ME = (u) => ({ user_id: u.user, role: u.role, region: u.region ?? null, institution_id: u.institution ?? null });

const APP = "aaaaaaaa-0000-4000-8000-000000000001";
const APPS = [{ id: APP, institution_id: SUNRISE.institution, category: "NEW_PROGRAMME", academic_year: "2027-28", status: "IN_PROCESS" }];

const record = (extra = {}) => ({
  id: "vr-1", application_id: APP, institution_id: SUNRISE.institution, region: "Southern", kind: "DOCUMENT_VALIDITY",
  source_letter_id: null, source_clause: "6.17(a)", source_status: "verified", state_origin: "OFFICER_CONFIRMED",
  rule_id: "DOCUMENT_EXPIRY", deadline_id: "dl-1", due_date: "2046-10-27", status: "OPEN", met_at: null, evidence: [],
  deadline_status: "RUNNING", overdue: false, document_id: "doc-lease", document_version_id: "ver-lease-1",
  document_version_no: 1, doc_type: "LEASE_DEED", valid_until: "2046-10-27", validity_basis: "DOCUMENT_FACT",
  validity_state: "VALID", days_left: 7304, eoa_stop_year: "2042-43", live_lease_ok: true, title: null,
  evidence_required: null, penalty_notes: [], ...extra,
});
const FIRE = record({ id: "vr-2", source_clause: "6.17(i)", doc_type: "FIRE_NOC", document_id: "doc-fire",
  document_version_id: "ver-fire-1", valid_until: "2026-11-20", due_date: "2026-11-20", validity_state: "EXPIRING_SOON",
  days_left: 23, eoa_stop_year: null, live_lease_ok: null, validity_basis: "OFFICER_RECORDED" });
const SSC = record({ id: "vr-3", source_clause: "6.17(h)", doc_type: "STRUCTURAL_STABILITY", document_id: "doc-ssc",
  valid_until: "2026-10-01", validity_state: "EXPIRED", days_left: -27, overdue: true, deadline_status: "BREACHED",
  eoa_stop_year: null, live_lease_ok: null, validity_basis: "APH_PERIOD" });
const RENEWED = record({ id: "vr-0", status: "MET", validity_state: "RENEWED", document_version_id: "ver-lease-0" });

const version = (id, no, status = "AVAILABLE") => ({ version_id: id, document_id: "x", version_no: no, original_filename: `${id}.pdf`,
  media_type: "application/pdf", size_bytes: 10, sha256: "ab".repeat(32), status, scan_status: status === "AVAILABLE" ? "clean" : "scan_pending",
  uploaded_at: "2026-10-20T10:00:00Z", scanned_at: null });
const DOCS = [
  { document_id: "doc-ssc", application_id: APP, doc_type: "STRUCTURAL_STABILITY", versions: [version("ver-ssc-1", 1)] },
  { document_id: "doc-aff", application_id: APP, doc_type: "AFFIDAVIT", versions: [version("ver-aff-1", 1)] },
  { document_id: "doc-fire", application_id: APP, doc_type: "FIRE_NOC", versions: [version("ver-fire-2", 2), version("ver-fire-1", 1)] },
];

describe("document validity panel", () => {
  it("lists each tracked document with its expiry, days left, source and the lease's EoA stop year", async () => {
    fakeServer({ "GET /api/compliance/letters": [], "GET /api/compliance/obligations": [record(), FIRE, SSC, RENEWED] });
    render(<ComplianceView who={SUNRISE} me={ME(SUNRISE)} onNavigate={() => {}} />);
    const table = await screen.findByRole("table", { name: "Document validity" });
    const rows = within(table).getAllByRole("row").slice(1);
    // expired first, then expiring soon, then valid; the renewed record is summarised, not listed
    expect(rows.map((r) => within(r).getAllByRole("cell")[4].textContent)).toEqual(["Expired", "Expiring soon", "Valid"]);
    expect(within(rows[0]).getByText("Expired 27 days ago")).toBeInTheDocument();
    expect(within(rows[0]).getByText(/APH cl. 6.17\(h\): five years from the issue date/)).toBeInTheDocument();
    expect(within(rows[1]).getByText("23 days left")).toBeInTheDocument();
    expect(within(rows[1]).getByText(/Recorded by an officer from the document/)).toBeInTheDocument();
    expect(within(rows[2]).getByText(/No extension of approval from 2042-43/)).toBeInTheDocument();
    expect(within(rows[2]).getByText(/From the document, confirmed by two officers/)).toBeInTheDocument();
    expect(screen.getByText(/1 earlier record was met by an accepted renewal/)).toBeInTheDocument();
    expect(screen.getByText(/demo assumptions/)).toBeInTheDocument();
  });

  it("sends the institution to upload a renewal with the document type chosen", async () => {
    const onNavigate = vi.fn();
    const u = userEvent.setup();
    fakeServer({ "GET /api/compliance/letters": [], "GET /api/compliance/obligations": [FIRE] });
    render(<ComplianceView who={SUNRISE} me={ME(SUNRISE)} onNavigate={onNavigate} />);
    await u.click(await screen.findByRole("button", { name: /Upload a renewal of the fire safety/ }));
    expect(onNavigate).toHaveBeenCalledWith("documents", { caseId: APP, docType: "FIRE_NOC" });
    expect(screen.queryByRole("button", { name: "Record a validity date" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Record an undertaking" })).toBeNull();
  });

  it("offers the institution only newer versions of the same document as the renewal", async () => {
    const u = userEvent.setup();
    fakeServer({ "GET /api/compliance/letters": [], "GET /api/compliance/obligations": [FIRE],
      "GET /api/compliance/obligations/vr-2": FIRE, [`GET /api/applications/${APP}/documents`]: DOCS });
    render(<ComplianceView who={SUNRISE} me={ME(SUNRISE)} onNavigate={() => {}} />);
    await u.click(await screen.findByRole("button", { name: /Open the fire safety/ }));
    const picker = await screen.findByRole("form", { name: "Submit evidence" });
    const options = within(within(picker).getByLabelText("Document version")).getAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual(["Fire safety no-objection certificate · v2 · ver-fire-2.pdf"]);
  });

  it("lets an officer verify a renewal under review with the existing evidence form", async () => {
    const u = userEvent.setup();
    const review = record({ ...FIRE, status: "EVIDENCE_SUBMITTED", validity_state: "RENEWAL_UNDER_REVIEW",
      evidence: [{ id: "e1", obligation_id: "vr-2", document_version_id: "ver-fire-2", status: "SUBMITTED",
        submitted_at: "2026-10-27T10:00:00Z", verified_role: null, verified_at: null, reason_code: null, has_note: false }] });
    const calls = fakeServer({ "GET /api/compliance/letters": [], "GET /api/compliance/obligations": [review],
      "GET /api/compliance/obligations/vr-2": review, [`GET /api/applications/${APP}/documents`]: DOCS,
      "POST /api/compliance/evidence/e1/verify": () => [200, {}] });
    render(<ComplianceView who={RO} me={ME(RO)} onNavigate={() => {}} />);
    expect(await screen.findByText("Renewal under review")).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: /Verify the renewal of the fire safety/ }));
    const form = await screen.findByRole("form", { name: "Verify this evidence" });
    expect(screen.getByText(/accepting it meets this record and opens the next one/)).toBeInTheDocument();
    await u.click(within(form).getByRole("button", { name: "Record decision" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(JSON.parse(calls.find((c) => c.method === "POST").body)).toEqual({ decision: "ACCEPTED" });
  });

  it("lets an officer record a validity date from a tracked document, by issue date for a structural certificate", async () => {
    const u = userEvent.setup();
    const calls = fakeServer({ "GET /api/compliance/letters": [], "GET /api/compliance/obligations": [],
      "GET /api/applications": APPS, [`GET /api/applications/${APP}/documents`]: DOCS,
      "POST /api/compliance/validity": () => [201, SSC] });
    render(<ComplianceView who={RO} me={ME(RO)} onNavigate={() => {}} />);
    await u.click(await screen.findByRole("button", { name: "Record a validity date" }));
    const form = await screen.findByRole("form", { name: "Record a validity date" });
    const versions = within(await within(form).findByLabelText("Document version")).getAllByRole("option").map((o) => o.textContent);
    expect(versions).toEqual(["Structural stability certificate · v1 · ver-ssc-1.pdf",
      "Fire safety no-objection certificate · v2 · ver-fire-2.pdf", "Fire safety no-objection certificate · v1 · ver-fire-1.pdf"]);
    await u.selectOptions(within(form).getByLabelText("Date read from the certificate"), "issue_date");
    await u.type(within(form).getByLabelText("Issue date"), "2024-04-01");
    await u.click(within(form).getByRole("button", { name: "Record date" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    const post = calls.find((c) => c.method === "POST");
    expect(JSON.parse(post.body)).toEqual({ document_version_id: "ver-ssc-1", issue_date: "2024-04-01" });
    expect(post.headers["Idempotency-Key"]).toBeTruthy();
    expect(await screen.findByText(/Recorded. Valid until/)).toBeInTheDocument();
  });

  it("keeps auditors read-only", async () => {
    fakeServer({ "GET /api/compliance/letters": [], "GET /api/compliance/obligations": [record()] });
    render(<ComplianceView who={AUDITOR} me={ME(AUDITOR)} onNavigate={() => {}} />);
    expect(await screen.findByRole("table", { name: "Document validity" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Record a validity date" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Upload a renewal/ })).toBeNull();
  });
});

describe("recorded undertakings", () => {
  it("an officer records an undertaking with its clause, evidence and stated due date", async () => {
    const u = userEvent.setup();
    const calls = fakeServer({ "GET /api/compliance/letters": [], "GET /api/compliance/obligations": [],
      "GET /api/applications": APPS, "POST /api/compliance/obligations": () => [201, record({ kind: "UNDERTAKING", due_date: "2026-12-01" })] });
    render(<ComplianceView who={RO} me={ME(RO)} onNavigate={() => {}} />);
    await u.click(await screen.findByRole("button", { name: "Record an undertaking" }));
    const form = await screen.findByRole("form", { name: "Record an undertaking" });
    const kinds = within(within(form).getByLabelText("Kind")).getAllByRole("option").map((o) => o.textContent);
    expect(kinds).toEqual(["Undertaking", "Affidavit", "Security deposit", "Condition in the letter", "Recurring filing"]);
    await u.type(within(form).getByLabelText("What it asks for"), "Synthetic: complete the library block");
    await u.type(within(form).getByLabelText("Evidence that meets it"), "Completion certificate");
    await u.type(within(form).getByLabelText(/Clause it comes from/), "2.25(f)");
    await u.type(within(form).getByLabelText("Due date"), "2026-12-01");
    await u.click(within(form).getByRole("button", { name: "Record obligation" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    const post = calls.find((c) => c.method === "POST");
    expect(JSON.parse(post.body)).toEqual({ application_id: APP, kind: "UNDERTAKING", title: "Synthetic: complete the library block",
      evidence_required: "Completion certificate", source_clause: "2.25(f)", due_date: "2026-12-01" });
    expect(post.headers["Idempotency-Key"]).toBeTruthy();
  });

  it("can time it by an official rule instead", async () => {
    const u = userEvent.setup();
    const calls = fakeServer({ "GET /api/compliance/letters": [], "GET /api/compliance/obligations": [],
      "GET /api/applications": APPS, "POST /api/compliance/obligations": () => [201, record({ kind: "AFFIDAVIT" })] });
    render(<ComplianceView who={RO} me={ME(RO)} onNavigate={() => {}} />);
    await u.click(await screen.findByRole("button", { name: "Record an undertaking" }));
    const form = await screen.findByRole("form", { name: "Record an undertaking" });
    await u.selectOptions(within(form).getByLabelText("Kind"), "AFFIDAVIT");
    await u.type(within(form).getByLabelText("What it asks for"), "No-admission affidavit");
    await u.type(within(form).getByLabelText("Evidence that meets it"), "Affidavit on stamp paper");
    await u.selectOptions(within(form).getByLabelText("Timing"), "rule");
    await u.click(within(form).getByRole("button", { name: "Record obligation" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(JSON.parse(calls.find((c) => c.method === "POST").body)).toMatchObject({
      kind: "AFFIDAVIT", rule_id: "NO_ADMISSION_AFFIDAVIT_7D", source_clause: null });
  });

  it("shows what a recorded obligation asks for and the penalty notes, never as applied", async () => {
    const u = userEvent.setup();
    const deposit = record({ id: "ob-d", kind: "DEPOSIT", doc_type: null, valid_until: null, validity_state: null, days_left: null,
      document_id: null, document_version_id: null, eoa_stop_year: null, live_lease_ok: null, rule_id: "DEPOSIT_15D",
      source_clause: "2.25(f)", title: "Synthetic deposit", evidence_required: "Bank receipt",
      penalty_notes: ["If late: 10% penalty up to 31 May (cl. 2.25(f))", "For the competent authority to decide; this system does not apply penalties"] });
    fakeServer({ "GET /api/compliance/letters": [], "GET /api/compliance/obligations": [deposit],
      "GET /api/compliance/obligations/ob-d": deposit, [`GET /api/applications/${APP}/documents`]: [] });
    render(<ComplianceView who={RO} me={ME(RO)} onNavigate={() => {}} />);
    await u.click(await screen.findByRole("button", { name: /Open security deposit for case/ }));
    const notes = await screen.findByRole("note", { name: "Penalty notes for the competent authority" });
    expect(within(notes).getByText(/10% penalty up to 31 May/)).toBeInTheDocument();
    expect(within(notes).getByText(/does not apply penalties/)).toBeInTheDocument();
    expect(screen.getAllByText("Synthetic deposit").length).toBeGreaterThan(0);
    expect(screen.getByText("Bank receipt")).toBeInTheDocument();
  });
});

describe("institution views", () => {
  it("the overview shows the next document expiry", async () => {
    fakeServer({ "GET /api/applications": APPS, "GET /api/deadlines": [],
      "GET /api/compliance/obligations": [record(), FIRE, RENEWED] });
    render(<OverviewView who={SUNRISE} onNavigate={() => {}} />);
    const kpis = await screen.findByLabelText("Your applications in figures");
    const expiry = await within(kpis).findByText("Next document expiry");
    const box = expiry.closest(".kpi");
    await waitFor(() => expect(within(box).getByText("20 Nov 2026")).toBeInTheDocument());
    expect(within(box).getByText("Fire safety no-objection certificate · Expiring soon · 23 days left")).toBeInTheDocument();
  });

  it("the upload form starts on the document type a renewal asks for", async () => {
    fakeServer({ "GET /api/applications": APPS, [`GET /api/applications/${APP}/documents`]: [],
      [`GET /api/applications/${APP}/checklist`]: { label: "DEMO", items: [] } });
    render(<DocumentsView who={SUNRISE} me={ME(SUNRISE)} focusCase={APP} focusDocType="FIRE_NOC" />);
    const select = await screen.findByLabelText("Checklist item");
    expect(select).toHaveValue("FIRE_NOC");
  });
});
