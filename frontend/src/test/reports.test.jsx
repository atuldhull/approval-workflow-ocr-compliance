import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DEMO_USERS } from "../api.js";
import DashboardView from "../views/DashboardView.jsx";
import DeliveryView from "../views/DeliveryView.jsx";
import InboxView from "../views/InboxView.jsx";
import ReportsView from "../views/ReportsView.jsx";
import { fakeServer } from "./fakeServer.js";

const ME = (u) => ({ user_id: u.user, role: u.role, region: u.region ?? null, institution_id: u.institution ?? null });
const RO = DEMO_USERS.find((u) => u.role === "RO_OFFICER");
const HEAD = DEMO_USERS.find((u) => u.role === "BUREAU_HEAD");
const SUNRISE = DEMO_USERS[0];
const CASE = "1a2b3c4d-0000-4000-8000-00000000abcd";

const catalogue = [
  { type: "pendency", title: "Pendency by region and stage", source: "Replayed from workflow events", columns: [] },
  { type: "overdue", title: "Overdue clocks", source: "Replayed from deadline events", columns: [] },
];
const head = { ledger_head: { seq: 42, entry_hash: "e".repeat(64) }, snapshot_hash: "abcdef0123456789".padEnd(64, "0") };
const pendency = {
  type: "pendency", title: "Pendency by region and stage", source: "Replayed from workflow events", scope: { region: "Southern" },
  columns: [{ key: "region", label: "Region" }, { key: "stage", label: "Stage" }, { key: "count", label: "Applications" }],
  rows: [{ region: "Southern", stage: "SCRUTINY", count: 2 }], total: 2,
  coverage: { note: "Stage is the stage recorded by workflow events this projection understands.", unhandled_event_types: {} }, ...head,
};
const overdue = {
  type: "overdue", title: "Overdue clocks", source: "Replayed from deadline events", scope: { region: "Southern", as_of: "2026-10-28" },
  columns: [{ key: "case_ref", label: "Case" }, { key: "rule_id", label: "Rule" }, { key: "owner_role", label: "Owner" },
    { key: "days_overdue", label: "Days overdue" }, { key: "status", label: "Clock" }, { key: "application_id", label: "Case id" }],
  rows: [{ application_id: CASE, case_ref: CASE.slice(0, 8), rule_id: "LOA_DEPOSIT_AFFIDAVIT_15D", owner_role: "INSTITUTION",
    days_overdue: 12, status: "BREACHED" }],
  total: { overdue: 1 }, coverage: { note: "Paused clocks are not overdue.", unhandled_event_types: {} }, ...head,
};

describe("reports", () => {
  it("shows the chosen report in words with its provenance, and opens the case from a row", async () => {
    fakeServer({ "GET /api/reports": catalogue, "GET /api/reports/pendency": pendency, "GET /api/reports/overdue": overdue });
    const onNavigate = vi.fn();
    const user = userEvent.setup();
    render(<ReportsView who={RO} me={ME(RO)} onNavigate={onNavigate} />);
    const table = await screen.findByRole("table", { name: "Pendency by region and stage" });
    expect(within(table).getByRole("cell", { name: "2" })).toBeInTheDocument();
    expect(screen.getByText(/Computed at ledger entry #42, snapshot/)).toHaveTextContent("abcdef012345");
    expect(screen.getByText("Southern region only")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Overdue clocks" }));
    const rows = await screen.findByRole("table", { name: "Overdue clocks" });
    expect(rows).toHaveTextContent("Fifteen days after an LoA for the deposit proof and affidavit");
    expect(rows).toHaveTextContent("Institution");
    expect(within(rows).queryByText("LOA_DEPOSIT_AFFIDAVIT_15D")).toBeNull();
    expect(within(rows).queryByRole("columnheader", { name: "Case id" })).toBeNull();   // in the CSV, not the table
    expect(screen.getByText("days counted to 2026-10-28 (IST)")).toBeInTheDocument();
    await user.click(within(rows).getByRole("button", { name: `Open case ${CASE.slice(0, 8)}` }));
    expect(onNavigate).toHaveBeenCalledWith("applications", { caseId: CASE });
  });

  it("puts the document validity report into words: document, date source, days left and state", async () => {
    const validity = {
      type: "document_validity", title: "Document validity", source: "Read from the compliance validity records and their deadline clocks",
      scope: { region: null, as_of: "2026-10-28" },
      columns: [{ key: "case_ref", label: "Case" }, { key: "document", label: "Document" }, { key: "validity_basis", label: "Date from" },
        { key: "days_left", label: "Days left" }, { key: "validity_state", label: "State" }, { key: "live_lease_ok", label: "Live lease covers longest course" },
        { key: "deadline_status", label: "Clock" }, { key: "application_id", label: "Case id" }],
      rows: [{ application_id: CASE, case_ref: CASE.slice(0, 8), doc_type: "FIRE_NOC", document: "fire noc", validity_basis: "OFFICER_RECORDED",
        days_left: -3, validity_state: "EXPIRED", live_lease_ok: null, deadline_status: "BREACHED" },
      { application_id: CASE, case_ref: CASE.slice(0, 8), doc_type: "LEASE_DEED", document: "lease deed", validity_basis: "DOCUMENT_FACT",
        days_left: 3650, validity_state: "VALID", live_lease_ok: true, deadline_status: "RUNNING" }],
      total: { records: 2 }, coverage: { note: "Read from the compliance validity records." }, ...head,
    };
    fakeServer({ "GET /api/reports": [...catalogue, { type: "document_validity", title: "Document validity", source: "", columns: [] }],
      "GET /api/reports/pendency": pendency, "GET /api/reports/document_validity": validity });
    const user = userEvent.setup();
    render(<ReportsView who={HEAD} me={ME(HEAD)} />);
    await screen.findByRole("table", { name: "Pendency by region and stage" });
    await user.click(screen.getByRole("button", { name: "Document validity" }));
    const table = await screen.findByRole("table", { name: "Document validity" });
    expect(table).toHaveTextContent("Fire safety no-objection certificate");
    expect(table).toHaveTextContent("Registered land lease deed");
    expect(table).toHaveTextContent("Recorded by an officer");
    expect(table).toHaveTextContent("Expired 3 days ago");
    expect(table).toHaveTextContent("3650 days left");
    expect(within(table).getByText("Expired")).toBeInTheDocument();
    expect(within(table).getByText("Yes")).toBeInTheDocument();
    expect(within(table).queryByText("EXPIRED")).toBeNull();
    expect(within(table).queryByText("OFFICER_RECORDED")).toBeNull();
  });

  it("downloads the CSV through the API with the caller's identity", async () => {
    const csv = new Blob(["Region,Stage,Applications\n"], { type: "text/csv" });
    const calls = fakeServer({
      "GET /api/reports": catalogue,
      // the same path answers CSV when asked with format=csv
      "GET /api/reports/pendency": () => [200, calls.at(-1).url.includes("format=csv") ? csv : pendency],
    });
    URL.createObjectURL = vi.fn(() => "blob:report");
    URL.revokeObjectURL = vi.fn();
    const user = userEvent.setup();
    render(<ReportsView who={HEAD} me={ME(HEAD)} />);
    await screen.findByRole("table", { name: "Pendency by region and stage" });
    await user.click(screen.getByRole("button", { name: "Download CSV" }));
    expect(await screen.findByText(/CSV downloaded/)).toBeInTheDocument();
    const download = calls.find((c) => c.url.includes("format=csv"));
    expect(download.headers).toMatchObject({ "X-Demo-Role": "BUREAU_HEAD" });
    expect(URL.createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
  });
});

describe("dashboard breakdowns", () => {
  it("shows the bottleneck, time in stage and institutions by name or reference", async () => {
    fakeServer({ "GET /api/analytics/dashboard": { scope: { region: null, as_of: "2026-10-24T10:00:00Z" }, sections: [
      { key: "flow", title: "Time in current stage and bottlenecks", status: "AVAILABLE", source: "Replayed from workflow stage events",
        data: { buckets: { "0-7 days": 1, "8-30 days": 1 }, by_stage: [{ stage: "SCRUTINY", cases: 2, median_days: 5, max_days: 10 }],
          bottleneck: "SCRUTINY", slowest: "SCRUTINY", not_timed: 0 } },
      { key: "institutions", title: "By institution", status: "AVAILABLE", source: "Replayed from workflow and deadline events",
        data: { institutions: 2, rows: [{ institution_id: SUNRISE.institution, cases: 2, in_process: 1, overdue: 1 },
          { institution_id: "99999999-0000-4000-8000-000000000009", cases: 1, in_process: 1, overdue: 0 }] } },
    ] } });
    render(<DashboardView who={HEAD} />);
    const flow = (await screen.findByRole("heading", { name: "Time in current stage and bottlenecks" })).closest("section");
    expect(within(flow).getByRole("table", { name: "Cases and time by current stage" })).toHaveTextContent("Scrutiny");
    expect(within(flow).getAllByText("Scrutiny").length).toBeGreaterThan(1);    // bottleneck and slowest tiles
    const inst = screen.getByRole("heading", { name: "By institution" }).closest("section");
    const table = within(inst).getByRole("table", { name: "Applications by institution" });
    expect(table).toHaveTextContent("Sunrise Institute of Technology (DEMO)");
    expect(table).toHaveTextContent("Institution 99999999");
  });
});

describe("event notifications", () => {
  const notice = {
    id: "n2", alert_id: null, source_event_id: "e1e2e3e4-0000", template: "compliance.evidence_rejected", subject: "Evidence rejected",
    text: "Case 1a2b3c4d: the evidence for the deposit was rejected (amount mismatch). It is due on 15 Sep 2025 (IST).",
    action: "Submit new evidence on the Compliance screen before the due date.", case_ref: "1a2b3c4d",
    links: { application_id: CASE, obligation_id: "0b0b0b0b-0000" }, created_at: "2026-10-24T10:00:00Z", read_at: null,
  };

  it("the inbox says what happened, what to do, and links to the records", async () => {
    fakeServer({ "GET /api/notifications/inbox": [notice] });
    const onNavigate = vi.fn();
    const user = userEvent.setup();
    render(<InboxView who={SUNRISE} onNavigate={onNavigate} />);
    await user.click(await screen.findByRole("button", { name: /^Evidence rejected/ }));
    expect(screen.getByText(notice.text)).toBeInTheDocument();
    expect(screen.getByText(/Submit new evidence on the Compliance screen/)).toBeInTheDocument();
    expect(screen.getByText("Recorded event")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open alerts to acknowledge" })).toBeNull();   // not an alert
    await user.click(screen.getByRole("button", { name: "Open the obligation" }));
    expect(onNavigate).toHaveBeenCalledWith("compliance", { obligationId: "0b0b0b0b-0000" });
    await user.click(screen.getByRole("button", { name: "Open the case" }));
    expect(onNavigate).toHaveBeenCalledWith("applications", { caseId: CASE });
    expect(screen.getAllByText("case 1a2b3c4d").length).toBeGreaterThan(0);
  });

  it("alert delivery lists messages about events beside alert messages", async () => {
    const base = { channel: "in_app", status: "DELIVERED", attempts: 1, last_error: null, next_attempt_at: null,
      created_at: "2026-10-24T10:00:00Z", delivered_at: "2026-10-24T10:00:01Z", dead_at: null };
    fakeServer({
      "GET /api/notifications/health": { by_status: { PENDING: 0, SENDING: 0, DELIVERED: 2, DEAD: 0 }, providers: {} },
      "GET /api/notifications/outbox": [
        { ...base, id: "o1", alert_id: "a1a1a1a1-0000", source_event_id: null, template: "deadline.reminder" },
        { ...base, id: "o2", alert_id: null, source_event_id: "e1e2e3e4-0000", template: "letter.registered" },
      ],
    });
    render(<DeliveryView who={HEAD} me={ME(HEAD)} />);
    const table = await screen.findByRole("table", { name: "Outbox messages" });
    expect(table).toHaveTextContent("Letter registered");
    expect(table).toHaveTextContent("Event e1e2e3e4");
    expect(table).toHaveTextContent("Alert a1a1a1a1");
  });
});
