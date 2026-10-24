import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import App, { Workspace } from "../App.jsx";
import { DEMO_USERS, api } from "../api.js";
import { navFor } from "../nav.js";
import DashboardView from "../views/DashboardView.jsx";
import ApplicationsView from "../views/ApplicationsView.jsx";
import { FieldReview } from "../views/OcrReviewView.jsx";
import { OCR_SAMPLE } from "../fixtures/previews.js";
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
  it("keeps the machine reading hidden until the officer commits their own", async () => {
    const user = userEvent.setup();
    render(<FieldReview field={OCR_SAMPLE.fields[1]} text={OCR_SAMPLE.text} />);
    expect(screen.getByText("31-03-2031", { selector: "mark" })).toBeInTheDocument();
    expect(screen.queryByText("2031-03-31")).toBeNull();
    const commit = screen.getByRole("button", { name: "Commit my reading" });
    expect(commit).toBeDisabled();

    await user.type(screen.getByLabelText(/Your reading/), "2031-03-30");
    await user.click(commit);
    expect(screen.getByText("2031-03-31")).toBeInTheDocument();
    expect(screen.getByText("Differs - check the document")).toBeInTheDocument();
    expect(screen.getByLabelText(/Your reading/)).toBeDisabled();
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
