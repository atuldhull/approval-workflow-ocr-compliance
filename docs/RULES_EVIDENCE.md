# Rule evidence: where every timer, route and rule comes from

Every rule the prototype runs on lives in [`rulesets/aph-2024-27/r1/`](../rulesets/aph-2024-27/r1/). This table lists
each one with its status:

- **Official** — the value is in the Approval Process Handbook 2024-25 to 2026-27 (APH), cited as clause and page
  (PDF page of the published handbook), or in the text of an official AICTE letter.
- **Demo assumption** — no figure was found in the APH. The value is a configurable placeholder, labelled
  `demo_assumption` / `DEMO ASSUMPTION` in the YAML and in the UI. It must not be presented as an AICTE rule.
- **Not built** — the APH sets the rule, but the prototype does not run it yet.

**The APH sets no internal processing times.** It does not say how many days scrutiny, an expert visit, the Standing
Hearing Committee or a deficiency reply may take. Table 2.2 (p.44) gives the processing period of every category as
"As per Public Notice Period" (category 1) or "Year round" (category 2): the calendar comes from AICTE's yearly public
notice, not from the handbook. Every internal clock below is therefore a demo assumption, and so is every advance
reminder and escalation step.

## Deadlines (`deadlines.yaml`)

| Rule | Value | Status | Evidence / note |
|---|---|---|---|
| `AICTE_PROCESSING` | 30 calendar days from submission | Demo assumption | APH Table 2.2 (p.44): "As per Public Notice Period". No internal SLA. |
| `EVC_PROCESSING` | 7 calendar days from the EVC request | Demo assumption | No EVC lead time in the APH; one global value for every route. |
| `INSTITUTION_RESPONSE` | 15 calendar days from a deficiency | Demo assumption | No deficiency reply window in the APH; dates come from the public notice. |
| `APPEAL_7D` | 7 days from the decision | Official | cl. 1.11(a) (p.25): within 7 days of the LoD; cl. 2.24(a) (p.45): within 7 days of the decision upload. Calendar vs working days not stated. |
| `DEPOSIT_15D` | 15 calendar days from the LoA issue date | Official | cl. 2.25(f) (p.47): security deposit and Affidavit 3 within 15 days of the intimation. |
| `DEPOSIT_15D` penalty tiers | 10 % to 31 May, 20 % to 31 July, then approval withdrawn | Official | cl. 2.25(f) (p.47). Shown to officers as notes; the system never applies a penalty. |
| `DEPOSIT_15D` reminders | 7, 2 and 1 days before | Demo assumption | The APH sets no reminder schedule. |
| `AFFIDAVIT3_REMAINING_1M` | 1 month from the LoA issue date | Official | APH p.205, Affidavit 3 item 5: remaining requirements within one month of the approval letter. |
| `NO_ADMISSION_AFFIDAVIT_7D` | 7 calendar days, recorded by an officer | Official | cl. 1.10(b)(i) (p.24): affidavit within seven days when no admissions are made. |
| `LOA_VALIDITY_2Y` | 24 months from the LoA issue date | Official | cl. 1.10(b)(ii) (p.25): LoA valid for two academic years. Counting 24 calendar months is our reading. |
| `EOA_DEFICIENCY_6M` | 6 months from the EoA issue date | Official (letter text) | Text of EoA letters that list deficiencies; cl. 2.25(c) (p.47): comply before the next EoA. Reminders (60/30/7 days) are a demo assumption. |
| `LEASE_EOA_STOP` | stop year = when the live lease equals the longest course | Official | cl. 2.1(e) (p.28): no EoA from that year unless the lease is extended by a further 30 years. |
| `LEASE_EOA_STOP` minimum lease | 30 years; live lease at least the longest course | Official | cl. 6.17(a) (p.72); lease deed registered, cl. 6.17(b). |
| `LEASE_EOA_STOP` longest course | 4 years unless the officer states it | Demo assumption | The case does not record its programmes' durations. Reminders (18/12/6 months) are a demo assumption. |
| `DOCUMENT_EXPIRY` | due on the document's own expiry date | Official | cl. 6.17 (p.72–73): lease deed (a), OC/CC (g), structural stability (h) and fire safety certificate (i) must be valid. The expiry is read from the document; the APH sets no period except for (h). Reminders (90/30/7 days) are a demo assumption. |
| `STRUCTURAL_STABILITY_VALIDITY` | 60 months from issue | Official | cl. 6.17(h) (p.73): required 30 years after the completion certificate, valid five years from issue. |
| `UNDERTAKING_DUE_DATE` | the due date the undertaking states | Official (letter text) | The date comes from the undertaking or letter the officer records. Reminders (7/2 days) are a demo assumption. |
| `LOA_DEPOSIT_AFFIDAVIT_15D` | 15 calendar days | Demo assumption (superseded) | No longer opened; kept so older clocks still resolve. Replaced by `DEPOSIT_15D`. |
| Academic year start | 1 July | Demo assumption | The APH text read so far does not fix the start day. |
| Security deposit held 10 years, double for leased land | — | Not built | cl. 1.12 / 2.25(g), Table 1.4 (p.26). Recorded in the APH facts; no clock runs on it. |
| LoA cancelled after two academic years | — | Not built | cl. 1.10(b)(ii) (p.25). `LOA_VALIDITY_2Y` tracks the date; nothing cancels the letter. |

## Alerts and escalation (`deadlines.yaml` `alerts:`)

| Rule | Value | Status | Evidence / note |
|---|---|---|---|
| `standard` ladder | owner −2 days, RO at due, bureau officer +3 days, bureau head +7 days | Demo assumption | The APH sets no reminder or escalation schedule. |
| `reminder_only` ladder | owner −2 days, never escalated | Demo assumption | Used for `APPEAL_7D`: not appealing is the institution's choice. |
| `document_expiry` ladder | RO at expiry, bureau officer +7 days, bureau head +30 days | Demo assumption | |
| Channels, owner roles, retry after 15 minutes | in-app and email | Demo assumption | |

## Notifications (`notifications.yaml`)

| Rule | Status | Evidence / note |
|---|---|---|
| Deficiency recorded → institution | Demo assumption | The APH does not say who is told what, or how. |
| EVC visit published → institution and scrutiny committee | Demo assumption | |
| Evidence accepted or rejected → institution | Demo assumption | |
| Letter registered → institution | Demo assumption | |
| Deadline missed → the clock's owner (unless its ladder already tells that role) | Demo assumption | |

## Routes and stages (`routes.yaml`)

| Rule | Status | Evidence / note |
|---|---|---|
| Stage sequence per category (22 routes) | Official | APH Table 2.3 (p.46): self-disclosure only; scrutiny only (change of name, closure, reduction in intake, ...); scrutiny + EVC + SAC/SHC "as applicable" (new programme, increase in intake, change of site, ...). The per-route `clause_citation` in the YAML is still marked `UNCONFIRMED`; the routing answer key is a manual transcription. |
| New institution: Scrutiny → Re-Scrutiny → EVC → EC → Council | Official | cl. 1.8–1.11. |
| SHC applies exactly where an EVC is held | Official | Table 2.3 "as applicable"; SHC reviews EVC reports and show-cause replies (definition 55, cl. 2.23.3). Whether it applies to a case is decided by forming an SHC workspace (demo assumption GF-002). |
| EVC held online by default | Official | Note under cl. 1.8 (p.24); video of at least 30 minutes, cl. 1.9(f) (p.24). The prototype schedules the visit; it does not hold it. |
| Transition policies (who may act, when a revert needs a second approver) | Demo assumption | TG-001..TG-006 and GF-001..GF-006 in [p1/ASSUMPTIONS.md](p1/ASSUMPTIONS.md). |
| Letter issued at the last applicable stage (LoA / EoA / LoD) | Official | cl. 1.10. Issue date is today's date on the demo clock (PORTAL_EVENT). |
| Deficiency vocabulary (item keys and reason codes) | Demo assumption | Fictional `DEMO_*` codes. |
| Expert pool, selector, panel of three, one visit per expert per day, EDF / CP-SAT planning | Demo assumption | The real selection happens on AICTE's portal; the selector is a labelled stand-in. |
| "Only EVC" routes (random inspection, complaint EVC) | Not built | cl. 2.3.5(a) (p.31) and cl. 7.10 (p.89). |
| Appeal to the Standing Appellate Committee (SAC) and Letter of Rejection | Not built | cl. 1.11(a)–(e) (p.25), cl. 2.24(a) (p.45); LoR carries a speaking order, cl. 1.10(b). `APPEAL_7D` is defined but no route opens it. |

<!-- Rows for the Only-EVC routes and the SAC appeal are updated when that workflow work is merged. -->

## Checklists (`checklists.yaml`)

| Rule | Status | Evidence / note |
|---|---|---|
| Items per category (`DEMO_*` references) | Demo assumption | Fictional stand-ins for Annexure-2; the full lists are open question Q3. |
| DSC required at submission | Demo assumption | `INTAKE_DSC_DEMO_POLICY`. |
| Optional `LEASE_DEED`, `STRUCTURAL_STABILITY`, `FIRE_NOC` items | Official (what is tracked) | cl. 6.17(a), (h), (i): the documents whose validity is tracked once confirmed. Optional while Q3 is open. |

## How to change a rule

Edit the YAML, keep the `source` block honest (`status: verified` only with a clause and page you have read), and
run the tests: the ruleset is pinned per case, so cases already submitted keep the revision they started with.
Proposals for bringing the prototype closer to the APH are in
[handoffs/APH_CONFORMANCE_PROPOSALS.md](handoffs/APH_CONFORMANCE_PROPOSALS.md).
