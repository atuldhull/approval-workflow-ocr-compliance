import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { DEMO_USERS } from "../api.js";
import { keepsKey } from "../actionKey.js";
import CaseDetail from "../components/CaseDetail.jsx";
import ScorecardView from "../views/ScorecardView.jsx";
import EvcView from "../views/EvcView.jsx";
import { REASONS, refusalText } from "../workflowText.js";
import { fakeServer } from "./fakeServer.js";

const user = (key) => DEMO_USERS.find((u) => u.key === key);
const ME = (u) => ({ user_id: u.user, role: u.role, region: u.region ?? null, institution_id: u.institution ?? null });
const SUNRISE = user("sunrise");
const ID = "4d96fec8-ff6b-421e-97e9-914b93618c17";
const DOC = "aaaaaaaa-0000-4000-8000-000000000001";
const ROUTE = [{ stage: "SCRUTINY", when: "always" }, { stage: "EVC", when: "always" }, { stage: "SHC", when: "as_applicable" }];

const caseRec = (over = {}) => ({
  case_id: ID, institution_id: SUNRISE.institution, region: "Southern", stage: "SCRUTINY", status: "IN_PROCESS", version: 3,
  route_id: "NEW_PROGRAMME", ruleset_key: "aph-2024-27@r1", preview_ruleset_key: null, route: ROUTE, clause_citation: null,
  stage_history: [], available_actions: [], assumption_status: "DEMO_ASSUMPTION", ...over,
});
const APP = { id: ID, category: "NEW_PROGRAMME", academic_year: "2027-28", status: "DRAFT", current_stage: null, submitted_at: null };
const CHECKLIST = {
  application_id: ID, category: "NEW_PROGRAMME", ruleset_key: "aph-2024-27@r1", pinned: false, status: "DEMO_ASSUMPTION",
  label: "DEMO ASSUMPTION", assumptions: [], dsc_required: true, dsc_present: false,
  items: [
    { item_key: "DEMO_CORE_REFERENCE", mandatory: true, state: "MISSING", document_ref: null },
    { item_key: "DEMO_OPTIONAL_REFERENCE", mandatory: false, state: "MISSING", document_ref: null },
  ],
  missing_mandatory_item_keys: ["DEMO_CORE_REFERENCE"], mandatory_items_complete: false,
};
const DOCS = [{ document_id: "d1", doc_type: "DEMO_CORE_REFERENCE",
  versions: [{ version_id: DOC, version_no: 1, status: "AVAILABLE", original_filename: "core.png", media_type: "image/png" }] }];

function draftServer(extra = {}) {
  return fakeServer({
    [`GET /api/cases/${ID}`]: caseRec({ stage: null, status: "DRAFT", version: 1, available_actions: [
      { action: "submit", targets: [], enabled: false, reason_code: "MANDATORY_ITEMS_MISSING", reason_codes_required: false, aliases: [] }] }),
    [`GET /api/applications/${ID}`]: APP,
    [`GET /api/applications/${ID}/checklist`]: CHECKLIST,
    [`GET /api/applications/${ID}/documents`]: DOCS,
    ...extra,
  });
}

const missing = (keys) => () => [422, { error: "ValidationFailed", detail: "MANDATORY_ITEMS_MISSING", reason_code: "MANDATORY_ITEMS_MISSING", missing_item_keys: keys }];

describe("institution checklist and submission", () => {
  it("renders the server checklist with each item's state, mandatory flag and the DSC requirement", async () => {
    draftServer();
    render(<CaseDetail who={SUNRISE} me={ME(SUNRISE)} id={ID} />);
    const list = await screen.findByRole("region", { name: "Checklist" });
    expect(within(list).getByText("Core reference document")).toBeInTheDocument();
    expect(within(list).getByText("Optional reference document")).toBeInTheDocument();
    expect(within(list).getAllByText("Not provided")).toHaveLength(2);
    expect(within(list).getByText("Mandatory")).toBeInTheDocument();
    expect(within(list).getByText("Optional")).toBeInTheDocument();
    expect(within(list).getByText("DEMO ASSUMPTION")).toBeInTheDocument();
    expect(within(list).getByLabelText(/signed with a valid digital signature certificate/)).not.toBeChecked();
    expect(within(list).getByText(/Still needed before submitting: Core reference document, Digital signature/)).toBeInTheDocument();
  });

  it("explains a MANDATORY_ITEMS_MISSING refusal item by item, including the DSC", async () => {
    draftServer({ [`POST /api/applications/${ID}/submit`]: missing(["DEMO_CORE_REFERENCE", "DSC"]) });
    const u = userEvent.setup();
    render(<CaseDetail who={SUNRISE} me={ME(SUNRISE)} id={ID} />);
    await u.click(await screen.findByRole("button", { name: "Submit application" }));
    const alerts = await screen.findAllByRole("alert");
    const text = alerts.map((a) => a.textContent).join(" ");
    expect(text).toMatch(/"Core reference document" is mandatory and has no document linked yet/);
    expect(text).toMatch(/digital signature certificate \(DSC\) has not been confirmed/);
  });

  it("sends the DSC flag the institution confirmed (false when unticked)", async () => {
    const calls = draftServer({ [`POST /api/applications/${ID}/submit`]: missing(["DSC"]),
      [`POST /api/applications/${ID}/items`]: { application_id: ID, items: [], dsc_required: true, assumptions: [] } });
    const u = userEvent.setup();
    render(<CaseDetail who={SUNRISE} me={ME(SUNRISE)} id={ID} />);
    await u.selectOptions(await screen.findByLabelText("Document for Core reference document"), DOC);
    await u.click(screen.getByRole("button", { name: "Submit application" }));
    await screen.findByText(/has not been confirmed/, { selector: ".checklist-item [role=alert]" });
    const submit = calls.find((c) => c.method === "POST" && c.url.endsWith("/submit"));
    expect(JSON.parse(submit.body)).toEqual({ dsc_present: false });
  });

  it("links a real uploaded document version to each item, then submits with dsc_present", async () => {
    const calls = draftServer({
      [`POST /api/applications/${ID}/items`]: { application_id: ID, items: [], dsc_required: true, assumptions: [] },
      [`POST /api/applications/${ID}/submit`]: { id: ID },
    });
    const u = userEvent.setup();
    const changed = [];
    render(<CaseDetail who={SUNRISE} me={ME(SUNRISE)} id={ID} onChanged={(x) => changed.push(x)} />);
    await u.selectOptions(await screen.findByLabelText("Document for Core reference document"), DOC);
    await u.click(screen.getByLabelText(/signed with a valid digital signature certificate/));
    await u.click(screen.getByRole("button", { name: "Submit application" }));
    await waitFor(() => expect(changed).toContain(ID));
    const items = calls.find((c) => c.method === "POST" && c.url.endsWith("/items"));
    expect(JSON.parse(items.body)).toEqual({ items: [{ item_key: "DEMO_CORE_REFERENCE", state: "PROVIDED", document_ref: DOC }] });
    const submit = calls.find((c) => c.method === "POST" && c.url.endsWith("/submit"));
    expect(JSON.parse(submit.body)).toEqual({ dsc_present: true });
    expect(items.headers["Idempotency-Key"]).toBeTruthy();
    expect(submit.headers["Idempotency-Key"]).toBeTruthy();
    expect(submit.headers["Idempotency-Key"]).not.toBe(items.headers["Idempotency-Key"]);
  });

  it("offers only scanned-clean versions to link", async () => {
    draftServer({ [`GET /api/applications/${ID}/documents`]: [{ ...DOCS[0], versions: [{ ...DOCS[0].versions[0], status: "QUARANTINED" }] }] });
    render(<CaseDetail who={SUNRISE} me={ME(SUNRISE)} id={ID} />);
    const picker = await screen.findByLabelText("Document for Core reference document");
    expect(within(picker).getAllByRole("option")).toHaveLength(1);
    expect(screen.getByText(/No scanned-clean document yet/)).toBeInTheDocument();
  });
});

const act = (action, enabled, reason_code = null, extra = {}) => ({
  action, targets: [], enabled, reason_code, reason_codes_required: false, aliases: [], ...extra,
});

describe("case actions follow the server's list for the role", () => {
  it("shows the scrutiny committee its actions with guard reasons in plain words", async () => {
    const scrutiny = user("scrutiny");
    fakeServer({ [`GET /api/cases/${ID}`]: caseRec({ available_actions: [
      act("advance", false, "ASSIGNMENT_REQUIRED"), act("record_deficiency", true, null, { targets: ["DEFICIENT"], reason_codes_required: true }),
    ] }) });
    render(<CaseDetail who={scrutiny} me={ME(scrutiny)} id={ID} />);
    const panel = await screen.findByRole("region", { name: "What you can do now" });
    expect(within(panel).getByText("Record a deficiency")).toBeInTheDocument();
    expect(within(panel).getByText("Complete this stage")).toBeInTheDocument();
    expect(within(panel).getByText(REASONS.ASSIGNMENT_REQUIRED)).toBeInTheDocument();
    expect(within(panel).queryByText("Issue Letter of Approval")).toBeNull();
  });

  it("shows the bureau the letter actions as switched off when the server says so", async () => {
    const bureau = user("bureau-officer");
    fakeServer({ [`GET /api/cases/${ID}`]: caseRec({ stage: "EVC", available_actions: [
      act("issue_loa", false, "LETTER_ISSUANCE_DISABLED"), act("reject", true, null, { reason_codes_required: true }),
    ] }) });
    render(<CaseDetail who={bureau} me={ME(bureau)} id={ID} />);
    expect(await screen.findByText(/Letter issuance is switched off on this server/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open" })).toBeInTheDocument(); // only reject can be opened
  });

  it("offers nothing that the server did not list", async () => {
    const auditor = user("auditor");
    fakeServer({ [`GET /api/cases/${ID}`]: caseRec() });
    render(<CaseDetail who={auditor} me={ME(auditor)} id={ID} />);
    expect(await screen.findByText("No actions for your role at this stage.")).toBeInTheDocument();
  });

  it("sends expected_version and reuses the Idempotency-Key when the same action is retried", async () => {
    const scrutiny = user("scrutiny");
    let attempt = 0;
    const calls = fakeServer({
      [`GET /api/cases/${ID}`]: caseRec({ available_actions: [act("advance_to_evc", true, null, { targets: ["EVC"] })] }),
      [`POST /api/cases/${ID}/actions`]: () => (++attempt === 1 ? [503, { detail: "unavailable" }] : [200, { case_id: ID }]),
    });
    const u = userEvent.setup();
    render(<CaseDetail who={scrutiny} me={ME(scrutiny)} id={ID} />);
    await u.click(await screen.findByRole("button", { name: "Open" }));
    const form = screen.getByRole("form", { name: "Send for expert visit (EVC)" });
    await u.click(within(form).getByRole("button", { name: "Send for expert visit (EVC)" }));
    expect(await within(form).findByText(/cannot be applied twice/)).toBeInTheDocument();
    await u.click(within(form).getByRole("button", { name: "Send for expert visit (EVC)" }));
    await waitFor(() => expect(attempt).toBe(2));
    const posts = calls.filter((c) => c.method === "POST");
    expect(JSON.parse(posts[0].body)).toEqual({ action: "advance_to_evc", expected_version: 3 });
    expect(posts[1].headers["Idempotency-Key"]).toBe(posts[0].headers["Idempotency-Key"]);
  });

  it("starts a new key after a refusal and explains a version conflict", async () => {
    const scrutiny = user("scrutiny");
    let attempt = 0;
    const calls = fakeServer({
      [`GET /api/cases/${ID}`]: caseRec({ available_actions: [act("advance", true)] }),
      [`POST /api/cases/${ID}/actions`]: () => (++attempt === 1
        ? [422, { error: "WorkflowValidationFailed", detail: "OPEN_DEFICIENCY_ITEMS" }]
        : [409, { error: "WorkflowConflict", detail: "VERSION_CONFLICT" }]),
    });
    const u = userEvent.setup();
    render(<CaseDetail who={scrutiny} me={ME(scrutiny)} id={ID} />);
    await u.click(await screen.findByRole("button", { name: "Open" }));
    const form = screen.getByRole("form", { name: "Complete this stage" });
    await u.click(within(form).getByRole("button", { name: "Complete this stage" }));
    expect(await within(form).findByText(REASONS.OPEN_DEFICIENCY_ITEMS)).toBeInTheDocument();
    await u.click(within(form).getByRole("button", { name: "Complete this stage" }));
    expect(await screen.findByText(REASONS.VERSION_CONFLICT)).toBeInTheDocument();
    const posts = calls.filter((c) => c.method === "POST");
    expect(posts[1].headers["Idempotency-Key"]).not.toBe(posts[0].headers["Idempotency-Key"]);
    // the conflict reloads the case
    await waitFor(() => expect(calls.filter((c) => c.method === "GET" && c.url === `/api/cases/${ID}`).length).toBeGreaterThan(1));
  });

  it("records a deficiency with the chosen items and reason", async () => {
    const scrutiny = user("scrutiny");
    const calls = fakeServer({
      [`GET /api/cases/${ID}`]: caseRec({ available_actions: [act("record_deficiency", true, null, { reason_codes_required: true })] }),
      [`POST /api/cases/${ID}/actions`]: { case_id: ID },
    });
    const u = userEvent.setup();
    render(<CaseDetail who={scrutiny} me={ME(scrutiny)} id={ID} />);
    await u.click(await screen.findByRole("button", { name: "Open" }));
    const form = screen.getByRole("form", { name: "Record a deficiency" });
    await u.click(within(form).getByLabelText("Core reference document"));
    await u.click(within(form).getByRole("button", { name: "Record a deficiency" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(JSON.parse(calls.find((c) => c.method === "POST").body)).toEqual({
      action: "record_deficiency", expected_version: 3, reason_code: "DEMO_MISSING_EVIDENCE", payload: { item_keys: ["DEMO_CORE_REFERENCE"] },
    });
  });

  it("lets the institution answer each open deficiency item with one of its documents", async () => {
    const ITEM = "bbbbbbbb-0000-4000-8000-000000000001";
    const calls = fakeServer({
      [`GET /api/cases/${ID}`]: caseRec({ stage: "DEFICIENT", available_actions: [act("submit_compliance", true, null, { targets: ["RESCRUTINY"] })] }),
      [`GET /api/applications/${ID}/documents`]: DOCS,
      [`GET /api/cases/${ID}/deficiencies`]: { case_id: ID, version: 3, ruleset_key: "aph-2024-27@r1",
        response_window: { rule_id: "INSTITUTION_RESPONSE", value: 15, unit: "calendar_days", assumption_code: "DEFICIENCY_RESPONSE_WINDOW_UNCONFIRMED" },
        rounds: [{ id: "r1", round_no: 1, status: "OPEN", opened_at: "2026-10-27T19:00:00Z", closed_at: null, closure_kind: null,
          items: [{ id: ITEM, item_key: "DEMO_CORE_REFERENCE", state: "OPEN", response_ref: null, decided_by: null, decision_reason_code: null, previous_item_id: null }] }] },
      [`POST /api/cases/${ID}/actions`]: { case_id: ID },
    });
    const u = userEvent.setup();
    render(<CaseDetail who={SUNRISE} me={ME(SUNRISE)} id={ID} />);
    expect(await screen.findByText("Open: response needed", { selector: ".round-head .badge" })).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "Open" }));
    await u.selectOptions(screen.getByLabelText("Response for Core reference document"), DOC);
    await u.click(screen.getByRole("button", { name: "Send the compliance response" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(JSON.parse(calls.find((c) => c.method === "POST").body).payload).toEqual({ responses: [{ item_id: ITEM, response_ref: DOC }] });
  });
});

describe("plain wording for guard codes", () => {
  it.each(["ASSIGNMENT_REQUIRED", "EVC_SCHEDULE_NOT_PUBLISHED", "DECISION_NOT_AUTHORISED", "LETTER_DATA_NOT_CONFIRMED",
    "LETTER_DECISION_MISMATCH", "APPROVAL_POLICY_UNAVAILABLE", "GUARD_CONTEXT_UNAVAILABLE", "INVALID_TRANSITION"])("%s", (code) => {
    const text = refusalText(Object.assign(new Error(code), { status: 422, reason: code }));
    expect(text).toBe(REASONS[code]);
    expect(text).not.toMatch(/[A-Z]{3,}_[A-Z]{3,}/);
  });

  it("falls back to readable words for an unknown code", () => {
    expect(refusalText(Object.assign(new Error("X"), { reason: "SOME_NEW_GUARD" }))).toBe("Refused: Some new guard.");
  });

  it("keeps the key only for failures that may have been applied", () => {
    expect(keepsKey({ status: 0 })).toBe(true);
    expect(keepsKey({ status: 503 })).toBe(true);
    expect(keepsKey({ status: 409, reason: null })).toBe(true); // still being processed
    expect(keepsKey({ status: 409, reason: "VERSION_CONFLICT" })).toBe(false);
    expect(keepsKey({ status: 422, reason: "ASSIGNMENT_REQUIRED" })).toBe(false);
    expect(keepsKey(null)).toBe(false);
  });
});

const QUEUE = { items: [{ id: "q1", application_id: ID, institution_ref: SUNRISE.institution, region: "Southern", category: "NEW_PROGRAMME",
  requested_at: "2026-10-27T19:00:00Z", earliest_date: "2026-10-28", due_by: "2026-11-04", status: "QUEUED", priority_key: "k",
  ruleset_key: "aph-2024-27@r1", rule_id: "EVC_PROCESSING", deadline_ref: "d", closed_at: null, days_waiting: 0, duration_days: 7 }],
  total: 1, offset: 0, limit: 100 };
const POOL = { items: [], total: 0, offset: 0, limit: 100, ruleset_key: "aph-2024-27@r1", region_rule: "SAME_REGION" };
const PROPOSAL = {
  selector_label: "SIMULATED authorised selector (stand-in)", simulation_status: "SIMULATED", source_status: "DEMO_ASSUMPTION",
  assumption_code: "EDF_PLANNING_UNCONFIRMED", run_id: "cd6f635d-ae83-4362-a49a-553ecd807fc3", algorithm: "CPSAT", status: "PROPOSED",
  region_scope: "SOUTHERN", horizon_start: "2026-10-28", horizon_end: "2026-11-10", created_at: "2026-10-27T19:20:19Z",
  input_fingerprint: "98818fce327d022e9e45f0dc", metrics: { queue_count: 1, scheduled: 1, unscheduled: 0, late_count: 0, total_lateness: 0,
    max_lateness: 0, total_waiting: 0, hard_constraint_violations: 0, lateness_days: [0] },
  solver: { solver_status: 4, objective_value: 6, best_bound: 6, repair_rounds: 0, candidate_count: 12, edf_scheduled: 1, fallback_to_edf: false },
  proposals: [{ application_id: ID, request_id: "q1", assignment_id: "a1", slot_id: "s1", date: "2026-10-28", slot_part: "PM",
    expert_ids: ["e1", "e2", "e3"], due_by: "2026-11-04", lateness_days: 0 }],
  unscheduled: [{ request_id: "q2", reason_code: "NO_FEASIBLE_SLOT" }],
};

function evcServer(extra = {}) {
  return fakeServer({ "GET /api/evc/queue": QUEUE, "GET /api/evc/experts": POOL, "GET /api/institutions": [], ...extra });
}

describe("EVC scheduling", () => {
  it("labels the simulated selector and scopes a regional officer's queue to its region", async () => {
    const ro = user("ro-southern");
    const calls = evcServer();
    render(<EvcView who={ro} me={ME(ro)} />);
    expect(await screen.findByText("Queued: no visit planned yet")).toBeInTheDocument();
    expect(screen.getByText(/real selection of experts happens on AICTE's own portal/)).toBeInTheDocument();
    expect(calls.find((c) => c.url.startsWith("/api/evc/queue")).url).toContain("region=Southern");
  });

  it("proposes with CP-SAT and shows metrics, proposals, unplanned requests and solver details", async () => {
    const ro = user("ro-southern");
    const calls = evcServer({ "POST /api/evc/schedule:propose": () => [201, PROPOSAL] });
    const u = userEvent.setup();
    render(<EvcView who={ro} me={ME(ro)} />);
    await u.click(await screen.findByRole("button", { name: "Propose schedule" }));
    expect(await screen.findByRole("heading", { name: /CP-SAT proposal/ })).toBeInTheDocument();
    const body = JSON.parse(calls.find((c) => c.method === "POST").body);
    expect(body).toMatchObject({ algorithm: "CPSAT", region: "Southern" });
    expect(body.run_id).toMatch(/^[0-9a-f-]{36}$/);
    expect(screen.getByText("Optimal")).toBeInTheDocument();
    expect(screen.getByText(/no slot in the window had a full eligible panel/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Compare proposals" })).toBeInTheDocument();
    // regional officers propose but never publish
    expect(screen.queryByRole("button", { name: "Publish this schedule" })).toBeNull();
    expect(screen.getByText(/Only the bureau publishes a schedule/)).toBeInTheDocument();
  });

  it("retries a lost proposal with the same run id and key", async () => {
    const ro = user("ro-southern");
    let attempt = 0;
    const calls = evcServer({ "POST /api/evc/schedule:propose": () => (++attempt === 1 ? [0, null] : [201, PROPOSAL]) });
    const u = userEvent.setup();
    render(<EvcView who={ro} me={ME(ro)} />);
    await u.click(await screen.findByRole("button", { name: "Propose schedule" }));
    await screen.findByText(/cannot be made twice/);
    await u.click(screen.getByRole("button", { name: "Propose schedule" }));
    await screen.findByRole("heading", { name: /CP-SAT proposal/ });
    const [a, b] = calls.filter((c) => c.method === "POST");
    expect(JSON.parse(b.body).run_id).toBe(JSON.parse(a.body).run_id);
    expect(b.headers["Idempotency-Key"]).toBe(a.headers["Idempotency-Key"]);
  });

  it("lets the bureau publish and explains a double booking in plain words", async () => {
    const bureau = user("bureau-officer");
    const calls = evcServer({
      "POST /api/evc/schedule:propose": () => [201, PROPOSAL],
      "POST /api/evc/schedule:publish": () => [409, { error: "Conflict", detail: "EVC_EXPERT_DOUBLE_BOOKED" }],
    });
    const u = userEvent.setup();
    render(<EvcView who={bureau} me={ME(bureau)} />);
    await u.click(await screen.findByRole("button", { name: "Propose schedule" }));
    await u.click(await screen.findByRole("button", { name: "Publish this schedule" }));
    expect(await screen.findByText(REASONS.EVC_EXPERT_DOUBLE_BOOKED)).toBeInTheDocument();
    const publish = calls.find((c) => c.url === "/api/evc/schedule:publish");
    expect(JSON.parse(publish.body)).toEqual({ run_id: PROPOSAL.run_id });
  });

  it("shows a published schedule once the bureau publishes it", async () => {
    const bureau = user("bureau-officer");
    evcServer({
      "POST /api/evc/schedule:propose": () => [201, PROPOSAL],
      "POST /api/evc/schedule:publish": { ...PROPOSAL, status: "PUBLISHED", published_count: 1, assignments: [] },
    });
    const u = userEvent.setup();
    render(<EvcView who={bureau} me={ME(bureau)} />);
    await u.click(await screen.findByRole("button", { name: "Propose schedule" }));
    await u.click(await screen.findByRole("button", { name: "Publish this schedule" }));
    expect(await screen.findByText(/Published 1 visit\./)).toBeInTheDocument();
  });

  it.each([
    ["EVC_SLOT_CAPACITY_EXHAUSTED", /already full with published visits/],
    ["EVC_PUBLISH_RECHECK_FAILED", /no longer passes the checks/],
  ])("explains %s", (code, text) => {
    expect(refusalText({ status: 409, reason: code, message: code })).toMatch(text);
  });

  it("gives the auditor the queue and pool to read but nothing to plan or manage", async () => {
    const auditor = user("auditor");
    evcServer();
    render(<EvcView who={auditor} me={ME(auditor)} />);
    expect(await screen.findByRole("heading", { name: /Visit requests/ })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: /Expert pool/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Propose schedule" })).toBeNull();
    expect(screen.queryByRole("form", { name: "Register an expert" })).toBeNull();
    expect(screen.queryByRole("form", { name: "Publish a proposal by reference" })).toBeNull();
  });

  it("lets a regional officer manage the pool of its own region only", async () => {
    const ro = user("ro-southern");
    const calls = evcServer({ "POST /api/evc/experts": () => [201, { id: "e9", user_ref: "u", region: "SOUTHERN", expertise_tags: ["DEMO"], active: true }] });
    const u = userEvent.setup();
    render(<EvcView who={ro} me={ME(ro)} />);
    const form = await screen.findByRole("form", { name: "Register an expert" });
    expect(within(form).getByLabelText("Region")).toHaveAttribute("readonly");
    await u.click(within(form).getByRole("button", { name: "Register" }));
    expect(await within(form).findByText(/Registered expert e9 in SOUTHERN/)).toBeInTheDocument();
    expect(JSON.parse(calls.find((c) => c.method === "POST").body)).toMatchObject({ region: "Southern", expertise_tags: ["DEMO"] });
  });
});

describe("scorecard routing line", () => {
  it("renders 22 of 22 with the answer key's unverified-source label", async () => {
    fakeServer({ "GET /api/analytics/scorecard": { generated_at: "2026-10-28T10:00:00Z", items: [{
      key: "routing", title: "Workflow routing vs APH Table 2.3", kind: "EVALUATED_ON_ANSWER_KEY", method: "Compares stages.",
      outcome: "PASS", ruleset: "aph-2024-27@r1",
      source: "Frozen docs/p1/expected_routes.csv. DEMO ASSUMPTION ACCEPTANCE_SOURCE_UNVERIFIED: no row is verified (PRIMARY_SOURCE_UNAVAILABLE).",
      result: { cases: 22, correct: 22, accuracy: 1, mismatches: [] },
    }] } });
    render(<ScorecardView who={user("bureau-officer")} />);
    expect(await screen.findByText(/22 of 22 categories routed as expected \(100%\)/)).toBeInTheDocument();
    expect(screen.getByText("Acceptance source unverified")).toBeInTheDocument();
    expect(screen.getByText("Pass", { selector: ".badge" })).toBeInTheDocument();
    expect(screen.getByText(/Against an unverified transcription/)).toBeInTheDocument();
  });
});
