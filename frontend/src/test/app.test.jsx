import { cleanup as cleanupRender, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import App, { Workspace } from "../App.jsx";
import { DEMO_USERS, api } from "../api.js";
import { navFor } from "../nav.js";
import DashboardView from "../views/DashboardView.jsx";
import ApplicationsView from "../views/ApplicationsView.jsx";
import OverviewView from "../views/OverviewView.jsx";
import ApplicationList from "../components/ApplicationList.jsx";
import LedgerChamber from "../components/LedgerChamber.jsx";
import RouteJourney from "../components/RouteJourney.jsx";
import { ErrorBox } from "../components/ui.jsx";
import OcrReviewView from "../views/OcrReviewView.jsx";
import { fixtureAdapter } from "../integrations/documentReview.js";
import ScorecardView from "../views/ScorecardView.jsx";
import InboxView from "../views/InboxView.jsx";
import DeliveryView from "../views/DeliveryView.jsx";
import AuditView, { evidenceSummary } from "../views/AuditView.jsx";
import { when, dateIST } from "../components/ui.jsx";
import { errorText, outcomeText } from "../deliveryText.js";
import NewApplication from "../components/NewApplication.jsx";
import { fakeServer } from "./fakeServer.js";
import { adoptTokens, clearSession, hasSession } from "../auth/oidc.js";

const SUNRISE = DEMO_USERS[0];
const RO = DEMO_USERS.find((u) => u.role === "RO_OFFICER");
const ME = (u) => ({ user_id: u.user, role: u.role, region: u.region ?? null, institution_id: u.institution ?? null });

describe("navigation follows the role", () => {
  it("gives institutions their own work only", () => {
    const keys = navFor("INSTITUTION").map((i) => i.key);
    expect(keys).toEqual(["overview", "applications", "inbox", "compliance"]);
    expect(navFor("INSTITUTION")[1].label).toBe("My applications");
  });

  it("gives oversight roles audit, delivery and scorecard", () => {
    for (const role of ["AUDITOR", "BUREAU_OFFICER", "BUREAU_HEAD"]) {
      expect(navFor(role).map((i) => i.key)).toEqual(expect.arrayContaining(["audit", "delivery", "scorecard"]));
    }
    expect(navFor("SCRUTINY_COMMITTEE").map((i) => i.key)).not.toContain("audit");
  });

  it("marks the current page for assistive technology", async () => {
    fakeServer({ "GET /api/applications": [], "GET /api/rulesets/aph-2024-27@r1": { routes: [] } });
    render(<Workspace who={SUNRISE} me={ME(SUNRISE)} config={{ mode: "demo", demo_mode: false }} />);
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).getByRole("button", { name: "Overview" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("button", { name: "My applications" })).not.toHaveAttribute("aria-current");
    expect(within(nav).queryByRole("button", { name: /Audit/ })).toBeNull();
  });
});

describe("api client", () => {
  it("sends demo identity headers only in demo mode", async () => {
    const calls = fakeServer({ "GET /api/auth/me": {} });
    await api(RO, "/auth/me");
    expect(calls[0].headers).toMatchObject({ "X-Demo-Role": "RO_OFFICER", "X-Demo-Region": "Southern" });
  });

  it("sends a bearer token and no demo headers when signed in", async () => {
    adoptTokens({ access_token: "tok", expires_in: 600 });
    const calls = fakeServer({ "GET /api/auth/me": {} });
    await api({ mode: "oidc", config: { issuer: "http://idp", client_id: "awoc-ui" } }, "/auth/me");
    expect(calls[0].headers.Authorization).toBe("Bearer tok");
    expect(Object.keys(calls[0].headers).some((h) => h.startsWith("X-Demo"))).toBe(false);
  });

  it("asks for sign-in without calling the server when there is no session", async () => {
    const calls = fakeServer({});
    await expect(api({ mode: "oidc", config: {} }, "/applications")).rejects.toMatchObject({ status: 401 });
    expect(calls).toHaveLength(0);
  });

  it("turns 401, 403 and 503 into clear messages", async () => {
    fakeServer({
      "GET /api/a": () => [401, { detail: "invalid or expired token" }],
      "GET /api/b": () => [403, { detail: "institution may only access its own records" }],
      "GET /api/c": () => [503, { detail: "authorisation service unavailable" }],
    });
    await expect(api(SUNRISE, "/a")).rejects.toThrow(/sign in again/);
    await expect(api(SUNRISE, "/b")).rejects.toThrow("Not permitted: institution may only access its own records");
    await expect(api(SUNRISE, "/c")).rejects.toThrow(/security service is unavailable/);
  });
});

describe("app start-up", () => {
  it("offers sign-in, and no demo switcher, in real sign-in mode", async () => {
    fakeServer({ "GET /api/auth/config": { mode: "oidc", demo_mode: false, issuer: "http://idp", client_id: "awoc-ui" } });
    render(<App />);
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Acting as")).toBeNull();
  });

  it("shows the demo switcher, demo badges and time travel in demo mode", async () => {
    fakeServer({
      "GET /api/auth/config": { mode: "demo", demo_mode: true, issuer: null, client_id: null },
      "GET /api/auth/me": ME(SUNRISE),
      "GET /api/applications": [],
      "GET /api/rulesets/aph-2024-27@r1": { routes: [] },
      "GET /api/sim/clock": { now: "2026-10-24T10:00:00Z", offset_days: 0 },
    });
    render(<App />);
    expect(await screen.findByLabelText("Acting as")).toBeInTheDocument();
    expect(screen.getByText("DEMO SIGN-IN")).toBeInTheDocument();
    expect(screen.getByText("SIMULATED TIME")).toBeInTheDocument();
  });

  it("hides time travel when the server is not in demo mode", async () => {
    fakeServer({ "GET /api/applications": [], "GET /api/rulesets/aph-2024-27@r1": { routes: [] } });
    render(<Workspace who={SUNRISE} me={ME(SUNRISE)} config={{ mode: "oidc", demo_mode: false }} />);
    await screen.findByText("Overview", { selector: "h1" });
    expect(screen.queryByText("SIMULATED TIME")).toBeNull();
  });
});

describe("dashboard", () => {
  const body = {
    scope: { region: null, as_of: "2026-10-24T10:00:00Z" },
    sections: [
      { key: "applications", title: "Applications", status: "AVAILABLE", source: "events",
        data: { total: 3, by_status: { IN_PROCESS: 2, DRAFT: 1 }, by_stage: { SCRUTINY: 2 }, by_region: { Southern: 2, Northern: 1 } } },
      { key: "workload", title: "Officer workload", status: "NOT_AVAILABLE", depends_on: "Person 1: case assignment data" },
    ],
  };

  it("shows real totals and labels missing data instead of inventing it", async () => {
    fakeServer({ "GET /api/analytics/dashboard": body });
    render(<DashboardView who={DEMO_USERS[5]} />);
    const apps = (await screen.findByRole("heading", { name: "Applications" })).closest("section");
    expect(within(apps).getByText("3")).toBeInTheDocument();
    expect(within(apps).getByRole("table", { name: "Applications by region" })).toHaveTextContent("Southern");
    const workload = screen.getByRole("heading", { name: "Officer workload" }).closest("section");
    expect(workload).toHaveTextContent("Not available yet");
    expect(workload).toHaveTextContent("Waiting for: Person 1: case assignment data");
    expect(within(workload).queryByText(/^\d+$/)).toBeNull();
  });

  it("shows a refusal as an error, not as empty data", async () => {
    fakeServer({ "GET /api/analytics/dashboard": () => [403, { detail: "INSTITUTION may not analytics.dashboard" }] });
    render(<DashboardView who={SUNRISE} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Not permitted");
  });
});

describe("regional officers", () => {
  it("explain why the case list is not available instead of showing an empty list", async () => {
    fakeServer({ "GET /api/applications": () => [403, { detail: "regional officers may only access their own region" }] });
    render(<ApplicationsView who={RO} me={ME(RO)} />);
    expect(await screen.findByText(/refused by the server until it can be filtered to your region/)).toBeInTheDocument();
  });
});

describe("document review: commit before reveal", () => {
  it("shows only the page image until the officer commits, then reveals the machine reading", async () => {
    const user = userEvent.setup();
    const { container } = render(<OcrReviewView />);
    expect(await screen.findByRole("img", { name: /Synthetic facsimile/ })).toBeInTheDocument();
    expect(screen.getByText(/Synthetic facsimile - demo only/)).toBeInTheDocument();
    // nothing machine-generated anywhere on the screen yet: no values, OCR text, confidence or location boxes
    const before = container.textContent;
    for (const leak of ["2031-03-31", "31-03-2031", "2001-04-01", "01-04-2001", "confidence"]) expect(before).not.toContain(leak);
    expect(container.querySelector(".ocr-box")).toBeNull();
    expect(screen.getByRole("button", { name: "Confirm facts" })).toBeDisabled();

    const end = screen.getByRole("group", { name: "Lease end date" });
    const commit = within(end).getByRole("button", { name: "Commit my reading" });
    expect(commit).toBeDisabled();
    await user.type(within(end).getByLabelText(/Your reading/), "2031-03-30");
    await user.click(commit);

    expect(await within(end).findByText("2031-03-31")).toBeInTheDocument();
    expect(within(end).getByText("Differs - check the document")).toBeInTheDocument();
    expect(within(end).getByLabelText(/Your reading/)).toBeDisabled();
    expect(screen.getByTestId("box-lease_end")).toBeInTheDocument();
    // the other field is still hidden
    const start = screen.getByRole("group", { name: "Lease start date" });
    expect(start.textContent).not.toContain("2001-04-01");
    expect(screen.queryByTestId("box-lease_start")).toBeNull();
    expect(screen.getByRole("button", { name: "Confirm facts" })).toBeDisabled(); // no backend to save to
  });

  it("the adapter itself withholds suggestions until a reading is committed", async () => {
    const review = await fixtureAdapter.loadReview("SAMPLE-LEASE-001");
    // the page image is the document itself and may show the dates; nothing else may carry machine output
    const { pages, ...rest } = review;
    expect(JSON.stringify(rest)).not.toMatch(/2031|2001|confidence|suggestion|box|sourceText/);
    expect(Object.keys(pages[0])).toEqual(["imageUrl", "width", "height"]);
    await expect(fixtureAdapter.commitReading(review.documentId, "lease_end", "")).rejects.toThrow();
    expect(fixtureAdapter.confirmFacts).toBeNull();
  });
});

describe("document review: confirmation", () => {
  function mockAdapter(confirmFacts) {
    return { ...fixtureAdapter, live: true, confirmFacts };
  }

  async function commitBoth(user, endValue = "2031-03-31") {
    const start = await screen.findByRole("group", { name: "Lease start date" });
    await user.type(within(start).getByLabelText(/Your reading/), "2001-04-01");
    await user.click(within(start).getByRole("button", { name: "Commit my reading" }));
    const end = screen.getByRole("group", { name: "Lease end date" });
    await user.type(within(end).getByLabelText(/Your reading/), endValue);
    await user.click(within(end).getByRole("button", { name: "Commit my reading" }));
    await within(end).findByText(/Machine reading/);
    return end;
  }

  it("stays unavailable until every field is committed, then sends one request with the officer's values", async () => {
    const user = userEvent.setup();
    const calls = [];
    const adapter = mockAdapter(async (id, decisions) => {
      calls.push(decisions);
      return { confirmed: decisions.map((d) => ({ fieldKey: d.fieldKey, factId: `f-${d.fieldKey}` })) };
    });
    render(<OcrReviewView adapter={adapter} />);
    const confirm = await screen.findByRole("button", { name: "Confirm facts" });
    expect(confirm).toBeDisabled();
    expect(screen.queryByText(/Preview with sample data/)).toBeNull();
    await commitBoth(user);
    expect(confirm).toBeEnabled();
    await user.click(confirm);
    expect(await screen.findByText("Facts confirmed by the server.")).toBeInTheDocument();
    expect(calls).toEqual([[
      { fieldKey: "lease_start", value: "2001-04-01", source: "OFFICER" },
      { fieldKey: "lease_end", value: "2031-03-31", source: "OFFICER" },
    ]]);
  });

  it("lets the officer adopt the machine reading only after seeing it, and says so", async () => {
    const user = userEvent.setup();
    const calls = [];
    const adapter = mockAdapter(async (id, d) => { calls.push(d); return { confirmed: d.map((x) => ({ fieldKey: x.fieldKey, factId: "f" })) }; });
    render(<OcrReviewView adapter={adapter} />);
    const end = await commitBoth(user, "2031-03-30");
    await user.click(within(end).getByRole("radio", { name: /Use the machine reading/ }));
    await user.click(screen.getByRole("button", { name: "Confirm facts" }));
    await screen.findByText("Facts confirmed by the server.");
    expect(calls[0][1]).toEqual({ fieldKey: "lease_end", value: "2031-03-31", source: "MACHINE" });
  });

  it("shows a failure and allows a retry", async () => {
    const user = userEvent.setup();
    let fail = true;
    const adapter = mockAdapter(async (id, d) => {
      if (fail) { fail = false; throw new Error("Confirmation service unavailable"); }
      return { confirmed: d.map((x) => ({ fieldKey: x.fieldKey, factId: "f" })) };
    });
    render(<OcrReviewView adapter={adapter} />);
    await commitBoth(user);
    await user.click(screen.getByRole("button", { name: "Confirm facts" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Confirmation service unavailable");
    expect(screen.queryByText("Facts confirmed by the server.")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Confirm facts" }));
    expect(await screen.findByText("Facts confirmed by the server.")).toBeInTheDocument();
  });

  it("does not report success unless the server confirmed every field", async () => {
    const user = userEvent.setup();
    const adapter = mockAdapter(async () => ({ confirmed: [{ fieldKey: "lease_start", factId: "f1" }] }));
    render(<OcrReviewView adapter={adapter} />);
    await commitBoth(user);
    await user.click(screen.getByRole("button", { name: "Confirm facts" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("did not confirm every field");
    expect(screen.queryByText("Facts confirmed by the server.")).toBeNull();
  });

  it("sends only one request on a double click", async () => {
    const user = userEvent.setup();
    let release;
    const calls = [];
    const adapter = mockAdapter((id, d) => { calls.push(d); return new Promise((r) => { release = () => r({ confirmed: d.map((x) => ({ fieldKey: x.fieldKey, factId: "f" })) }); }); });
    render(<OcrReviewView adapter={adapter} />);
    await commitBoth(user);
    await user.dblClick(screen.getByRole("button", { name: "Confirm facts" }));
    expect(calls).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Confirming…" })).toBeDisabled();
    release();
    expect(await screen.findByText("Facts confirmed by the server.")).toBeInTheDocument();
  });
});

describe("resilience", () => {
  it("offers a retry for server errors but not for refusals", async () => {
    let calls = 0;
    fakeServer({ "GET /api/analytics/scorecard": () => (++calls === 1 ? [500, { detail: "boom" }] : [200, { generated_at: "2026-10-24T10:00:00Z", items: [] }]) });
    const user = userEvent.setup();
    render(<ScorecardView who={DEMO_USERS[5]} />);
    await user.click(await screen.findByRole("button", { name: "Try again" }));
    expect(await screen.findByText(/Each line says how it was measured/)).toBeInTheDocument();
    cleanupRender();
    fakeServer({ "GET /api/analytics/scorecard": () => [403, { detail: "no" }] });
    render(<ScorecardView who={SUNRISE} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Not permitted");
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  });

  it("a double click marks a notification read only once", async () => {
    let release;
    const slow = new Promise((r) => { release = () => r([200, {}]); });   // the first request is still in flight
    const calls = fakeServer({
      "GET /api/notifications/inbox": [{ id: "n1", alert_id: "a1b2c3d4e5", subject: "Deadline reminder", created_at: "2026-10-24T10:00:00Z", read_at: null }],
      "POST /api/notifications/inbox/n1/read": () => slow,
    });
    const user = userEvent.setup();
    render(<InboxView who={SUNRISE} />);
    const button = await screen.findByRole("button", { name: /^Mark .* as read$/ });
    await user.dblClick(button);
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(1);
    release();
  });

  it("shows a failed action instead of failing silently", async () => {
    fakeServer({
      "GET /api/notifications/inbox": [{ id: "n1", alert_id: "a1b2c3d4e5", subject: "Deadline reminder", created_at: "2026-10-24T10:00:00Z", read_at: null }],
      "POST /api/notifications/inbox/n1/read": () => [503, { detail: "down" }],
    });
    const user = userEvent.setup();
    render(<InboxView who={SUNRISE} />);
    await user.click(await screen.findByRole("button", { name: /^Mark .* as read$/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/unavailable/);
  });

  it("a double click creates only one draft", async () => {
    let release;
    const slow = new Promise((r) => { release = () => r([201, { id: "x" }]); });
    const calls = fakeServer({
      "GET /api/rulesets/aph-2024-27@r1": { routes: [{ category: "NEW_PROGRAMME", label: "New programme", stages: [] }] },
      "POST /api/applications": () => slow,
    });
    const user = userEvent.setup();
    render(<NewApplication who={SUNRISE} institution={SUNRISE.institution} onChanged={() => {}} />);
    await screen.findByRole("option", { name: "New programme" });
    await user.dblClick(screen.getByRole("button", { name: "Create draft" }));
    const posts = calls.filter((c) => c.method === "POST");
    expect(posts.length).toBe(1);
    expect(posts[0].headers["Idempotency-Key"]).toBeTruthy();
    release();
  });

  it("has a skip link to the main content", () => {
    fakeServer({ "GET /api/applications": [], "GET /api/rulesets/aph-2024-27@r1": { routes: [] } });
    render(<Workspace who={SUNRISE} me={ME(SUNRISE)} config={{ mode: "demo", demo_mode: false }} />);
    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveAttribute("href", "#content");
  });
});

describe("session hardening", () => {
  const OIDC = { mode: "oidc", config: { issuer: "http://idp", client_id: "awoc-ui" } };

  it("never writes the access token to browser storage", () => {
    adoptTokens({ access_token: "secret-access", refresh_token: "r1", id_token: "i1", expires_in: 300 });
    const stored = JSON.stringify({ ...sessionStorage, ...localStorage });
    expect(stored).not.toContain("secret-access");
    expect(JSON.parse(sessionStorage.getItem("awoc.oidc.tokens"))).toEqual({ refresh_token: "r1", id_token: "i1" });
    clearSession();
  });

  it("ends the session and tells the app when the server answers 401", async () => {
    adoptTokens({ access_token: "tok", refresh_token: "r1", expires_in: 300 });
    fakeServer({ "GET /api/applications": () => [401, { detail: "invalid or expired token" }] });
    let fired = false;
    window.addEventListener("awoc:session-expired", () => { fired = true; }, { once: true });
    await expect(api(OIDC, "/applications")).rejects.toMatchObject({ status: 401 });
    expect(fired).toBe(true);
    expect(hasSession()).toBe(false);
  });

  it("ends the session when the refresh token is rejected", async () => {
    adoptTokens({ access_token: "old", refresh_token: "r-revoked", expires_in: 1 }); // already inside the 30 s margin
    fakeServer({
      "GET http://idp/.well-known/openid-configuration": { issuer: "http://idp", token_endpoint: "http://idp/token" },
      "POST http://idp/token": () => [400, { error: "invalid_grant" }],
    });
    await expect(api(OIDC, "/applications")).rejects.toMatchObject({ status: 401 });
    expect(hasSession()).toBe(false);
  });

  it("demo-mode 401s do not touch any session", async () => {
    fakeServer({ "GET /api/x": () => [401, { detail: "headers required" }] });
    let fired = false;
    window.addEventListener("awoc:session-expired", () => { fired = true; }, { once: true });
    await expect(api(SUNRISE, "/x")).rejects.toMatchObject({ status: 401 });
    expect(fired).toBe(false);
  });
});

describe("audit screen honesty", () => {
  const full = { ok: true, status: "VERIFIED", assurance: "CHECKPOINTED", checkpoint_seq: 9, entries_after_checkpoint: 0 };
  const newer = { ok: true, status: "VERIFIED", assurance: "CHECKPOINTED_WITH_NEWER_ENTRIES", checkpoint_seq: 9, entries_after_checkpoint: 3 };
  const chainOnly = { ok: true, status: "NO_TRUSTED_CHECKPOINT", assurance: "CHAIN_ONLY" };
  const complete = { verdict: "VERIFIED_COMPLETE" };

  it("is green only when anchored through the latest entry and replay is complete", async () => {
    const { headline } = await import("../views/AuditView.jsx");
    expect(headline(true, full, complete)).toEqual(["ok", "Fully verified through the latest entry"]);
  });

  it("does not call history with unanchored newer entries fully verified, even with complete replay", async () => {
    const { headline, checkpointState } = await import("../views/AuditView.jsx");
    const [tone, text] = headline(true, newer, complete);
    expect(tone).toBe("warn");
    expect(text).toMatch(/up to entry #9; the 3 newest entries are not anchored/);
    expect(checkpointState(newer)[0]).toBe("warn");
  });

  it("never lets replay stand in for a checkpoint", async () => {
    const { headline, checkpointState } = await import("../views/AuditView.jsx");
    expect(headline(true, chainOnly, complete)).toEqual(["warn", "Chain intact, but not anchored by a trusted checkpoint"]);
    expect(checkpointState(chainOnly)[0]).toBe("warn");
  });

  it("flags incomplete or missing replay", async () => {
    const { headline, replayState } = await import("../views/AuditView.jsx");
    expect(headline(true, full, { verdict: "CONSISTENT_SUBSET" })[1]).toMatch(/replay covered only part/);
    expect(headline(true, full, null)[1]).toMatch(/replay not run/);
    expect(replayState({ verdict: "CONSISTENT_SUBSET" })[0]).toBe("warn");
  });

  it("reports integrity failures as failures", async () => {
    const { headline } = await import("../views/AuditView.jsx");
    expect(headline(false, full, complete)[0]).toBe("bad");
    expect(headline(true, { ok: false, status: "WITNESS_CORRUPT" }, null)[0]).toBe("bad");
    expect(headline(true, full, { verdict: "MISMATCH" })[0]).toBe("bad");
  });
});

describe("scorecard colours follow the result", () => {
  it("never shows a failed or partial check as green", async () => {
    const { outcomeTone } = await import("../views/ScorecardView.jsx");
    expect(outcomeTone({ key: "ledger_integrity", result: { ok: false, assurance: "NONE" } })).toBe("bad");
    expect(outcomeTone({ key: "ledger_integrity", result: { ok: true, assurance: "CHAIN_ONLY" } })).toBe("warn");
    expect(outcomeTone({ key: "ledger_integrity", result: { ok: true, assurance: "CHECKPOINTED" } })).toBe("ok");
    expect(outcomeTone({ key: "replay_consistency", result: { verdict: "MISMATCH" } })).toBe("bad");
    expect(outcomeTone({ key: "replay_consistency", result: { verdict: "CONSISTENT_SUBSET" } })).toBe("warn");
    expect(outcomeTone({ key: "routing", result: { mismatches: [{}] } })).toBe("warn");
  });
});

describe("times are shown in IST", () => {
  it("formats in Asia/Kolkata whatever the browser zone", () => {
    expect(when("2026-10-24T20:00:00Z")).toBe("25 Oct 2026, 01:30 IST");
    expect(dateIST("2026-10-24T20:00:00Z")).toBe("25 Oct 2026");
    expect(when(null)).toBe("—");
  });
});

describe("delivery operations", () => {
  const BUREAU_HEAD = DEMO_USERS.find((u) => u.role === "BUREAU_HEAD");
  const AUDITOR = DEMO_USERS.find((u) => u.role === "AUDITOR");
  const health = {
    by_status: { PENDING: 2, SENDING: 1, DELIVERED: 5, DEAD: 1 }, oldest_undelivered_age_seconds: 600,
    first_try_success_rate_24h: 0.5, first_tries_24h: 4, delivered_after_retry_24h: 1, attempts_24h: {},
    stalled_sending: 1, lease_lost_24h: 2, providers: { email: "not_configured", sms: "mock (nothing is sent)", in_app: "built_in" },
  };
  const dead = { id: "d1d1d1d1-0000", alert_id: "a1", channel: "email", template: "deadline.breached", status: "DEAD",
    attempts: 1, last_error: "NOT_CONFIGURED", next_attempt_at: null, created_at: "2026-10-24T10:00:00Z", delivered_at: null, dead_at: "2026-10-24T10:01:00Z" };

  it("shows each state separately and explains problems in plain language", async () => {
    fakeServer({ "GET /api/notifications/health": health, "GET /api/notifications/outbox": [dead] });
    render(<DeliveryView who={AUDITOR} me={ME(AUDITOR)} />);
    expect((await screen.findAllByText("Sending")).length).toBeGreaterThan(0);
    expect(within(screen.getByRole("list", { name: "Messages by state" })).getByText("Dead letters")).toBeInTheDocument();
    expect(screen.getByText(/Email is not configured in this deployment/)).toBeInTheDocument();
    expect(screen.getByText(/1 message\(s\) were being sent by a worker that stopped/)).toBeInTheDocument();
    expect(await screen.findByRole("cell", { name: "The mail server is not configured for this deployment" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Requeue/ })).toBeNull();          // auditors cannot requeue
    expect(screen.getByText("Only the bureau head can requeue dead letters.")).toBeInTheDocument();
  });

  it("asks before requeueing, sends one request, and explains the result", async () => {
    let release;
    const calls = fakeServer({
      "GET /api/notifications/health": health,
      "GET /api/notifications/outbox": [dead],
      "POST /api/notifications/outbox/d1d1d1d1-0000/retry": () => new Promise((r) => { release = () => r([200, { requeued: "d1" }]); }),
    });
    const user = userEvent.setup();
    render(<DeliveryView who={BUREAU_HEAD} me={ME(BUREAU_HEAD)} />);
    await user.click(await screen.findByRole("button", { name: /Requeue deadline.breached by email/ }));
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);        // nothing sent yet
    await user.dblClick(screen.getByRole("button", { name: "Yes, requeue" }));
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(1);
    release();
    expect(await screen.findByText(/recipients already reached will not get it twice/)).toBeInTheDocument();
  });

  it("can cancel a requeue", async () => {
    const calls = fakeServer({ "GET /api/notifications/health": health, "GET /api/notifications/outbox": [dead] });
    const user = userEvent.setup();
    render(<DeliveryView who={BUREAU_HEAD} me={ME(BUREAU_HEAD)} />);
    await user.click(await screen.findByRole("button", { name: /Requeue/ }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("button", { name: /Requeue/ })).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
  });

  it("translates codes, keeping unknown ones visible", () => {
    expect(errorText("SMTP_550")).toMatch(/rejected the message \(550\)/);
    expect(errorText("SOME_RECIPIENTS_REFUSED")).toMatch(/some recipients/);
    expect(errorText("SOMETHING_NEW")).toBe("SOMETHING_NEW");
    expect(outcomeText("TRANSIENT_LEASE_LOST")).toMatch(/another worker/);
  });
});

describe("audit evidence presentation", () => {
  const AUDITOR = DEMO_USERS.find((u) => u.role === "AUDITOR");
  const BUREAU_OFFICER = DEMO_USERS.find((u) => u.role === "BUREAU_OFFICER");
  const verify = { ok: true, status: "VERIFIED", assurance: "CHECKPOINTED_WITH_NEWER_ENTRIES", checked: 12, checkpoint_seq: 9,
    checkpoint_at: "2026-10-24T10:00:00Z", checkpoint_key_id: "demo-2026-10", entries_after_checkpoint: 3, unpublished_checkpoints: 1,
    witness_kind: "local-file (DEMO ONLY)", detail: "Chain verifies and matches the latest trusted checkpoint.", witness_configured: true };
  const routes = (over = {}) => ({
    "GET /api/audit/verify": verify,
    "GET /api/ledger/verify": { ok: true, checked: 12, first_bad_seq: null, detail: null },
    "GET /api/audit/checkpoints": [{ id: "c1", created_at: "2026-10-24T10:05:00Z", head_seq: 12, entry_count: 12, key_id: "demo-2026-10", status: "PENDING", publish_error: "simulated witness outage" }],
    "POST /api/audit/replay": { ok: false, verdict: "MISMATCH", unhandled_event_types: {}, schemas_without_projector: [],
      projections: [{ name: "applications", owner: "P1", status: "MISMATCH", events_applied: 4, records: 2, compared_fields: ["status"],
        differences: [{ key: "a1b2c3d4-0000", field: "status", replayed: "IN_PROCESS", live: "APPROVED" }], skipped_versions: {} }],
      gaps: [{ kind: "UNREADABLE_EVENT", seq: 7, event_type: "wf.application_created", projection: "applications", error: "KeyError" }] },
    ...over,
  });

  it("marks the local witness as demo only and explains pending publication", async () => {
    fakeServer(routes());
    render(<AuditView who={AUDITOR} me={ME(AUDITOR)} />);
    expect(await screen.findByText(/DEMO ONLY - same machine, not independent/)).toBeInTheDocument();
    expect(screen.getByText(/signed but the witness has not accepted them yet/)).toBeInTheDocument();
    expect(screen.getByText(/the 3 newest entries are not anchored yet/)).toBeInTheDocument();
  });

  it("shows replay mismatches and unreadable entries in words", async () => {
    fakeServer(routes());
    const user = userEvent.setup();
    render(<AuditView who={AUDITOR} me={ME(AUDITOR)} />);
    await user.click(await screen.findByRole("button", { name: "Run replay" }));
    expect(await screen.findByText(/Entry #7 \(wf.application_created\) could not be read/)).toBeInTheDocument();
    await user.click(screen.getByText("Show"));
    expect(screen.getByText(/status is "APPROVED" live but "IN_PROCESS" from events/)).toBeInTheDocument();
    expect(screen.getAllByText("Integrity problem found").length).toBeGreaterThan(0);
  });

  it("builds a summary with statuses only, never payloads", () => {
    const text = evidenceSummary({ chain: { ok: true, checked: 12 }, verify, replay: routes()["POST /api/audit/replay"],
      checkpoints: routes()["GET /api/audit/checkpoints"], generatedAt: "now" });
    expect(text).toMatch(/Overall: Integrity problem found/);
    expect(text).toMatch(/3 newer entries are not anchored yet/);
    expect(text).toMatch(/witness: local-file \(DEMO ONLY\)/);
    expect(text).toMatch(/not independent long-term assurance/);
    expect(text).not.toMatch(/APPROVED|IN_PROCESS|payload/);
  });

  it("copies the summary to the clipboard", async () => {
    fakeServer(routes());
    const user = userEvent.setup();   // provides a clipboard stub on navigator
    render(<AuditView who={AUDITOR} me={ME(AUDITOR)} />);
    await screen.findByText(/DEMO ONLY - same machine/);
    await user.click(screen.getByRole("button", { name: "Copy summary" }));
    const copiedText = await navigator.clipboard.readText();
    expect(copiedText).toMatch(/Hash chain: intact, 12 entries/);
    expect(copiedText).not.toMatch(/APPROVED|IN_PROCESS/);
    expect(await screen.findByText("Summary copied.")).toBeInTheDocument();
  });

  it("does not offer replay or signing to a bureau officer, and shows a refused check as an error", async () => {
    fakeServer(routes({ "GET /api/audit/verify": () => [403, { detail: "BUREAU_OFFICER may not audit.checkpoint.read" }] }));
    render(<AuditView who={BUREAU_OFFICER} me={ME(BUREAU_OFFICER)} />);
    expect((await screen.findAllByRole("alert"))[0]).toHaveTextContent("Not permitted");
    expect(screen.queryByRole("button", { name: "Run replay" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Sign checkpoint/ })).toBeNull();
    expect(screen.getByText(/An auditor or the bureau head can retry publication/)).toBeInTheDocument();
  });

  it("reports a failed signing attempt", async () => {
    fakeServer(routes({ "GET /api/audit/checkpoints": [], "POST /api/audit/checkpoints": () => [503, { detail: "no witness" }] }));
    const user = userEvent.setup();
    render(<AuditView who={AUDITOR} me={ME(AUDITOR)} />);
    await user.click(await screen.findByRole("button", { name: "Sign checkpoint now" }));
    expect(await screen.findByText(/security service is unavailable/)).toBeInTheDocument();
  });
});

describe("navigation matrix (mirrors backend/app/platform/policy.py)", () => {
  // Hiding a screen is not security - the server decides - but showing one the server always refuses is a defect.
  const EXPECTED = {
    INSTITUTION: ["overview", "applications", "inbox", "compliance"],
    SCRUTINY_COMMITTEE: ["dashboard", "applications", "inbox", "ocr"],
    RO_OFFICER: ["dashboard", "applications", "inbox", "ocr", "compliance"],
    BUREAU_OFFICER: ["dashboard", "applications", "inbox", "ocr", "evc", "compliance", "audit", "delivery", "scorecard"],
    BUREAU_HEAD: ["dashboard", "applications", "inbox", "evc", "compliance", "audit", "delivery", "scorecard"],
    AUDITOR: ["dashboard", "applications", "inbox", "audit", "delivery", "scorecard"],
  };
  for (const [role, keys] of Object.entries(EXPECTED)) {
    it(`${role} sees exactly its screens`, () => {
      expect(navFor(role).map((i) => i.key)).toEqual(keys);
    });
  }
  it("an unknown role sees nothing", () => {
    expect(navFor("SYSTEM")).toEqual([]);
    expect(navFor(undefined)).toEqual([]);
  });
});

describe("redesign interactions", () => {
  it("the pause switch stops animation loops and is remembered", async () => {
    const { motionPaused, setMotionPaused, prefersReducedMotion } = await import("../motion.js");
    window.matchMedia = (q) => ({ matches: false, media: q, addEventListener() {}, removeEventListener() {} });
    expect(motionPaused()).toBe(false);
    expect(prefersReducedMotion()).toBe(false);
    setMotionPaused(true);
    expect(localStorage.getItem("awoc.motion")).toBe("off");
    expect(prefersReducedMotion()).toBe(true);
    setMotionPaused(false);
    expect(prefersReducedMotion()).toBe(false);
    delete window.matchMedia;
  });

  it("the institution overview counts cases per stage and opens a case from its deadline", async () => {
    const app = (id, stage) => ({ id, institution_id: "i", category: "NEW_PROGRAMME", academic_year: "2027-28", status: "IN_PROCESS",
      current_stage: stage, ruleset_rev: "r", route: [{ stage: "SCRUTINY", when: "always" }, { stage: "EVC", when: "always" }], created_at: "2026-10-20T10:00:00Z", submitted_at: "2026-10-20T10:00:00Z" });
    fakeServer({
      "GET /api/applications": [app("a1111111-x", "SCRUTINY"), app("a2222222-x", "SCRUTINY"), app("a3333333-x", "EVC")],
      "GET /api/deadlines": [{ id: "d1", rule_id: "AICTE_PROCESSING", status: "RUNNING", due_date: "2026-11-23" }],
    });
    const onNavigate = vi.fn();
    const user = userEvent.setup();
    render(<OverviewView who={SUNRISE} onNavigate={onNavigate} />);
    const path = await screen.findByRole("img", { name: "Scrutiny: 2, Expert visit: 1" });
    expect(path).toBeInTheDocument();
    expect(screen.getAllByText("AICTE processing").length).toBeGreaterThan(0);   // acronym kept, not "Aicte"
    await user.click(screen.getAllByRole("button", { name: "Open case" })[0]);
    expect(onNavigate).toHaveBeenCalledWith("applications", { caseId: "a1111111-x" });
  });

  it("case list filters by status with counts from the rows", async () => {
    const mk = (id, status) => ({ id, category: "NEW_PROGRAMME", academic_year: "2027-28", status, current_stage: status === "DRAFT" ? null : "SCRUTINY", created_at: `2026-10-2${id}T10:00:00Z` });
    const user = userEvent.setup();
    render(<ApplicationList apps={[mk("1", "DRAFT"), mk("2", "IN_PROCESS"), mk("3", "IN_PROCESS")]} selected={null} onSelect={() => {}} />);
    expect(screen.getByRole("button", { name: "Drafts 1" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "In process 2" }));
    expect(screen.getAllByRole("button", { pressed: false }).filter((b) => b.classList.contains("row"))).toHaveLength(2);
  });

  it("the ledger falls back to a block strip without WebGL and says what it shows", () => {
    render(<LedgerChamber chain={{ ok: false, checked: 12, first_bad_seq: 9 }} verify={{ ok: false, assurance: "NONE" }} />);
    const strip = screen.getByRole("img", { name: /12 ledger entries: 0 anchored by the trusted checkpoint, first broken link at entry 9/ });
    expect(strip.querySelectorAll(".blk.broken")).toHaveLength(1);
    expect(strip.querySelectorAll(".blk.after")).toHaveLength(3);
    expect(screen.getByText("First broken link")).toBeInTheDocument();
  });

  it("the journey marks done, current and ahead stages for assistive technology", () => {
    render(<RouteJourney route={[{ stage: "SCRUTINY", when: "always" }, { stage: "EVC", when: "always" }, { stage: "SHC", when: "as_applicable" }]}
      current="EVC" status="IN_PROCESS" />);
    const items = within(screen.getByRole("list")).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Done");
    expect(items[1]).toHaveAttribute("aria-current", "step");
    expect(items[2]).toHaveTextContent("Ahead · if applicable");
  });

  it("a refusal reads as a rule, without a retry", () => {
    const err = Object.assign(new Error("Not permitted: regional officers may only access their own region"), { status: 403 });
    render(<ErrorBox error={err} onRetry={() => {}} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Not available to your role.");
    expect(screen.queryByRole("button", { name: /Try again/ })).toBeNull();
  });
});
