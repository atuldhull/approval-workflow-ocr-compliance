import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { DEMO_USERS } from "../api.js";
import TimeTravel from "../components/TimeTravel.jsx";
import AlertsView from "../views/AlertsView.jsx";
import ComplianceView, { availableVersions } from "../views/ComplianceView.jsx";
import DocumentsView from "../views/DocumentsView.jsx";
import FactReviewView, { FOUR_EYES_MESSAGE } from "../views/FactReviewView.jsx";
import { fakeServer } from "./fakeServer.js";

const user = (key) => DEMO_USERS.find((u) => u.key === key);
const SUNRISE = user("sunrise");
const SCRUTINY = user("scrutiny");
const RO = user("ro-southern");
const BUREAU = user("bureau-officer");
const AUDITOR = user("auditor");
const ME = (u) => ({ user_id: u.user, role: u.role, region: u.region ?? null, institution_id: u.institution ?? null });

const APP = "aaaaaaaa-0000-4000-8000-000000000001";
const VERSION = "bbbbbbbb-0000-4000-8000-000000000001";
const FACT = "cccccccc-0000-4000-8000-000000000001";
const OTHER_OFFICER = "00000000-0000-4000-9000-000000000099";

const version = (id, no, scan) => ({
  version_id: id, document_id: "d1", version_no: no, original_filename: `deed-v${no}.pdf`, media_type: "application/pdf",
  size_bytes: 2048, sha256: "ab".repeat(32), scan_status: scan, uploaded_at: "2026-10-20T10:00:00Z", scanned_at: null,
});
const DOCS = [{
  document_id: "d1", application_id: APP, doc_type: "LAND_DEED", current_version_id: VERSION,
  versions: [version("v-pending", 3, "scan_pending"), version("v-infected", 2, "infected"), version(VERSION, 1, "clean")],
}];
const APPS = [{ id: APP, institution_id: SUNRISE.institution, category: "NEW_INSTITUTION", academic_year: "2027-28", status: "DRAFT" }];

const proposed = (extra = {}) => ({
  fact_id: FACT, field_key: "lease_end_date", status: "proposed", review_decision: null, page_number: 1,
  suggestion_visible: false, candidate_text: null, normalized_value: null, confidence: null,
  reviewed_value: null, reviewed_by: null, reviewed_at: null, confirmed_by: null, confirmed_at: null, ...extra,
});
const reviewed = (by) => proposed({ status: "reviewed", review_decision: "CORRECTED", reviewed_value: "2031-03-31",
  reviewed_by: by, reviewed_at: "2026-10-21T10:00:00Z", suggestion_visible: true, candidate_text: "31-03-2031",
  normalized_value: "2031-03-30", confidence: 0.91 });
const factsOf = (...facts) => ({ document_version_id: VERSION, document_id: "d1",
  review_status: { proposed: 0, in_review: 0, reviewed: 0, rejected: 0, confirmed: 0 }, facts });

describe("documents: role-based screens", () => {
  it("lets an institution upload to its own application and explains each scan state", async () => {
    fakeServer({ "GET /api/applications": APPS, [`GET /api/applications/${APP}/documents`]: DOCS });
    render(<DocumentsView who={SUNRISE} me={ME(SUNRISE)} />);
    expect(await screen.findByRole("form", { name: "Upload a document" })).toBeInTheDocument();
    expect(await screen.findByText("Waiting for malware scan")).toBeInTheDocument();
    expect(screen.getByText(/Held in quarantine until the scanner checks it/)).toBeInTheDocument();
    expect(screen.getByText("Blocked by malware scan")).toBeInTheDocument();
    expect(screen.getByText(/stays in quarantine and can never be used/)).toBeInTheDocument();
    expect(screen.getByText("Scanned clean")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Run the malware scan again for version 3/ })).toBeInTheDocument();
  });

  it("gives officers the documents in their scope without an upload form", async () => {
    const calls = fakeServer({ "GET /api/documents": DOCS });
    render(<DocumentsView who={RO} me={ME(RO)} />);
    expect(await screen.findByText("Scanned clean")).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Upload a document" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Run the malware scan again/ })).toBeNull();
    expect(calls[0].url).toBe("/api/documents");
  });

  it("shows a refusal as a rule, not a failure", async () => {
    fakeServer({ "GET /api/documents": () => [403, { error: "Forbidden", detail: "regional officers may only access their own region" }] });
    render(<DocumentsView who={RO} me={ME(RO)} />);
    expect(await screen.findByText("Not available to your role.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  });

  it("shows an institution only confirmed facts and the review counts", async () => {
    const u = userEvent.setup();
    fakeServer({
      "GET /api/applications": APPS, [`GET /api/applications/${APP}/documents`]: DOCS,
      [`GET /api/document-versions/${VERSION}/facts`]: { ...factsOf({ fact_id: FACT, field_key: "lease_end_date", status: "confirmed", value: "2031-03-31", page_number: 1, confirmed_at: "2026-10-22T10:00:00Z" }),
        review_status: { proposed: 1, in_review: 0, reviewed: 1, rejected: 0, confirmed: 1 } },
    });
    render(<DocumentsView who={SUNRISE} me={ME(SUNRISE)} />);
    await u.click(await screen.findByRole("button", { name: "Confirmed facts" }));
    expect(await screen.findByText("2031-03-31")).toBeInTheDocument();
    expect(screen.getByText(/still with officers/).textContent).toMatch(/1 confirmed · 2 still with officers · 0 rejected/);
  });
});

describe("documents: upload idempotency", () => {
  it("reuses the Idempotency-Key when the same upload is retried, and starts a new one afterwards", async () => {
    const u = userEvent.setup();
    let attempt = 0;
    const calls = fakeServer({
      "GET /api/applications": APPS, [`GET /api/applications/${APP}/documents`]: [],
      [`POST /api/applications/${APP}/documents`]: () => (++attempt === 1 ? [500, { detail: "boom" }]
        : [201, { document_id: "d1", doc_type: "LAND_DEED", created: true, version: version("v9", 1, "scan_pending") }]),
    });
    render(<DocumentsView who={SUNRISE} me={ME(SUNRISE)} />);
    const form = await screen.findByRole("form", { name: "Upload a document" });
    await u.upload(within(form).getByLabelText(/^File/), new File(["%PDF-1.7 synthetic"], "deed.pdf", { type: "application/pdf" }));
    await u.click(within(form).getByRole("button", { name: "Upload" }));
    expect(await within(form).findByText(/same upload, so it cannot be stored twice/)).toBeInTheDocument();
    await u.click(within(form).getByRole("button", { name: "Try the upload again" }));
    expect(await within(form).findByText(/Uploaded as version 1/)).toBeInTheDocument();

    const posts = calls.filter((c) => c.method === "POST");
    expect(posts).toHaveLength(2);
    const key = posts[0].headers["Idempotency-Key"];
    expect(key).toMatch(/^[0-9a-f-]{36}$/);
    expect(posts[1].headers["Idempotency-Key"]).toBe(key);
    expect(posts[0].body).toBeInstanceOf(FormData);
    expect(posts[0].body.get("doc_type")).toBe("LAND_DEED");
    expect(posts[0].headers["Content-Type"]).toBeUndefined();

    // a new upload after success is a new action with a new key
    await u.upload(within(form).getByLabelText(/^File/), new File(["%PDF-1.7 other"], "plan.pdf", { type: "application/pdf" }));
    await u.click(within(form).getByRole("button", { name: "Upload" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "POST")).toHaveLength(3));
    expect(calls.filter((c) => c.method === "POST")[2].headers["Idempotency-Key"]).not.toBe(key);
  });

  it("does not send a file over the server's size cap", async () => {
    const u = userEvent.setup();
    const calls = fakeServer({ "GET /api/applications": APPS, [`GET /api/applications/${APP}/documents`]: [] });
    render(<DocumentsView who={SUNRISE} me={ME(SUNRISE)} />);
    const form = await screen.findByRole("form", { name: "Upload a document" });
    const big = new File(["x"], "big.pdf", { type: "application/pdf" });
    Object.defineProperty(big, "size", { value: 11 * 1024 * 1024 });
    await u.upload(within(form).getByLabelText(/^File/), big);
    expect(within(form).getByText(/larger than 10 MB/)).toBeInTheDocument();
    expect(within(form).getByRole("button", { name: "Upload" })).toBeDisabled();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });
});

describe("fact review: blind entry, then reveal, then review", () => {
  it("withholds the machine reading until the reviewer's own value is recorded", async () => {
    const u = userEvent.setup();
    let fact = proposed();
    const calls = fakeServer({
      "GET /api/documents": DOCS,
      [`GET /api/document-versions/${VERSION}/facts`]: () => [200, factsOf(fact)],
      [`POST /api/document-facts/${FACT}/entry`]: () => {
        fact = proposed({ status: "in_review", suggestion_visible: true, candidate_text: "31-03-2031", normalized_value: "2031-03-31", confidence: 0.82, normalization_status: "NORMALIZED" });
        return [200, { fact_id: FACT, candidate_text: "31-03-2031", normalized_value: "2031-03-31", confidence: 0.82, normalization_status: "NORMALIZED" }];
      },
      [`POST /api/document-facts/${FACT}/review`]: () => [200, reviewed(SCRUTINY.user)],
    });
    const { container } = render(<FactReviewView who={SCRUTINY} me={ME(SCRUTINY)} />);
    const card = await screen.findByRole("group", { name: "Lease end date" });
    expect(container.textContent).not.toMatch(/2031|31-03|confidence|Machine reading/);
    expect(within(card).queryByRole("radiogroup")).toBeNull();

    await u.type(within(card).getByLabelText("Your reading"), "2031-03-30");
    await u.click(within(card).getByRole("button", { name: "Commit my reading" }));
    expect(await within(card).findByText(/Machine reading/)).toBeInTheDocument();
    expect(within(card).getByText("Differs from your reading - check the document")).toBeInTheDocument();

    const writes = calls.filter((c) => c.method === "POST").map((c) => c.url);
    expect(writes).toEqual([`/api/document-facts/${FACT}/entry`]);
    expect(JSON.parse(calls.find((c) => c.method === "POST").body)).toEqual({ value: "2031-03-30" });

    // the reviewer's differing reading is offered as the correction
    const group = within(card).getByRole("radiogroup", { name: /Decision for Lease end date/ });
    expect(within(group).getByRole("radio", { name: /Correct it/ })).toBeChecked();
    expect(within(card).getByLabelText("Correct value")).toHaveValue("2031-03-30");
    await u.click(within(card).getByRole("button", { name: "Record my review" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "POST")).toHaveLength(2));
    const review = calls.filter((c) => c.method === "POST")[1];
    expect(review.url).toBe(`/api/document-facts/${FACT}/review`);
    expect(JSON.parse(review.body)).toEqual({ decision: "CORRECTED", value: "2031-03-30" });
    expect(review.headers["Idempotency-Key"]).toBeTruthy();
  });

  it("explains a missing text reader in plain words", async () => {
    const u = userEvent.setup();
    fakeServer({
      "GET /api/documents": DOCS, [`GET /api/document-versions/${VERSION}/facts`]: factsOf(),
      [`POST /api/document-versions/${VERSION}/extract`]: () => [503, { error: "ServiceUnavailable", detail: "no text engine is configured" }],
    });
    render(<FactReviewView who={RO} me={ME(RO)} />);
    await u.click(await screen.findByRole("button", { name: "Extract facts" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No text reader is configured on the server yet");
    expect(screen.getByRole("alert").textContent).not.toMatch(/security service/);
  });

  it("only offers versions that passed the malware scan", async () => {
    fakeServer({ "GET /api/documents": DOCS, [`GET /api/document-versions/${VERSION}/facts`]: factsOf() });
    render(<FactReviewView who={RO} me={ME(RO)} />);
    const select = await screen.findByLabelText("Version to review");
    expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual([expect.stringContaining("v1")]);
  });
});

describe("fact review: four eyes", () => {
  it("shows the server's four-eyes refusal clearly", async () => {
    const u = userEvent.setup();
    fakeServer({
      "GET /api/documents": DOCS, [`GET /api/document-versions/${VERSION}/facts`]: factsOf(reviewed(OTHER_OFFICER)),
      [`POST /api/document-facts/${FACT}/confirm`]: () => [409, { error: "FourEyesViolation", detail: "the officer who reviewed this fact cannot also confirm it; another officer must confirm" }],
    });
    render(<FactReviewView who={RO} me={ME(RO)} />);
    await u.click(await screen.findByRole("button", { name: "Confirm lease end date" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Refused by the four-eyes rule.");
    expect(alert).toHaveTextContent(FOUR_EYES_MESSAGE);
    expect(alert.textContent).not.toMatch(/FourEyesViolation|409/);
  });

  it("tells the reviewer up front that someone else must confirm", async () => {
    fakeServer({ "GET /api/documents": DOCS, [`GET /api/document-versions/${VERSION}/facts`]: factsOf(reviewed(RO.user)) });
    render(<FactReviewView who={RO} me={ME(RO)} />);
    expect(await screen.findByText(FOUR_EYES_MESSAGE)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Confirm/ })).toBeNull();
  });

  it("lets a different officer confirm, sending an Idempotency-Key", async () => {
    const u = userEvent.setup();
    let fact = reviewed(RO.user);
    const calls = fakeServer({
      "GET /api/documents": DOCS, [`GET /api/document-versions/${VERSION}/facts`]: () => [200, factsOf(fact)],
      [`POST /api/document-facts/${FACT}/confirm`]: () => { fact = { ...fact, status: "confirmed", confirmed_by: BUREAU.user, confirmed_at: "2026-10-22T10:00:00Z" }; return [200, fact]; },
    });
    render(<FactReviewView who={BUREAU} me={ME(BUREAU)} />);
    expect(await screen.findByText(/confirms values another officer reviewed/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Your reading")).toBeNull();
    await u.click(screen.getByRole("button", { name: "Confirm lease end date" }));
    const card = screen.getByRole("group", { name: "Lease end date" });
    expect(await within(card).findByText("Confirmed by a second officer")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST").headers["Idempotency-Key"]).toBeTruthy();
  });

  it("keeps auditors read-only", async () => {
    fakeServer({ "GET /api/documents": DOCS, [`GET /api/document-versions/${VERSION}/facts`]: factsOf(proposed({ suggestion_visible: true, candidate_text: "31-03-2031", normalized_value: "2031-03-31", confidence: 0.8 }), ) });
    render(<FactReviewView who={AUDITOR} me={ME(AUDITOR)} />);
    expect(await screen.findByText(/Read-only: your role can see the review record/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Your reading")).toBeNull();
    expect(screen.queryByRole("button", { name: /Confirm|Record my review|Extract/ })).toBeNull();
  });
});

const OB = "dddddddd-0000-4000-8000-000000000001";
const obligation = (extra = {}) => ({
  id: OB, application_id: APP, institution_id: SUNRISE.institution, region: "Southern", kind: "AFFIDAVIT",
  source_letter_id: "l1", source_clause: "2.14", source_status: "verified", state_origin: "RULE_DEFAULT", rule_id: "affidavit",
  deadline_id: null, due_date: "2027-03-15", status: "OPEN", met_at: null, evidence: [], ...extra,
});
const LETTER = { id: "l1", application_id: APP, institution_id: SUNRISE.institution, region: "Southern", letter_type: "LOA",
  academic_year: "2027-28", issue_date: "2026-10-01", issue_date_source: "PORTAL_EVENT", issue_date_fact_id: null,
  document_version_id: null, f_no: "F.No. SYN-1", lists_deficiencies: false, ruleset_rev: "r1", valid_until: null,
  registered_at: "2026-10-02T10:00:00Z", obligation_ids: [OB] };

describe("compliance", () => {
  it("evidence picker offers only scanner-approved versions not already submitted", async () => {
    expect(availableVersions(DOCS).map((v) => v.id)).toEqual([VERSION]);
    expect(availableVersions(DOCS, [VERSION])).toEqual([]);

    const u = userEvent.setup();
    const calls = fakeServer({
      "GET /api/compliance/letters": [LETTER], "GET /api/compliance/obligations": [obligation()],
      [`GET /api/compliance/obligations/${OB}`]: obligation(), [`GET /api/applications/${APP}/documents`]: DOCS,
      [`POST /api/compliance/obligations/${OB}/evidence`]: () => [201, { id: "e1" }],
    });
    render(<ComplianceView who={SUNRISE} me={ME(SUNRISE)} />);
    expect(await screen.findByText("Letter of Approval (LoA)")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Register a letter" })).toBeNull();
    await u.click(await screen.findByRole("button", { name: /Open affidavit for case/ }));
    const picker = await screen.findByRole("form", { name: "Submit evidence" });
    const options = within(within(picker).getByLabelText("Document version")).getAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual(["Land ownership or registered lease deed · v1 · deed-v1.pdf"]);
    await u.click(within(picker).getByRole("button", { name: "Submit as evidence" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    const post = calls.find((c) => c.method === "POST");
    expect(JSON.parse(post.body)).toEqual({ document_version_id: VERSION });
    expect(post.headers["Idempotency-Key"]).toBeTruthy();
  });

  it("officers verify with a reason code; a rejection needs one", async () => {
    const u = userEvent.setup();
    const submitted = obligation({ status: "EVIDENCE_SUBMITTED", evidence: [{ id: "e1", obligation_id: OB, document_version_id: VERSION,
      status: "SUBMITTED", submitted_at: "2026-10-23T10:00:00Z", verified_role: null, verified_at: null, reason_code: null, has_note: false }] });
    const calls = fakeServer({
      "GET /api/compliance/letters": [], "GET /api/compliance/obligations": [submitted],
      [`GET /api/compliance/obligations/${OB}`]: submitted, [`GET /api/applications/${APP}/documents`]: DOCS,
      "POST /api/compliance/evidence/e1/verify": () => [200, {}],
    });
    render(<ComplianceView who={RO} me={ME(RO)} />);
    await u.click(await screen.findByRole("button", { name: /Open affidavit/ }));
    const form = await screen.findByRole("form", { name: "Verify this evidence" });
    expect(screen.getByText("Land ownership or registered lease deed · v1 · deed-v1.pdf")).toBeInTheDocument();
    await u.click(within(form).getByRole("radio", { name: "Reject" }));
    const save = within(form).getByRole("button", { name: "Record decision" });
    expect(save).toBeDisabled();
    await u.selectOptions(within(form).getByLabelText("Reason"), "DATE_MISMATCH");
    await u.click(save);
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(JSON.parse(calls.find((c) => c.method === "POST").body)).toEqual({ decision: "REJECTED", reason_code: "DATE_MISMATCH" });
    expect(screen.queryByRole("form", { name: "Submit evidence" })).toBeNull();
  });

  it("other-reason rejections need a note", async () => {
    const u = userEvent.setup();
    const submitted = obligation({ status: "EVIDENCE_SUBMITTED", evidence: [{ id: "e1", obligation_id: OB, document_version_id: VERSION,
      status: "SUBMITTED", submitted_at: "2026-10-23T10:00:00Z", verified_role: null, verified_at: null, reason_code: null, has_note: false }] });
    fakeServer({ "GET /api/compliance/letters": [], "GET /api/compliance/obligations": [submitted],
      [`GET /api/compliance/obligations/${OB}`]: submitted, [`GET /api/applications/${APP}/documents`]: DOCS });
    render(<ComplianceView who={BUREAU} me={ME(BUREAU)} />);
    expect(screen.getByRole("button", { name: "Register a letter" })).toBeInTheDocument();
    await u.click(await screen.findByRole("button", { name: /Open affidavit/ }));
    const form = await screen.findByRole("form", { name: "Verify this evidence" });
    await u.click(within(form).getByRole("radio", { name: "Reject" }));
    await u.selectOptions(within(form).getByLabelText("Reason"), "OTHER_SEE_NOTE");
    expect(within(form).getByRole("button", { name: "Record decision" })).toBeDisabled();
    await u.type(within(form).getByLabelText(/Note/), "Synthetic note");
    expect(within(form).getByRole("button", { name: "Record decision" })).toBeEnabled();
  });

  it("auditors read without acting", async () => {
    const u = userEvent.setup();
    fakeServer({ "GET /api/compliance/letters": [LETTER], "GET /api/compliance/obligations": [obligation()],
      [`GET /api/compliance/obligations/${OB}`]: obligation(), [`GET /api/applications/${APP}/documents`]: DOCS });
    render(<ComplianceView who={AUDITOR} me={ME(AUDITOR)} />);
    await u.click(await screen.findByRole("button", { name: /Open affidavit/ }));
    expect(await screen.findByText(/auditors can see decisions but not make them/)).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Submit evidence" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Register a letter" })).toBeNull();
  });
});

const alert = (extra = {}) => ({
  id: "al-1", deadline_id: "dl-1", level: 0, due_version: 1, role: "RO_OFFICER", subject_type: "application", subject_id: APP,
  institution_id: SUNRISE.institution, region: "Southern", template: "deadline.reminder", status: "OPEN", reason: null,
  from_alert_id: null, raised_at: "2026-10-24T10:00:00Z", escalated_at: null, acknowledged_at: null, ...extra,
});

describe("alerts", () => {
  it("acknowledges an alert addressed to the caller's role, with an Idempotency-Key", async () => {
    const u = userEvent.setup();
    let current = alert();
    const calls = fakeServer({
      "GET /api/alerts": () => [200, [current, alert({ id: "al-2", level: 1, role: "BUREAU_HEAD", status: "ESCALATED", reason: "WINDOW_ELAPSED", template: "deadline.escalated" })]],
      "POST /api/alerts/al-1/ack": () => { current = { ...current, status: "ACKNOWLEDGED", acknowledged_at: "2026-10-25T10:00:00Z" }; return [200, current]; },
    });
    render(<AlertsView who={RO} me={ME(RO)} />);
    expect(await screen.findByText("The previous level was not acknowledged in time.")).toBeInTheDocument();
    expect(screen.getByText("Only the bureau head can acknowledge this")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /^Acknowledge:/ })).toHaveLength(1);
    await u.click(screen.getByRole("button", { name: /^Acknowledge: A deadline is approaching/ }));
    expect(await screen.findByText(/No further escalation will be raised/)).toBeInTheDocument();
    expect(await screen.findByText("Acknowledged", { selector: ".badge" })).toBeInTheDocument();
    const post = calls.find((c) => c.method === "POST");
    expect(post.url).toBe("/api/alerts/al-1/ack");
    expect(post.headers["Idempotency-Key"]).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^Acknowledge:/ })).toBeNull();
  });

  it("filters by status on the server and keeps auditors read-only", async () => {
    const u = userEvent.setup();
    const calls = fakeServer({ "GET /api/alerts": [alert({ role: "AUDITOR" })] });
    render(<AlertsView who={AUDITOR} me={ME(AUDITOR)} />);
    expect(await screen.findByText(/auditors see alerts but do not acknowledge them/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Acknowledge:/ })).toBeNull();
    await u.click(screen.getByRole("button", { name: "Escalated" }));
    await waitFor(() => expect(calls.at(-1).url).toBe("/api/alerts?status=ESCALATED"));
  });

  it("the demo timer run fetches the alerts again", async () => {
    const u = userEvent.setup();
    let runs = 0;
    const calls = fakeServer({
      "GET /api/sim/clock": { now: "2026-10-27T10:00:00Z", offset_days: 0 },
      "POST /api/sim/timers/run": () => [200, { processed: ++runs }],
      "GET /api/alerts": [],
    });
    render(<><TimeTravel who={RO} /><AlertsView who={RO} me={ME(RO)} /></>);
    expect(await screen.findByText("No deadline alerts in your scope.")).toBeInTheDocument();
    const before = calls.filter((c) => c.url === "/api/alerts").length;
    await u.click(screen.getByRole("button", { name: "Run timers now" }));
    expect(await screen.findByText("Timers ran: 1 processed")).toBeInTheDocument();
    await waitFor(() => expect(calls.filter((c) => c.url === "/api/alerts").length).toBe(before + 1));
  });
});
