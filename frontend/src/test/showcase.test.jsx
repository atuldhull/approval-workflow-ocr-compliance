import { fireEvent, render, screen, waitFor, within, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App.jsx";
import { ShowcaseGate, isShowcaseHash } from "../showcase/entry.jsx";
import Showcase, { parseShowcaseHash } from "../showcase/Showcase.jsx";
import { ROUTES, TOUR, TOUR_STEP_MS } from "../showcase/data.js";
import { fakeServer } from "./fakeServer.js";

const DEMO_ME = { user_id: "u-1", role: "INSTITUTION", institution_id: "i-1" };

beforeEach(() => {
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
});
afterEach(() => {
  history.replaceState(null, "", "/");
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const gate = () => render(<ShowcaseGate><App /></ShowcaseGate>);
const heroHeading = () => screen.findByRole("heading", { level: 1, name: /Every approval has a path/ });

describe("showcase routing", () => {
  it("recognises only showcase fragments", () => {
    expect(isShowcaseHash("#showcase")).toBe(true);
    expect(isShowcaseHash("#showcase/audit")).toBe(true);
    expect(isShowcaseHash("#showcase/tour/3")).toBe(true);
    for (const h of ["", "#", "#inbox", "#applications?case=abc", "#overview", "#showcaseX", "#show"]) expect(isShowcaseHash(h)).toBe(false);
    expect(parseShowcaseHash("#showcase/tour/3")).toEqual({ tour: 2 });
    expect(parseShowcaseHash("#showcase/route")).toEqual({ chapter: "route" });
    expect(parseShowcaseHash("#showcase/nonsense")).toEqual({ chapter: null });
  });

  it("renders the showcase without any backend request", async () => {
    const calls = fakeServer({});
    history.replaceState(null, "", "/#showcase");
    gate();
    await heroHeading();
    expect(screen.getAllByText(/not the AICTE portal/).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Explore how it works" })).toBeVisible();
    expect(screen.getAllByRole("button", { name: /workspace/i }).length).toBeGreaterThan(0);
    expect(calls).toHaveLength(0);
  });

  it("leaves workspace deep links to the app and keeps its config request", async () => {
    const calls = fakeServer({ "GET /api/auth/config": () => new Promise(() => {}) });
    history.replaceState(null, "", "/#applications?case=abc");
    gate();
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/api/auth/config"))).toBe(true));
    expect(screen.queryByRole("heading", { name: /Every approval has a path/ })).toBeNull();
    expect(window.location.hash).toBe("#applications?case=abc");
  });

  it("switches between workspace and showcase through the address, both ways", async () => {
    fakeServer({ "GET /api/auth/config": { mode: "demo" }, "GET /api/auth/me": DEMO_ME, "GET /api/applications": [] });
    history.replaceState(null, "", "/#overview");
    gate();
    const link = await screen.findByRole("link", { name: /How it works/ });
    expect(link).toHaveAttribute("href", "#showcase");
    act(() => { history.pushState(null, "", "#showcase"); window.dispatchEvent(new HashChangeEvent("hashchange")); });
    await heroHeading();
    act(() => { history.back(); });
    await waitFor(() => expect(screen.queryByRole("heading", { name: /Every approval has a path/ })).toBeNull(), { timeout: 3000 });
  });
});

describe("showcase content", () => {
  it("uses the standard view without WebGL, with the same information as an SVG figure", async () => {
    history.replaceState(null, "", "/#showcase");
    const { container } = render(<Showcase />);
    expect(container.querySelector(".sc-root")).toHaveAttribute("data-render", "standard");
    expect(screen.getByRole("img", { name: /Illustrative dossier/ })).toBeInTheDocument();
    expect(container.querySelector("canvas")).toBeNull();
  });

  it("composes static frames under reduced motion", () => {
    history.replaceState(null, "", "/#showcase");
    const { container } = render(<Showcase />);
    expect(container.querySelector(".sc-root")).toHaveAttribute("data-motion", "reduced");
    expect(container.querySelector(".sc-hero")).toHaveClass("is-static");
    expect(container.querySelectorAll(".sc-beat.is-active")).toHaveLength(5);
    expect(container.querySelector(".sc-audit")).toHaveAttribute("data-step", "5");
  });

  it("follows the motion setting when motion is allowed", () => {
    vi.stubGlobal("matchMedia", (q) => ({ matches: false, media: q, addEventListener() {}, removeEventListener() {} }));
    history.replaceState(null, "", "/#showcase");
    const { container } = render(<Showcase />);
    expect(container.querySelector(".sc-root")).toHaveAttribute("data-motion", "full");
    expect(container.querySelector(".sc-hero")).not.toHaveClass("is-static");
  });

  it("navigates chapters by deep link and focuses the chapter heading", async () => {
    history.replaceState(null, "", "/#showcase");
    render(<Showcase />);
    const nav = screen.getByRole("navigation", { name: "Chapters" });
    expect(within(nav).getAllByRole("link")).toHaveLength(6);
    act(() => { history.pushState(null, "", "#showcase/audit"); window.dispatchEvent(new HashChangeEvent("hashchange")); });
    await waitFor(() => expect(screen.getByRole("heading", { name: "Trust Through Audit" })).toHaveFocus());
  });

  it("draws each category's route from the rule set, with conditional stages only where they exist", async () => {
    const user = userEvent.setup();
    history.replaceState(null, "", "/#showcase");
    render(<Showcase />);
    const index = () => within(screen.getByRole("list", { name: "Stages in this route" })).getAllByRole("button").map((b) => b.textContent.replace(/^\d+\s*/, ""));
    expect(index()).toEqual(["Application submitted", "Scrutiny", "Expert visit (EVC)", "SHC · as applicable", "Outcome recorded here"]);
    await user.click(screen.getByRole("button", { name: "EoA · self-disclosure" }));
    expect(index()).toEqual(["Application submitted", "Self-disclosure", "Outcome recorded here"]);
    await user.selectOptions(screen.getByRole("combobox", { name: /All 22 categories/ }), "NEW_INSTITUTION");
    expect(index()).toEqual(["Application submitted", "Scrutiny", "Expert visit (EVC)", "SHC · as applicable", "Executive Committee (EC)", "Council", "Outcome recorded here"]);
    expect(ROUTES).toHaveLength(22);
    await user.click(screen.getByRole("button", { name: "Next stage" }));
    expect(screen.getByText("Stage 2 of 7")).toBeInTheDocument();
    expect(screen.getByText(/Scrutiny committee \(records deficiencies/)).toBeInTheDocument();
  });

  it("reveals the machine reading only after the visitor commits theirs, without any request", async () => {
    const calls = fakeServer({});
    const user = userEvent.setup();
    history.replaceState(null, "", "/#showcase");
    render(<Showcase />);
    expect(screen.queryByText("4,320")).toBeNull();
    await user.type(screen.getByLabelText("Total built-up area (sq m)"), "4820");
    await user.click(screen.getByRole("button", { name: "Commit my reading" }));
    expect(screen.getByText("4,320")).toBeInTheDocument();
    expect(screen.getByText(/differs from the proposal/)).toBeInTheDocument();
    expect(calls).toHaveLength(0);
  });

  it("states what each audit layer can and cannot show", () => {
    history.replaceState(null, "", "/#showcase");
    render(<Showcase />);
    expect(screen.getByText(/Not that they were true when recorded/)).toBeInTheDocument();
    expect(screen.getByText(/Same machine. Not an authority./)).toBeInTheDocument();
  });
});

describe("guided tour", () => {
  it("steps forward and back, pauses, and exits with Escape", async () => {
    const user = userEvent.setup();
    history.replaceState(null, "", "/#showcase");
    render(<Showcase />);
    await user.click(screen.getByRole("button", { name: /Guided tour/ }));
    const tour = screen.getByRole("region", { name: "Guided tour" });
    expect(within(tour).getByText(`Step 1 of ${TOUR.length}`)).toBeInTheDocument();
    expect(window.location.hash).toBe("#showcase/tour/1");
    await user.click(within(tour).getByRole("button", { name: "Next" }));
    expect(within(tour).getByText(`Step 2 of ${TOUR.length}`)).toBeInTheDocument();
    await user.click(within(tour).getByRole("button", { name: "Previous" }));
    expect(within(tour).getByText(`Step 1 of ${TOUR.length}`)).toBeInTheDocument();
    const pause = within(tour).getByRole("button", { name: "Pause" });
    expect(pause).toHaveAttribute("aria-pressed", "true");
    await user.click(pause);
    expect(within(tour).getByRole("button", { name: "Resume" })).toHaveAttribute("aria-pressed", "false");
    await user.selectOptions(within(tour).getByRole("combobox", { name: "Jump to step" }), "6");
    expect(within(tour).getByText(`Step 7 of ${TOUR.length}`)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("heading", { name: "Trust Through Audit" })).toHaveFocus());
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("region", { name: "Guided tour" })).toBeNull();
    expect(window.location.hash).toBe("#showcase");
  });

  it("advances on its own only while playing", () => {
    vi.useFakeTimers();
    history.replaceState(null, "", "/#showcase");
    render(<Showcase />);
    fireEvent.click(screen.getByRole("button", { name: /Guided tour/ }));
    act(() => { vi.advanceTimersByTime(TOUR_STEP_MS + 10); });
    expect(screen.getByText(`Step 2 of ${TOUR.length}`)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    act(() => { vi.advanceTimersByTime(TOUR_STEP_MS * 3); });
    expect(screen.getByText(`Step 2 of ${TOUR.length}`)).toBeInTheDocument();
  });

  it("opens paused at a deep-linked step", () => {
    history.replaceState(null, "", "/#showcase/tour/4");
    render(<Showcase />);
    expect(screen.getByText(`Step 4 of ${TOUR.length}`)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Resume" })).toBeInTheDocument();
  });

  it("never sends a non-GET request through the whole tour, and ends in the workspace", async () => {
    const calls = fakeServer({ "GET /api/auth/config": { mode: "demo" }, "GET /api/auth/me": DEMO_ME, "GET /api/applications": [] });
    const user = userEvent.setup();
    history.replaceState(null, "", "/#showcase");
    gate();
    await heroHeading();
    await user.click(screen.getByRole("button", { name: /Guided tour/ }));
    const tour = screen.getByRole("region", { name: "Guided tour" });
    for (let i = 1; i < TOUR.length; i++) await user.click(within(tour).getByRole("button", { name: "Next" }));
    expect(within(tour).getByText(`Step ${TOUR.length} of ${TOUR.length}`)).toBeInTheDocument();
    expect(calls).toHaveLength(0);
    await user.click(within(tour).getByRole("button", { name: "Enter workspace" }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/api/auth/me"))).toBe(true));
    expect(window.location.hash).toBe("");
    expect(calls.every((c) => c.method === "GET")).toBe(true);
  });
});
