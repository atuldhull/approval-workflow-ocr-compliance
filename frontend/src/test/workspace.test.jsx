import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DEMO_USERS } from "../api.js";
import DocumentPreview from "../components/DocumentPreview.jsx";
import Lifecycle from "../components/Lifecycle.jsx";
import AuditView from "../views/AuditView.jsx";
import ComplianceView from "../views/ComplianceView.jsx";
import DashboardView from "../views/DashboardView.jsx";
import OverviewView from "../views/OverviewView.jsx";
import { fakeServer } from "./fakeServer.js";

const user = (key) => DEMO_USERS.find((u) => u.key === key);
const SUNRISE = user("sunrise");
const AUDITOR = user("auditor");
const ME = (u) => ({ user_id: u.user, role: u.role, region: u.region ?? null, institution_id: u.institution ?? null });

const stubUrls = () => {
  const created = [], revoked = [];
  URL.createObjectURL ??= () => "";
  URL.revokeObjectURL ??= () => {};
  vi.spyOn(URL, "createObjectURL").mockImplementation((b) => { created.push(b); return `blob:test/${created.length}`; });
  vi.spyOn(URL, "revokeObjectURL").mockImplementation((u) => revoked.push(u));
  return { created, revoked };
};
const version = (extra = {}) => ({ version_id: "v1", version_no: 1, original_filename: "lease.png", media_type: "image/png",
  size_bytes: 1024, status: "AVAILABLE", ...extra });

describe("document reading surface", () => {
  it("shows a clean scanned image inline from a blob URL and revokes it when closed", async () => {
    const { revoked } = stubUrls();
    const calls = fakeServer({ "GET /api/document-versions/v1/content": () => [200, new Blob(["png"], { type: "image/png" })] });
    const view = render(<DocumentPreview who={SUNRISE} version={version()} />);
    const img = await screen.findByRole("img", { name: "Page image of lease.png" });
    expect(img).toHaveAttribute("src", "blob:test/1");
    expect(calls[0].headers["X-Demo-User"]).toBe(SUNRISE.user);
    view.unmount();
    expect(revoked).toEqual(["blob:test/1"]);
  });

  it("never fetches a PDF or an unscanned version, and says why", () => {
    stubUrls();
    const calls = fakeServer({});
    const { rerender } = render(<DocumentPreview who={SUNRISE} version={version({ media_type: "application/pdf", original_filename: "deed.pdf" })} />);
    expect(screen.getByText(/does not allow embedded document viewers/)).toBeInTheDocument();
    rerender(<DocumentPreview who={SUNRISE} version={version({ status: "QUARANTINED" })} />);
    expect(screen.getByText(/never served or shown/)).toBeInTheDocument();
    expect(calls).toHaveLength(0);
  });
});

describe("institution overview", () => {
  const app = (id, status, stage) => ({ id, institution_id: "i", category: "NEW_PROGRAMME", academic_year: "2027-28", status,
    current_stage: stage, route: stage ? [{ stage: "SCRUTINY", when: "always" }, { stage: "EVC", when: "always" }] : null,
    created_at: "2026-10-20T10:00:00Z", submitted_at: stage ? "2026-10-20T10:00:00Z" : null });

  it("derives each next step from recorded facts only", async () => {
    fakeServer({
      "GET /api/applications": [app("d1111111-x", "DRAFT", null), app("p2222222-x", "IN_PROCESS", "SCRUTINY"), app("p3333333-x", "IN_PROCESS", "EVC")],
      "GET /api/deadlines": [],
      "GET /api/compliance/obligations": [{ id: "o1", application_id: "p2222222-x", kind: "AFFIDAVIT", status: "OPEN", due_date: "2027-01-10" }],
    });
    render(<OverviewView who={SUNRISE} onNavigate={() => {}} />);
    expect(await screen.findByText("Next: open the draft and submit it to fix the route")).toBeInTheDocument();
    expect(screen.getByText("Next: submit evidence for 1 open obligation")).toBeInTheDocument();
    expect(screen.getByText("With expert visit; nothing is recorded as awaiting you")).toBeInTheDocument();
    expect(await screen.findByText("No deadlines are running on your applications.")).toBeInTheDocument();
  });

  it("offers a way in when there are no applications, without inventing figures", async () => {
    const onNavigate = vi.fn();
    fakeServer({ "GET /api/applications": [], "GET /api/compliance/obligations": [] });
    const u = userEvent.setup();
    render(<OverviewView who={SUNRISE} onNavigate={onNavigate} />);
    await u.click(await screen.findByRole("button", { name: /Start an application/ }));
    expect(onNavigate).toHaveBeenCalledWith("applications");
    expect(screen.queryByText(/^\d+$/)).toBeNull();
  });
});

describe("dashboard pendency", () => {
  const dashboard = { scope: { region: "Southern", as_of: "2026-10-24T10:00:00Z" }, sections: [] };
  it("draws one row for one region and only the stages the report returned", async () => {
    fakeServer({ "GET /api/analytics/dashboard": dashboard, "GET /api/dashboards/pendency": {
      type: "pendency", scope: { region: "Southern" }, rows: [{ region: "Southern", stage: "SCRUTINY", count: 3 }], total: 3,
      coverage: { note: "Stage as recorded." }, ledger_head: { seq: 9 }, snapshot_hash: "abc" } });
    render(<DashboardView who={user("ro-southern")} />);
    const table = await screen.findByRole("table", { name: /by region and current stage/ });
    expect(within(table).getAllByRole("row")).toHaveLength(2);
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Region", "Scrutiny", "Total"]);
    expect(screen.getByText("Southern region only")).toBeInTheDocument();
  });

  it("keeps the rest of the dashboard when the pendency report is refused", async () => {
    fakeServer({ "GET /api/analytics/dashboard": dashboard, "GET /api/dashboards/pendency": () => [403, { detail: "no" }] });
    render(<DashboardView who={user("ro-southern")} />);
    expect(await screen.findByText("Not available to your role.")).toBeInTheDocument();
    expect(screen.getByText("Southern region only")).toBeInTheDocument();
  });
});

describe("audit console", () => {
  it("inspects a layer without writing anything", async () => {
    const calls = fakeServer({
      "GET /api/audit/verify": { ok: true, status: "NO_TRUSTED_CHECKPOINT", assurance: "CHAIN_ONLY" },
      "GET /api/ledger/verify": { ok: true, checked: 5, first_bad_seq: null, detail: null },
      "GET /api/audit/checkpoints": [],
    });
    const u = userEvent.setup();
    render(<AuditView who={AUDITOR} me={ME(AUDITOR)} />);
    const inspector = await screen.findByRole("complementary", { name: "Assurance detail" });
    expect(within(inspector).getByRole("heading", { name: "Hash continuity" })).toBeInTheDocument();
    const replay = screen.getByRole("region", { name: "3. Replay consistency" });
    await u.click(within(replay).getByRole("button", { name: "Inspect" }));
    expect(within(inspector).getByRole("heading", { name: "Replay consistency" })).toBeInTheDocument();
    expect(within(inspector).getByText("Not run")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });
});

describe("lifecycle and compliance axis", () => {
  it("marks only the screen's own step", () => {
    render(<Lifecycle here="delivery" />);
    const steps = screen.getAllByRole("listitem");
    expect(steps).toHaveLength(5);
    expect(steps.filter((s) => s.getAttribute("aria-current") === "step").map((s) => s.textContent)).toEqual([expect.stringMatching(/^Message sent per channel/)]);
  });

  it("groups obligations due the same day under one marker and opens the one chosen", async () => {
    const ob = (id, kind) => ({ id, application_id: "aaaaaaaa-1", kind, status: "OPEN", due_date: "2027-03-15", evidence: [], state_origin: "RULE_DEFAULT" });
    fakeServer({ "GET /api/compliance/letters": [], "GET /api/compliance/obligations": [ob("o1", "AFFIDAVIT"), ob("o2", "DEPOSIT")],
      "GET /api/compliance/obligations/o2": ob("o2", "DEPOSIT"), "GET /api/applications/aaaaaaaa-1/documents": [] });
    const u = userEvent.setup();
    const { container } = render(<ComplianceView who={user("bureau-officer")} me={ME(user("bureau-officer"))} />);
    await screen.findByRole("heading", { name: "Due dates" });
    expect(container.querySelectorAll(".axis-group")).toHaveLength(1);
    await u.click(screen.getByRole("button", { name: /^Deposit, case aaaaaaaa, due/ }));
    await waitFor(() => expect(screen.getByRole("complementary", { name: "Obligation detail" })).toHaveTextContent("Deposit"));
  });
});
