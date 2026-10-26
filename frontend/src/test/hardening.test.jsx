import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DEMO_USERS, api } from "../api.js";
import { DeadlineTimeline } from "../nebula/World.jsx";

const who = DEMO_USERS[0];

// A fetch that never answers until it is aborted, like a hung backend.
function hangingFetch() {
  vi.stubGlobal("fetch", vi.fn((url, init) => new Promise((_, reject) => {
    init.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
  })));
}

describe("requests that cannot complete", () => {
  it("a hung read gives up with a clear message instead of loading forever", async () => {
    hangingFetch();
    await expect(api(who, "/applications", { timeoutMs: 10 })).rejects.toMatchObject({
      status: 0, message: "The server did not answer in time. Try again shortly." });
  });

  it("a hung write says the outcome is unknown rather than inviting a blind retry", async () => {
    hangingFetch();
    await expect(api(who, "/applications/x/submit", { method: "POST", timeoutMs: 10 })).rejects.toMatchObject({
      status: 0, message: expect.stringMatching(/may or may not have been saved; refresh before trying again/) });
  });

  it("an unreachable server is reported in plain words", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(api(who, "/applications")).rejects.toMatchObject({
      status: 0, message: "The server cannot be reached. Check your connection and try again." });
  });

  it("a gateway error from the proxy is not shown as a raw status", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 502, statusText: "Bad Gateway", json: () => Promise.reject(new Error("html")) }));
    await expect(api(who, "/applications")).rejects.toMatchObject({ status: 502, message: "The server is unavailable right now. Try again shortly." });
  });
});

describe("deadline timeline dates", () => {
  it("shows a recorded timestamp in IST and keeps plain due dates as given", () => {
    render(<DeadlineTimeline submittedAt="2026-10-25T14:50:44.812074+00:00"
      deadlines={[{ id: "d1", due_date: "2026-11-24", rule_id: "AICTE_PROCESSING", status: "RUNNING" }]} />);
    expect(screen.getByText("25 Oct 2026, 20:20 IST")).toBeInTheDocument();
    expect(screen.getByText("2026-11-24")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/T14:50:44/);
  });

  it("does not crash on a date it cannot read", () => {
    render(<DeadlineTimeline deadlines={[{ id: "d1", due_date: "not-a-date", rule_id: "X", status: "RUNNING" }]} />);
    expect(screen.getByText("not-a-date")).toBeInTheDocument();
    expect(screen.getByText("Date could not be placed on the axis")).toBeInTheDocument();
  });
});

describe("production serving config", () => {
  const conf = readFileSync(resolve(__dirname, "../../nginx/default.conf.template"), "utf8");
  const csp = conf.match(/set \$csp "([^"]+)"/)[1];

  it("keeps a strict content security policy", () => {
    expect(csp).toMatch(/default-src 'self'/);
    expect(csp).toMatch(/script-src 'self';/);
    expect(csp).toMatch(/frame-ancestors 'none'/);
    expect(csp).toMatch(/object-src 'none'/);
    expect(csp).not.toMatch(/unsafe-inline|unsafe-eval|\*/);
  });

  it("serves the app for any path and never caches API responses or the page", () => {
    expect(conf).toMatch(/try_files \$uri \/index\.html;/);
    expect(conf.split("location ").find((b) => b.startsWith("/api/"))).toMatch(/proxy_no_cache 1;/);
    expect(conf).toMatch(/location \/ \{[^}]*Cache-Control "no-store"/s);
  });
});
