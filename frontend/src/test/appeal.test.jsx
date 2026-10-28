import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DEMO_USERS } from "../api.js";
import CaseDetail from "../components/CaseDetail.jsx";
import { fakeServer } from "./fakeServer.js";
import { sentence } from "../nav.js";

const user = (key) => DEMO_USERS.find((u) => u.key === key);
const ME = (u) => ({ user_id: u.user, role: u.role, region: u.region ?? null, institution_id: u.institution ?? null });
const SUNRISE = user("sunrise");
const ID = "4d96fec8-ff6b-421e-97e9-914b93618c17";
const ROUTE = [{ stage: "SCRUTINY", when: "always" }];
const HASH = "a".repeat(64);
const LOD_VISIT = { id: "v1", stage: "SCRUTINY", entered_at: "2027-01-02T05:00:00Z", exited_at: "2027-01-05T05:00:00Z",
  outcome: "ISSUE_LOD", reason_code: null, note_ref: null };
const caseRec = (over = {}) => ({
  case_id: ID, institution_id: SUNRISE.institution, region: "Southern", stage: "SCRUTINY", status: "IN_PROCESS", version: 5,
  route_id: "CHANGE_OF_NAME", ruleset_key: "aph-2024-27@r1", preview_ruleset_key: null, route: ROUTE,
  clause_citation: { source_document: "APH_2024_27", locator: "TABLE_2_3", clause: "2.23.4", row: 4, page: 46, status: "VERIFIED" },
  stage_history: [LOD_VISIT], available_actions: [], assumption_status: "DEMO_ASSUMPTION", ...over,
});
const act = (action, enabled, reason_code = null, extra = {}) => ({
  action, targets: [], enabled, reason_code, reason_codes_required: false, aliases: [], ...extra,
});
const appeal = (over = {}) => ({
  id: "ap1", status: "WINDOW_OPEN", max_appeals: 1, opened_at: "2027-01-05T05:00:00Z", lod_letter_ref: "l1",
  window: { rule_id: "APPEAL_7D", deadline_id: "d1", due_date: "2027-01-12", clock_status: "RUNNING", days_left: 4,
    clause: "2.24(a)", source_status: "verified" },
  filed_at: null, filed_by: null, grounds_note_hash: null, hearing_no: 0, recommendation: null, recommended_at: null,
  recommended_by: null, recommendation_report_ref: null, outcome: null, decided_at: null, decided_by: null,
  decision_letter_ref: null, speaking_order_note_hash: null, closed_at: null, source: { status: "VERIFIED" }, ...over,
});

describe("appeal against an LoD", () => {
  it("shows the institution the open window with days left and lets it file with grounds", async () => {
    const calls = fakeServer({
      [`GET /api/cases/${ID}`]: caseRec({ available_actions: [act("file_appeal", true, null, { targets: ["SAC"] }),
        act("withdraw", false, "APPEAL_WINDOW_OPEN")] }),
      [`GET /api/cases/${ID}/appeal`]: { case_id: ID, appeal: appeal() },
      [`POST /api/cases/${ID}/actions`]: { case_id: ID, stage: "SAC", status: "IN_PROCESS", version: 6, available_actions: [] },
    });
    const u = userEvent.setup();
    render(<CaseDetail who={SUNRISE} me={ME(SUNRISE)} id={ID} />);
    const panel = await screen.findByRole("region", { name: "Appeal against the LoD" });
    expect(await within(panel).findByText("Appeal window open")).toBeInTheDocument();
    expect(within(panel).getByText("4")).toBeInTheDocument();
    expect(within(panel).getByText("APH cl. 2.24(a)")).toBeInTheDocument();
    expect(screen.getByText(/only the institution's appeal, or the window's lapse, can follow/)).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "Open" }));
    await u.type(screen.getByLabelText(/Grounds of appeal/), "Fictional DEMO grounds.");
    await u.click(screen.getByRole("button", { name: "File an appeal to the Council" }));
    const post = calls.find((c) => c.method === "POST");
    expect(JSON.parse(post.body)).toMatchObject({ action: "file_appeal", expected_version: 5, note: "Fictional DEMO grounds." });
  });

  it("requires the speaking order before the bureau head can issue a Letter of Rejection", async () => {
    const head = user("bureau-head");
    fakeServer({
      [`GET /api/cases/${ID}`]: caseRec({ stage: "SAC", available_actions: [act("issue_lor", true, null, { targets: ["REJECTED"] })],
        stage_history: [LOD_VISIT, { ...LOD_VISIT, id: "v2", stage: "SAC", exited_at: null, outcome: null }] }),
      [`GET /api/cases/${ID}/appeal`]: { case_id: ID, appeal: appeal({ status: "NOT_RECOMMENDED", recommendation: "NOT_RECOMMEND",
        recommended_at: "2027-01-08T05:00:00Z", filed_at: "2027-01-06T05:00:00Z", grounds_note_hash: HASH, hearing_no: 1,
        window: { ...appeal().window, clock_status: "MET", days_left: null } }) },
      [`GET /api/cases/${ID}/committees`]: [{ id: "c1", type: "SAC", ordinal: 2, status: "ACTIVE", members: [], task_count: 0,
        report_count: 1, latest_report: { id: "r1", version_no: 1, created_at: "2027-01-07T05:00:00Z", author_user_ref: "u", content_note_hash: HASH } }],
      [`GET /api/applications/${ID}`]: { id: ID, category: "CHANGE_OF_NAME", academic_year: "2027-28", status: "IN_PROCESS",
        current_stage: "SAC", submitted_at: "2027-01-02T05:00:00Z" },
    });
    const u = userEvent.setup();
    render(<CaseDetail who={head} me={ME(head)} id={ID} />);
    expect(await screen.findByText("SAC does not recommend; awaiting the Council")).toBeInTheDocument();
    expect(screen.getAllByText("Appellate committee (SAC)").length).toBeGreaterThan(0);  // journey shows the SAC step
    await u.click(await screen.findByRole("button", { name: "Open" }));
    await u.selectOptions(screen.getByLabelText("Decision cited"), "r1");
    await u.type(screen.getByLabelText("Letter number (F. No.)"), "F.No. DEMO/LOR");
    const submit = screen.getByRole("button", { name: "Issue Letter of Rejection" });
    expect(submit).toBeDisabled();
    await u.type(screen.getByLabelText(/Speaking order/), "Fictional DEMO reasons.");
    expect(submit).toBeEnabled();
  });
});

describe("electronic case summary", () => {
  it("opens a printable summary that shows fingerprints, withheld sections and prints with the browser", async () => {
    const auditor = user("auditor");
    fakeServer({
      [`GET /api/cases/${ID}`]: caseRec({ stage: null, status: "REJECTED" }),
      [`GET /api/cases/${ID}/appeal`]: { case_id: ID, appeal: appeal({ status: "LAPSED", closed_at: "2027-01-13T05:00:00Z",
        window: { ...appeal().window, clock_status: "WAIVED", days_left: null } }) },
      [`GET /api/cases/${ID}/summary`]: {
        case_id: ID, generated_at: "2027-01-14T05:00:00Z", institution_id: SUNRISE.institution, region: "Southern",
        academic_year: "2027-28", route_id: "CHANGE_OF_NAME", route_label: "Change of name of institution",
        clause_citation: caseRec().clause_citation, ruleset_key: "aph-2024-27@r1", status: "REJECTED", stage: null, version: 7,
        submitted_at: "2027-01-02T05:00:00Z", route: ROUTE, stage_visits: [LOD_VISIT], deficiencies: [],
        committees: [{ id: "c1", ordinal: 1, type: "SCRUTINY", status: "ACTIVE", member_count: 1, reports: [
          { id: "r1", version_no: 1, created_at: "2027-01-04T05:00:00Z", author_user_ref: "u", content_note_hash: HASH }] }],
        evc_requests: [], open_deadlines: null, obligations: null, letters: null,
        appeal: appeal({ status: "LAPSED" }), withheld: ["open_deadlines", "obligations", "letters"], assumption_status: null,
      },
    });
    const print = vi.fn();
    vi.stubGlobal("print", print);
    const u = userEvent.setup();
    render(<CaseDetail who={auditor} me={ME(auditor)} id={ID} />);
    await u.click(await screen.findByRole("button", { name: "Case summary" }));
    const doc = await screen.findByRole("article", { name: "Change of name of institution" });
    expect(within(doc).getByText(/APH 2024-27 Table 2.3, cl. 2.23.4, row 4, p.46/)).toBeInTheDocument();
    expect(within(doc).getAllByText(/Not shown: your role may not read/)).toHaveLength(3);
    expect(within(doc).getByTitle(`SHA-256 ${HASH}`)).toBeInTheDocument();
    expect(within(doc).getByText("Issue Letter of Deficiency")).toBeInTheDocument();
    await u.click(within(doc).getByRole("button", { name: "Print" }));
    expect(print).toHaveBeenCalledTimes(1);
    vi.unstubAllGlobals();
  });
});

describe("appeal wording", () => {
  it("writes the SAC as an acronym in committee names", () => {
    expect(sentence("SAC")).toBe("SAC");
    expect(sentence("SHC")).toBe("SHC");
  });
});
