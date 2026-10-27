import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { DEMO_USERS } from "../api.js";
import { keepsKey } from "../actionKey.js";
import CaseDetail from "../components/CaseDetail.jsx";
import ScorecardView from "../views/ScorecardView.jsx";
import EvcView from "../views/EvcView.jsx";
import { REASONS, explanationText, refusalText } from "../workflowText.js";
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

const RUN_REF = "cd6f635d-ae83-4362-a49a-553ecd807fc3";
const VOCAB_PATH = "GET /api/rulesets/aph-2024-27%40r1/deficiency-vocabulary";
const VOCAB = { ruleset_key: "aph-2024-27@r1", item_keys: ["DEMO_CORE_REFERENCE", "DEMO_FACILITY_REFERENCE"],
  reason_codes: ["DEMO_REASON", "DEMO_MISSING_EVIDENCE"], response_rule_id: "INSTITUTION_RESPONSE", source_status: "DEMO_ASSUMPTION",
  assumption_code: "DEFICIENCY_RESPONSE_WINDOW_UNCONFIRMED" };

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
      [VOCAB_PATH]: VOCAB,
    });
    const u = userEvent.setup();
    render(<CaseDetail who={scrutiny} me={ME(scrutiny)} id={ID} />);
    await u.click(await screen.findByRole("button", { name: "Open" }));
    const form = screen.getByRole("form", { name: "Record a deficiency" });
    await u.click(await within(form).findByLabelText("Core reference document"));
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
it("offers the deficiency items and reasons the pinned ruleset publishes, not a mirrored list", async () => {
    const scrutiny = user("scrutiny");
    const calls = fakeServer({
      [`GET /api/cases/${ID}`]: caseRec({ available_actions: [act("record_deficiency", true, null, { reason_codes_required: true })] }),
      [VOCAB_PATH]: { ...VOCAB, item_keys: ["DEMO_CORE_REFERENCE", "DEMO_NEW_ITEM"], reason_codes: ["DEMO_REASON", "DEMO_NEW_REASON"] },
    });
    const u = userEvent.setup();
    render(<CaseDetail who={scrutiny} me={ME(scrutiny)} id={ID} />);
    await u.click(await screen.findByRole("button", { name: "Open" }));
    const form = screen.getByRole("form", { name: "Record a deficiency" });
    expect(await within(form).findByLabelText("Demo new item")).toBeInTheDocument();
    expect(within(form).queryByLabelText("Safety reference document")).toBeNull();
    const reasons = within(within(form).getByLabelText("Reason")).getAllByRole("option").map((o) => o.textContent);
    expect(reasons).toEqual(["Choose a reason", "Other recorded reason", "Demo new reason"]);
    expect(calls.some((c) => c.url === "/api/rulesets/aph-2024-27%40r1/deficiency-vocabulary")).toBe(true);
  });
});

describe("case screen reads", () => {
  it("shows the published visit date, half-day and panel references from the per-case EVC read", async () => {
    const scrutiny = user("scrutiny");
    const calls = fakeServer({
      [`GET /api/cases/${ID}`]: caseRec({ stage: "EVC" }),
      [`GET /api/applications/${ID}/evc`]: { application_id: ID, region: "Southern", current: null, requests: [{
        id: "q1", status: "PUBLISHED", category: "NEW_PROGRAMME", requested_at: "2026-10-27T19:00:00Z", earliest_date: "2026-10-28",
        due_by: "2026-11-04", closed_at: null, ruleset_key: "aph-2024-27@r1", rule_id: "EVC_PROCESSING", days_waiting: 1, duration_days: 7,
        source_status: "DEMO_ASSUMPTION", assumption_code: "EVC_DURATION_UNCONFIRMED",
        visit: { assignment_id: "a1", run_id: RUN_REF, algorithm: "CPSAT", date: "2026-10-30", slot_part: "PM", panel_role: "DEMO_PANEL",
          expert_ids: ["11111111-aaaa-4000-8000-000000000001", "22222222-aaaa-4000-8000-000000000002"], simulation_status: "SIMULATED",
          selector_label: "SIMULATED authorised selector (stand-in)" } }] },
    });
    render(<CaseDetail who={scrutiny} me={ME(scrutiny)} id={ID} />);
    const zone = await screen.findByRole("region", { name: "Expert visit (EVC)" });
    expect(await within(zone).findByText("Visit published")).toBeInTheDocument();
    expect(within(zone).getByText(/30 Oct 2026 · Afternoon/)).toBeInTheDocument();
    expect(within(zone).getByText("11111111")).toBeInTheDocument();
    expect(within(zone).getByText("22222222")).toBeInTheDocument();
    expect(calls.some((c) => c.url.startsWith("/api/evc/queue"))).toBe(false);
  });

  it("lists the case's committees from the per-case committee read, not from the timeline", async () => {
    const scrutiny = user("scrutiny");
    const C = "cccccccc-0000-4000-8000-000000000001";
    fakeServer({
      [`GET /api/cases/${ID}`]: caseRec(),
      [`GET /api/cases/${ID}/timeline`]: [],
      [`GET /api/cases/${ID}/committees`]: [{ id: C, application_id: ID, ordinal: 1, type: "SCRUTINY", status: "ACTIVE",
        members: [{ user_ref: scrutiny.user, role: "CHAIR" }], task_count: 0, report_count: 0, latest_report: null, assumption_status: "DEMO_ASSUMPTION" }],
      [`GET /api/committees/${C}`]: { id: C, application_id: ID, type: "SCRUTINY", status: "ACTIVE",
        members: [{ user_ref: scrutiny.user, role: "CHAIR" }], tasks: [], report_count: 0, assumption_status: "DEMO_ASSUMPTION" },
      [`GET /api/committees/${C}/reports`]: [],
    });
    render(<CaseDetail who={scrutiny} me={ME(scrutiny)} id={ID} />);
    const zone = await screen.findByRole("region", { name: "Committee workspace" });
    expect(await within(zone).findByRole("article", { name: "Scrutiny committee" })).toBeInTheDocument();
    expect(within(zone).getByText("you (Chair)")).toBeInTheDocument();
  });

  it("opens a case for a regional officer with the application record (academic year)", async () => {
    const ro = user("ro-southern");
    const calls = fakeServer({
      [`GET /api/cases/${ID}`]: caseRec(),
      [`GET /api/applications/${ID}`]: { ...APP, status: "IN_PROCESS", current_stage: "SCRUTINY" },
    });
    render(<CaseDetail who={ro} me={ME(ro)} id={ID} />);
    expect(await screen.findByText(/· 2027-28/)).toBeInTheDocument();
    expect(calls.some((c) => c.url === `/api/applications/${ID}`)).toBe(true);
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
const RUN = "cd6f635d-ae83-4362-a49a-553ecd807fc3";
const LABELS = { selector_label: "SIMULATED authorised selector (stand-in)", simulation_status: "SIMULATED", source_status: "DEMO_ASSUMPTION",
  assumption_code: "EDF_PLANNING_UNCONFIRMED" };
const SUMMARY = {
  ...LABELS, run_id: RUN, algorithm: "CPSAT", status: "PROPOSED", region_scope: "SOUTHERN", horizon_start: "2026-10-28",
  horizon_end: "2026-11-10", created_at: "2026-10-27T19:20:19Z", input_fingerprint: "98818fce327d022e9e45f0dc",
  metrics: { queue_count: 2, scheduled: 1, unscheduled: 1, late_count: 0, total_lateness: 0, max_lateness: 0, total_waiting: 0,
    hard_constraint_violations: 0, lateness_days: [0, null] },
  expert_daily_cap: 1, slot_capacity: 4, candidate_slots: 12, outcomes_recorded: true,
};
const OTHER = "eeeeeeee-0000-4000-8000-000000000002";
const DETAIL = {
  ...SUMMARY,
  solver: { solver_status: 4, objective_value: 6, best_bound: 6, repair_rounds: 0, candidate_count: 12, edf_scheduled: 1,
    fallback_to_edf: false, candidate_slots: 12 },
  proposals: [{ application_id: ID, request_id: "q1", assignment_id: "a1", slot_id: "s1", date: "2026-10-28", slot_part: "PM",
    expert_ids: ["e1", "e2", "e3"], due_by: "2026-11-04", lateness_days: 0, published: false }],
  unscheduled: [{ request_id: "q2", application_id: OTHER, reason_code: "NO_FEASIBLE_SLOT", explanation_code: "COI_ONLY" }],
  withdrawn: [],
};
const PROPOSAL = { ...DETAIL, proposals: DETAIL.proposals.map(({ published, ...p }) => p) };
const page = (items) => ({ items, total: items.length, offset: 0, limit: 20 });

// The run list and run read follow what the fake server has stored: nothing until a proposal is made.
function evcServer(extra = {}, { runs = [] } = {}) {
  const stored = { list: runs };
  const routes = {
    "GET /api/evc/queue": QUEUE, "GET /api/evc/experts": POOL, "GET /api/institutions": [],
    "GET /api/evc/schedule/runs": () => [200, page(stored.list.map(({ solver, proposals, unscheduled, withdrawn, ...r }) => r))],
    [`GET /api/evc/schedule/runs/${RUN}`]: () => {
      const run = stored.list.find((r) => r.run_id === RUN);
      return run ? [200, run] : [404, { error: "NotFound", detail: "EVC_RUN_NOT_FOUND" }];
    },
    ...extra,
  };
  const propose = routes["POST /api/evc/schedule:propose"];
  if (propose) {
    routes["POST /api/evc/schedule:propose"] = async (init) => {
      const [status, body] = await propose(init);
      if (status === 201) stored.list = [DETAIL];
      return [status, body];
    };
  }
  const calls = fakeServer(routes);
  calls.stored = stored;
  return calls;
}

describe("EVC scheduling", () => {
  it("labels the simulated selector and scopes a regional officer's queue and runs to its region", async () => {
    const ro = user("ro-southern");
    const calls = evcServer();
    render(<EvcView who={ro} me={ME(ro)} />);
    expect(await screen.findByText("Queued: no visit planned yet")).toBeInTheDocument();
    expect(screen.getByText(/real selection of experts happens on AICTE's own portal/)).toBeInTheDocument();
    expect(calls.find((c) => c.url.startsWith("/api/evc/queue")).url).toContain("region=Southern");
    expect(await screen.findByText("No proposal runs in this scope yet.")).toBeInTheDocument();
    expect(calls.find((c) => c.url.startsWith("/api/evc/schedule/runs")).url).toContain("region=Southern");
  });

  it("proposes with CP-SAT, then reads the run back with its limits, unplanned reasons and solver details", async () => {
    const ro = user("ro-southern");
    const calls = evcServer({ "POST /api/evc/schedule:propose": () => [201, PROPOSAL] });
    const u = userEvent.setup();
    render(<EvcView who={ro} me={ME(ro)} />);
    await u.click(await screen.findByRole("button", { name: "Propose schedule" }));
    expect(await screen.findByRole("heading", { name: /CP-SAT proposal/ })).toBeInTheDocument();
    const body = JSON.parse(calls.find((c) => c.method === "POST").body);
    expect(body).toMatchObject({ algorithm: "CPSAT", region: "Southern" });
    expect(body.run_id).toMatch(/^[0-9a-f-]{36}$/);
    expect(calls.some((c) => c.url === `/api/evc/schedule/runs/${RUN}`)).toBe(true);
    expect(screen.getByText("Optimal")).toBeInTheDocument();
    expect(screen.getByText(/conflicts of interest with the institution always leave it short/)).toBeInTheDocument();
    const limits = screen.getByLabelText("Planning limits used for this run");
    expect(within(limits).getByText("Visits per expert per day")).toBeInTheDocument();
    expect(within(limits).getByText(/The earliest 12 feasible slots per request/)).toBeInTheDocument();
    expect(within(limits).getByText(/4 in the slots this run created/)).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: /Proposal runs/ })).toBeInTheDocument();
    // regional officers propose but never publish or discard
    expect(screen.queryByRole("button", { name: "Publish this schedule" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Discard this proposal" })).toBeNull();
    expect(screen.getByText(/Only the bureau publishes or discards a schedule/)).toBeInTheDocument();
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

  it("lists runs made elsewhere so the bureau can publish one, and explains a double booking in plain words", async () => {
    const bureau = user("bureau-officer");
    const calls = evcServer({ "POST /api/evc/schedule:publish": () => [409, { error: "Conflict", detail: "EVC_EXPERT_DOUBLE_BOOKED" }] },
      { runs: [DETAIL] });
    const u = userEvent.setup();
    render(<EvcView who={bureau} me={ME(bureau)} />);
    const runs = await screen.findByRole("table", { name: "Proposal runs, newest first" });
    expect(within(runs).getByText("SOUTHERN")).toBeInTheDocument();
    expect(within(runs).getByText("Proposed, not published")).toBeInTheDocument();
    await u.click(await screen.findByRole("button", { name: "Publish this schedule" }));
    expect(await screen.findByText(REASONS.EVC_EXPERT_DOUBLE_BOOKED)).toBeInTheDocument();
    const publish = calls.find((c) => c.url === "/api/evc/schedule:publish");
    expect(JSON.parse(publish.body)).toEqual({ run_id: RUN });
    expect(publish.headers["Idempotency-Key"]).toBeTruthy();
    expect(screen.queryByRole("form", { name: "Publish a proposal by reference" })).toBeNull();
  });

  it("shows a published schedule once the bureau publishes it", async () => {
    const bureau = user("bureau-officer");
    const calls = evcServer({
      "POST /api/evc/schedule:publish": () => {
        calls.stored.list = [{ ...DETAIL, status: "PUBLISHED", proposals: DETAIL.proposals.map((p) => ({ ...p, published: true })) }];
        return [200, { ...LABELS, run_id: RUN, algorithm: "CPSAT", status: "PUBLISHED", published_count: 1, assignments: [] }];
      },
    }, { runs: [DETAIL] });
    const u = userEvent.setup();
    render(<EvcView who={bureau} me={ME(bureau)} />);
    await u.click(await screen.findByRole("button", { name: "Publish this schedule" }));
    expect(await screen.findByText(/Published 1 visit\./)).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("button", { name: "Discard this proposal" })).toBeNull());
    expect(screen.getAllByText("Published").length).toBeGreaterThan(0);
  });

  it("lets the bureau discard a proposed run and explains a refusal", async () => {
    const bureau = user("bureau-officer");
    let attempt = 0;
    const calls = evcServer({
      "POST /api/evc/schedule:discard": () => (++attempt === 1
        ? [409, { error: "Conflict", detail: "EVC_RUN_NOT_DISCARDABLE" }]
        : [200, { ...LABELS, run_id: RUN, algorithm: "CPSAT", status: "DISCARDED", discarded_count: 1,
          withdrawn: [{ application_id: ID, request_id: "q1", assignment_id: "a1" }] }]),
    }, { runs: [DETAIL] });
    const u = userEvent.setup();
    render(<EvcView who={bureau} me={ME(bureau)} />);
    await u.click(await screen.findByRole("button", { name: "Discard this proposal" }));
    expect(await screen.findByText(REASONS.EVC_RUN_NOT_DISCARDABLE)).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "Discard this proposal" }));
    expect(await screen.findByText(/Discarded\. 1 request is back in the queue/)).toBeInTheDocument();
    const posts = calls.filter((c) => c.url === "/api/evc/schedule:discard");
    expect(JSON.parse(posts[0].body)).toEqual({ run_id: RUN });
    expect(posts[1].headers["Idempotency-Key"]).not.toBe(posts[0].headers["Idempotency-Key"]); // a 409 is final
  });

  it("shows a discarded run's withdrawn requests and says when outcomes were not recorded", async () => {
    const auditor = user("auditor");
    evcServer({}, { runs: [{ ...DETAIL, status: "DISCARDED", proposals: [], unscheduled: [], outcomes_recorded: false,
      withdrawn: [{ request_id: "q1", application_id: ID }] }] });
    render(<EvcView who={auditor} me={ME(auditor)} />);
    expect(await screen.findByText(/Returned to the queue by the discard/)).toBeInTheDocument();
    expect(screen.getByText(/made before unplanned requests were recorded/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Discard this proposal" })).toBeNull();
  });

  it.each([
    ["NO_AVAILABILITY", /no qualified expert declared any free half-day/],
    ["PANEL_INCOMPLETE", /never enough at the same date and half-day/],
    ["CAPACITY_EXHAUSTED", /taken by other visits/],
    ["EXPERT_DAILY_CAP", /more visits on one day than the daily limit/],
    ["NO_FEASIBLE_SLOT", /no slot in its visit window/],
    ["SOMETHING_NEW", /^Something new\.$/],
  ])("explains unplanned code %s in plain words", (code, text) => {
    expect(explanationText(code)).toMatch(text);
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
