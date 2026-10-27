import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import CaseDetail from "../components/CaseDetail.jsx";
import { DEMO_USERS } from "../api.js";
import { auditRecords } from "../operations/semanticData.js";
import { deadlineSource, internalRef } from "../provenance.js";
import { fakeServer } from "./fakeServer.js";

const who = DEMO_USERS[0];
const me = { user_id: who.user, role: who.role, institution_id: who.institution };
const APP = {
  id: "53f01ce2-9897-4eea-bcc6-e3ae443962d2", institution_id: who.institution, category: "NEW_PROGRAMME", academic_year: "2027-28",
  status: "IN_PROCESS", current_stage: "SCRUTINY", ruleset_rev: "aph-2024-27@r1", submitted_at: "2026-10-25T14:24:44Z",
  route: [{ stage: "SCRUTINY", when: "always" }, { stage: "EVC", when: "always" }, { stage: "SHC", when: "as_applicable" }],
};
const DEADLINES = [
  { id: "d1", rule_id: "AICTE_PROCESSING", ruleset: "aph-2024-27", revision: "r1", clause: null, source_status: "demo_assumption",
    clock_kind: "INTERNAL", status: "RUNNING", due_date: "2026-11-24", explanation: "30 calendar days (demo assumption)" },
  { id: "d2", rule_id: "APPEAL_7D", ruleset: "aph-2024-27", revision: "r1", clause: "2.24(a)", source_status: "verified",
    clock_kind: "LEGAL", status: "RUNNING", due_date: "2026-11-01", explanation: "7 days" },
];

const CASE = {
  case_id: APP.id, institution_id: who.institution, region: "Southern", stage: "SCRUTINY", status: "IN_PROCESS", version: 1,
  route_id: "NEW_PROGRAMME", ruleset_key: "aph-2024-27@r1", preview_ruleset_key: null, route: APP.route, clause_citation: null,
  stage_history: [], available_actions: [], assumption_status: "DEMO_ASSUMPTION",
};

function openCase(deadlines = DEADLINES) {
  fakeServer({ [`GET /api/applications/${APP.id}`]: APP, [`GET /api/cases/${APP.id}`]: CASE, "GET /api/deadlines": deadlines,
    [`GET /api/cases/${APP.id}/timeline`]: [] });
  render(<CaseDetail who={who} me={me} id={APP.id} onChanged={() => {}} />);
}

describe("official versus internal references", () => {
  it("labels our id as internal and shows AICTE identifiers as not linked", async () => {
    openCase();
    const ref = await screen.findByText(internalRef(APP.id));
    expect(ref.closest("p")).toHaveTextContent(/^Internal ref/);
    expect(ref).toHaveAttribute("title", expect.stringMatching(/Not an AICTE Application Id/));
    const refs = screen.getByLabelText("Official AICTE references");
    expect(within(refs).getByText("AICTE Permanent Id").nextSibling).toHaveTextContent("Not linked");
    expect(within(refs).getByText("AICTE Application Id").nextSibling).toHaveTextContent("Not linked");
    expect(within(refs).getByText("AICTE file number").nextSibling).toHaveTextContent("Not issued in this system");
  });

  it("says the status is this system's, not AICTE's decision", async () => {
    openCase();
    expect(await screen.findByText(/Status in this system\. AICTE's decision is issued only through the AICTE portal\./)).toBeInTheDocument();
  });

  it("never shows a real-looking AICTE identifier", async () => {
    openCase();
    await screen.findByText("Deadlines");
    const text = document.body.textContent;
    expect(text).not.toMatch(/\b1-\d{7,11}\b/);            // Permanent Id / Application Id shape on AICTE letters
    expect(text).not.toMatch(/F\.No\./);
    expect(text).not.toMatch(/connected to (the )?AICTE portal(?! yet)/i);
  });
});

describe("deadline provenance", () => {
  it("marks a configured assumption apart from a handbook clause", async () => {
    openCase();
    const assumption = (await screen.findByText("AICTE processing")).closest(".clock");
    expect(within(assumption).getByText("Demo assumption")).toHaveClass("warn");
    expect(within(assumption).getByText(/not an AICTE date/)).toBeInTheDocument();
    const clause = screen.getByText("Appeal 7d").closest(".clock");
    expect(within(clause).getByText("Handbook clause")).toHaveClass("ok");
    expect(within(clause).getByText(/APH 2024-27 clause 2\.24\(a\) · rule set aph-2024-27 r1/)).toBeInTheDocument();
    expect(screen.getByText(/Calendar version: not supplied/)).toBeInTheDocument();
  });

  it("does not guess a source it was not given", () => {
    expect(deadlineSource({ rule_id: "X" })).toEqual({ tone: "neutral", label: "Source not supplied", detail: "Rule set not supplied" });
    expect(deadlineSource({ source_status: "verified", ruleset: "aph-2024-27" }).detail).toBe("APH 2024-27, clause not supplied · rule set aph-2024-27");
    expect(deadlineSource({ source_status: "something_new", ruleset: "r", revision: "r9" }).label).toBe("Source not supplied");
  });
});

describe("audit witness wording", () => {
  const verify = { ok: true, status: "OK", assurance: "CHECKPOINTED", checkpoint_seq: 10, entries_after_checkpoint: 0 };
  it("a same-machine demo witness is recorded, not anchored, and says so", () => {
    const w = auditRecords({ ok: true, checked: 10 }, { ...verify, witness_kind: "local folder (DEMO ONLY)" }, null)[1];
    expect(w.label).toBe("Checkpoint witness");
    expect(w.state).toBe("recorded");
    expect(w.facts).toContainEqual(["Independence", "Same machine (demo only); not independent"]);
  });
  it("a broken chain is never shown as anchored, even with a checkpoint", () => {
    expect(auditRecords({ ok: false, first_bad_seq: 4 }, { ...verify, witness_kind: "remote" }, null)[1].state).toBe("unknown");
  });
  it("an intact chain with a configured witness is anchored, and still not called government authentication", () => {
    const w = auditRecords({ ok: true, checked: 10 }, { ...verify, witness_kind: "remote" }, null)[1];
    expect(w.state).toBe("anchored");
    expect(w.facts).toContainEqual(["Scope", "Integrity of this system's own log; not authentication by AICTE or any government system"]);
  });
});
