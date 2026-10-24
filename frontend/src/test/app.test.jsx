import { cleanup as cleanupRender, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import App, { Workspace } from "../App.jsx";
import { DEMO_USERS, api } from "../api.js";
import { navFor } from "../nav.js";
import DashboardView from "../views/DashboardView.jsx";
import ApplicationsView from "../views/ApplicationsView.jsx";
import OcrReviewView from "../views/OcrReviewView.jsx";
import { fixtureAdapter } from "../integrations/documentReview.js";
import ScorecardView from "../views/ScorecardView.jsx";
import InboxView from "../views/InboxView.jsx";
import NewApplication from "../components/NewApplication.jsx";
import { fakeServer } from "./fakeServer.js";
import { adoptTokens, clearSession, hasSession } from "../auth/oidc.js";

const SUNRISE = DEMO_USERS[0];
const RO = DEMO_USERS.find((u) => u.role === "RO_OFFICER");
const ME = (u) => ({ user_id: u.user, role: u.role, region: u.region ?? null, institution_id: u.institution ?? null });

describe("navigation follows the role", () => {
  it("gives institutions their own work only", () => {
    const keys = navFor("INSTITUTION").map((i) => i.key);
    expect(keys).toEqual(["applications", "inbox", "compliance"]);
    expect(navFor("INSTITUTION")[0].label).toBe("My applications");
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
    expect(within(nav).getByRole("button", { name: "My applications" })).toHaveAttribute("aria-current", "page");
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
    await screen.findByText("My applications", { selector: "h1" });
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
    expect(fixtureAdapter.confirmFact).toBeNull();
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
    const button = await screen.findByRole("button", { name: "Mark read" });
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
    await user.click(await screen.findByRole("button", { name: "Mark read" }));
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
  it("never calls a partial result fully verified", async () => {
    const { checkpointState, replayState, headline } = await import("../views/AuditView.jsx");
    const checkpointed = { ok: true, assurance: "CHECKPOINTED" };
    const chainOnly = { ok: true, assurance: "CHAIN_ONLY", status: "NO_TRUSTED_CHECKPOINT" };
    expect(checkpointState(chainOnly)[0]).toBe("warn");
    expect(replayState({ verdict: "CONSISTENT_SUBSET" })[0]).toBe("warn");
    expect(headline(true, chainOnly, { verdict: "VERIFIED_COMPLETE" })[0]).toBe("warn");
    expect(headline(true, checkpointed, { verdict: "CONSISTENT_SUBSET" })[0]).toBe("warn");
    expect(headline(true, checkpointed, null)[0]).toBe("warn");
    expect(headline(true, checkpointed, { verdict: "VERIFIED_COMPLETE" })).toEqual(["ok", "Fully verified"]);
    expect(headline(false, checkpointed, { verdict: "VERIFIED_COMPLETE" })[0]).toBe("bad");
    expect(headline(true, { ok: false, status: "WITNESS_CORRUPT" }, null)[0]).toBe("bad");
  });
});
