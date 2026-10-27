# AICTE integration readiness

**Status (25 Oct 2026):** this system is **not connected** to any AICTE or NSWS system. No integration has been
authorised, no AICTE interface specification or credentials exist, and nothing below describes a working connector.
This document fixes the boundary so that an adapter can be added later, when an authorised interface exists, without
changing ownership or weakening the existing guarantees.

Evidence labels: **VERIFIED_OFFICIAL** (opened an AICTE or government document), **THIRD_PARTY_EXAMPLE** (an
official AICTE letter or notice reposted by an institution or state body), **DOCUMENTED_HISTORICAL** (older official
material), **DESIGN_PROPOSAL** (ours), **UNVERIFIED** (secondary or snippet only).

## 1. Sources

| Source | Label | Notes |
|---|---|---|
| [Approval Process Handbook 2024-27](https://cdnbbsr.s3waas.gov.in/s35938b4d054136e5d59ada6ec9c295d7a/uploads/2025/03/2025031399.pdf) | VERIFIED_OFFICIAL | Clause and page references below are to this text. Applies to 2024-25 to 2026-27. |
| AICTE EoA letter 2026-27, VIT Pune ([PDF](https://www.vit.edu/wp-content/uploads/2026/08/AICTE-EoA-LETTER-for-A.Y.-2026-27.pdf)) | THIRD_PARTY_EXAMPLE | Permanent Id, Application Id, file number, intake table. |
| AICTE EoA letter 2026-27, FSM Delhi ([PDF](https://www.fsm.ac.in/images/cms/approval-letter-of-delhi-campus-2026-2027.pdf)) | THIRD_PARTY_EXAMPLE | "Deficiencies noted based on self disclosure", to be complied within six months. |
| AICTE LoA 2026-27, ICFAI University Tripura ([PDF](https://www.iutripura.edu.in/assets/pdf/recognitions-accreditations/LOA-Report-2026-2027.pdf)) | THIRD_PARTY_EXAMPLE | New institution: Permanent Id equals Application Id; computer generated, no signature. |
| Supreme Court order of 12 Aug 2026 and AICTE revised academic calendar 2026-27 (circular AICTE/RB-AC-2026-27/2, 13 Aug 2026), reposted by [PTU](https://ptu.ac.in/wp-content/uploads/2026/09/2026-09-01-Regarding-Last-date-of-admission.pdf) | THIRD_PARTY_EXAMPLE | Time for grant of approval for 2026-27 extended to 14 Sep 2026. |
| Original academic calendar 2026-27 (annexed to a Haryana DTE notice, [PDF](https://hstes.org.in/Documents/2026/Notifications/Adobe%20Scan%20Apr%2020,%202026.pdf)) | THIRD_PARTY_EXAMPLE | Approval by 30 Apr, affiliation by 31 May, classes from 14 Aug (later revised). |
| Public notice for approval process 2026-27 (26 Nov 2025) and revision (4 Feb 2026) | UNVERIFIED | Seen only in secondary summaries; the AICTE PDFs were unreachable. Says new institutions apply through NSWS. |
| [National Single Window System](https://www.nsws.gov.in/) | VERIFIED_OFFICIAL (homepage only) | Lists "Know Your Approvals" across central departments. No department API documentation found. |
| portal.aicte-india.org, facilities.aicte-india.org, www.aicte-india.org | — | Connections reset from our network on 25 Oct 2026; www.aicte.gov.in showed a maintenance page. **Portal screens, statuses and any APIs are unverified.** |

## 2. Who owns what

| Thing | Source of truth | In this system |
|---|---|---|
| Approval decisions (LoA, EoA, LoD, LoR, speaking orders) | AICTE: Executive Committee, ratified by the Council (APH 1.10, 2.25a) | Our status is a workflow record only. The UI says "Status in this system. AICTE's decision is issued only through the AICTE portal." |
| Institution master record, Permanent Id | AICTE portal | `wf.institution` (Person 1) holds synthetic institutions only. |
| Application Id and file number | AICTE portal | Not held. Our case id is an internal UUID and is labelled "Internal ref". |
| Committee reports (scrutiny, EVC, SHC, SAC) | AICTE portal (APH 1.9h: reports made available through the portal) | Modelled as route stages (Person 1); no report import. |
| New-institution applications | NSWS front door, then AICTE (UNVERIFIED, per public-notice summaries) | Not modelled. |
| Deadlines and obligations derived from APH rules | This system (Person 2), from versioned rules | Each deadline carries `ruleset`, `revision`, `clause`, `source_status`. |
| Audit ledger, checkpoints, notifications | This system (Person 3) | Integrity evidence for this system only, not government authentication. |

## 3. Official identifiers

| Identifier | Seen on | Format observed | Held here? | Owner if added |
|---|---|---|---|---|
| Permanent Id | EoA, LoA | `1-` followed by 7–11 digits (e.g. `1-3514117`) | No | Person 1 (`wf.institution`) |
| Application Id | EoA, LoA | `1-` followed by 11 digits; equals the Permanent Id for a new institution | No | Person 1 (`wf.application`) |
| File number | EoA, LoA | `F.No. <Region>/<Application Id>/2026/EOA` and `F.No. Eastern/2026-27/<Id>`: the format differs between letters | No | Person 2 (`cmp.approval_letter`) |
| Region | All | Region name (Western, Eastern, Southern, …) | Yes, `ro_region` on institution | Person 1 |
| Academic year | All | `2026-27` | Yes, `academic_year` | Person 1 |
| Date of approval, printed-on date, printed-by | Letters | `16-Mar-2026`; printed-by looks like an officer user id | No | Person 2 |
| Programme and intake (previous and current year, NRI, international) | Letters | Table | No | Person 2 (letter), Person 1 (application) |

Rules: our UUID is never displayed as an AICTE id; no Permanent Id or file number is generated. The case screen lists
the three AICTE identifiers as "Not linked" or "Not issued in this system", and a test fails if a value shaped like
an AICTE id or `F.No.` appears. Adding real identifiers needs Person 1 and Person 2 schema changes and a contracts
change (see `APH_CONFORMANCE_PROPOSALS.md`).

## 4. Workflow concepts

| Concept | APH source | Model today (person-1 branch, read-only) | Frontend | Mapping | Owner | Follow-up |
|---|---|---|---|---|---|---|
| Category-specific route | Table 2.3, p. 30 | `routes.yaml` stage lists for all 21 Table 2.3 types and new institutions | Route stages as listed, 3D gates from returned stages | Exact | P1 | — |
| Scrutiny / re-scrutiny | 1.8, 2.23.1 | `SCRUTINY`, `DEFICIENT`, `RESCRUTINY` | "Scrutiny", "Deficiency reply", "Re-scrutiny" | Exact | P1 | — |
| Expert Visit Committee | 1.9, 2.23.2 | `EVC` stage; scheduling not built | Stage label; EVC screen is a labelled sample | Partial | P1 | EVC API |
| Standing Hearing Committee, as applicable | 2.23.3, Table 2.3 "AA" | `SHC` with `when: as_applicable` | "If applicable" | Exact | P1 | — |
| Executive Committee decision, Council ratification | 1.10a, 2.23.3, 2.25a | `EC`, `COUNCIL` only on the new-institution route; Chapter II letters issued by a bureau officer | Not shown for Chapter II | Partial | P1 | Proposal P1-1 |
| Standing Appellate Committee, one appeal in 7 days | 1.11, 2.24 | `appeal:` window `APPEAL_7D`, `max_appeals: 1`; no SAC stage | Not shown | Partial | P1 | Proposal P1-2 |
| LoA / EoA | 1.10b, 2.25b | `issue_loa`, `issue_eoa` → `APPROVED` | "Approved" with the status note | Partial | P1 | — |
| LoD (deficiency) | 1.10b, 1.11a | `issue_lod` → `REJECTED` (terminal) | "Rejected" | **Mismatch**: an LoD can be appealed and is not a rejection | P1 | Proposal P1-3 |
| LoR (rejection) and speaking order | 1.10b | Not modelled | — | Missing | P1 | Proposal P1-3 |
| Random inspection EVC | 2.3.5 | Not modelled | — | Missing | P1 | Later |
| Numerical grade | none | — | Scorecard measures this system, not institutions | Not applicable: approval is not graded | — | — |

## 5. Deadlines and calendars

| Deadline | APH source | Model today | Provenance shown in UI |
|---|---|---|---|
| Appeal: 7 days from upload of the decision | 2.24(a) (Chapter I: from issue of the LoD, 1.11a) | `APPEAL_7D`, `verified`, clause `2.24(a)` | "Handbook clause · APH 2024-27 clause 2.24(a) · rule set aph-2024-27 r1" |
| Security deposit plus Affidavit 3 in 15 days; 10% / 20% penalty to 31 May / 31 July, then approval withdrawn | 2.25(f), 1.12 | `DEPOSIT_15D`, `verified`; tiers marked "suggestion only"; withdrawal not modelled | "Handbook clause" |
| Deficiencies in an EoA, comply within six months | EoA letters (THIRD_PARTY_EXAMPLE); APH 2.25(c) says before the next EoA | `EOA_DEFICIENCY_6M`, `verified_letter_text` | "Approval-letter text" |
| Lease: no EoA once the live lease equals the longest course | 2.1(e) | `LEASE_EOA_STOP` (computed, not yet implemented) | — |
| LoA valid for two academic years, then cancelled | 1.10b(ii) | Not modelled | — |
| AICTE processing (30 days), institution response (15 days) | none: Table 2.2 says "as per Public Notice Period" | `demo_assumption` | "Demo assumption · No handbook figure; configurable, not an AICTE date" |
| Annual public notice and academic calendar, with revisions (2026-27 extended to 14 Sep 2026 by the Supreme Court) | 2.2, 2.25(j); calendar circulars | Not modelled. Person 2 has versioned working-day calendars on `person-2` (`a9db919`), but not AICTE's notice or calendar dates | "Calendar version: not supplied by the deadline service" |

The frontend computes no dates. It shows the API's `due_date`, its explanation, and a source label from
`source_status` and `clause` (`frontend/src/provenance.js`). An unknown `source_status` shows "Source not supplied".

## 6. Approval letters

Real letters (THIRD_PARTY_EXAMPLE) carry: approval process year and letter type, file number, date of approval,
Permanent Id and Application Id, institution name, type, region and year of establishment, a programme table with
approved intake (previous and current year, NRI, international), a deficiency block with the six-month clause (EoA),
the conditions of approval, "computer generated, no signature required", and printed-on and printed-by.

This system holds no letters yet (Person 2's `cmp.approval_letter` is planned). Until it does, the frontend shows no
letter and generates nothing letter-shaped. When letters exist, the screen should show them only as records of this
system, prominently marked as samples while the data is synthetic, never with an emblem, seal or signature, and never
as an AICTE document.

## 7. Provenance on screen

| Kind | How it is shown |
|---|---|
| Synthetic data | "Synthetic data" badge in the top bar, in every mode |
| Our identifiers | "Internal ref" with a tooltip saying it is not an AICTE Application Id |
| AICTE identifiers | "Not linked" or "Not issued in this system" |
| Workflow status | Status plus "Status in this system. AICTE's decision is issued only through the AICTE portal." |
| Deadline source | "Handbook clause", "Approval-letter text", "Demo assumption" or "Source not supplied" |
| OCR | Machine reading only after the human commits; "Facts: confirmed by server" only after the server confirms |
| Audit | Three separate layers; a same-machine demo witness is "recorded", never "anchored"; "not authentication by AICTE or any government system" |
| Preview features | "PREVIEW · SAMPLE" on EVC, compliance and document review |

## 8. A future connector (DESIGN_PROPOSAL)

Nothing here is a fact about AICTE systems. It is how a connector would fit our architecture if AICTE authorises one.

- **Direction:** read first. Import AICTE identifiers, decisions and committee outcomes; do not write to AICTE. Any
  write (for example submitting compliance) needs explicit written authorisation and AICTE's own interface.
- **Where it lives:** an adapter behind a port, owned by the module whose data it changes. Workflow imports go
  through Person 1's planned `wf.inbound_event` table; letters through Person 2's `cmp.approval_letter`. The
  connector never writes another module's tables.
- **Authentication:** whatever AICTE specifies. Likely service-to-service: OAuth client credentials or mutual TLS.
  Credentials come from a secret store, are rotated, and are never in the repo. The connector gets its own service
  principal and Cerbos role, with nothing beyond import rights.
- **No public ingestion endpoint:** a pull worker, or a push endpoint only behind AICTE-issued authentication plus
  signature verification if AICTE offers it. No unauthenticated webhook, and no demo endpoint that looks production-like.
- **Idempotency and replay:** each inbound record keyed by (source system, external record id, external version).
  Duplicates are no-ops; an older version than the one held is refused. Push requests also need a timestamp window and
  a nonce, if the interface supports them.
- **Provenance:** every imported fact records source system, external id, fetch time, payload hash and the
  connector principal, and goes into the hash-chained ledger like any other event. Imported events would be new event
  types, and so a contracts change.
- **Conflicts:** an external decision never silently overwrites a local state that disagrees with it. The case is
  flagged for an officer, both values are kept, and the resolution is recorded with its reason.
- **Failure:** time-outs, retries with backoff, and the transactional outbox for anything we send. An outage leaves
  workflow state unchanged and shows "external data unavailable", never stale data presented as current. A
  reconciliation job compares counts and versions after an outage.
- **Data minimisation and logs:** import only the fields needed. Personal data stays in `plat.personal_data`; logs
  carry ids and hashes, never payloads or tokens.
- **Schema versions:** the adapter maps each external schema version explicitly and fails closed on an unknown one.
- **Monitoring:** lag, error rate and last-successful-sync per source, surfaced like delivery health is today.

What already supports this: the idempotency middleware (claimed inside the command's unit of work), the transactional
outbox with leases and fencing, the hash-chained ledger with signed checkpoints and replay, Cerbos with deny-by-default
and fail-closed behaviour, and OIDC token verification with issuer and audience checks.

## 9. Evidence matrix

| Requirement | Source | Label | AY | Implementation | Owner | Readiness | Next action |
|---|---|---|---|---|---|---|---|
| Route per application type | APH Table 2.3 p. 30 | VERIFIED_OFFICIAL | 2024-27 | `routes.yaml` | P1 | Ready | — |
| EC decision and Council ratification | APH 1.10a, 2.23.3, 2.25a | VERIFIED_OFFICIAL | 2024-27 | New-institution route only | P1 | Partial | P1-1 |
| One appeal to SAC within 7 days | APH 1.11, 2.24 | VERIFIED_OFFICIAL | 2024-27 | Window only | P1 | Partial | P1-2 |
| LoD is not a rejection; LoR with speaking order | APH 1.10b, 1.11a | VERIFIED_OFFICIAL | 2024-27 | LoD → REJECTED | P1 | Mismatch | P1-3 |
| Regional officers see their region's cases | Our policy design | DESIGN_PROPOSAL | — | List refused (403) | P1 | Missing | P1-4 |
| Deposit penalty, then withdrawal | APH 2.25(f) | VERIFIED_OFFICIAL | 2024-27 | Tiers "suggestion only" | P2 | Partial | P2-1 |
| LoA valid two academic years | APH 1.10b(ii) | VERIFIED_OFFICIAL | 2024-27 | Missing | P2 | Missing | P2-2 |
| Processing windows per public notice and calendar | APH 2.2, Table 2.2, 2.25(j); 2026-27 calendar revision | VERIFIED_OFFICIAL (rule); THIRD_PARTY_EXAMPLE (dates) | 2026-27 | Demo day counts | P2 | Missing | P2-3 |
| Six-month EoA deficiency compliance | EoA letters | THIRD_PARTY_EXAMPLE | 2026-27 | `EOA_DEFICIENCY_6M` | P2 | Ready (pending letters) | P2-4 |
| AICTE identifiers on cases and letters | EoA and LoA letters | THIRD_PARTY_EXAMPLE | 2026-27 | Not held; shown as not linked | P1, P2 | Missing | P1-5, P2-5 |
| New institutions apply through NSWS | Public-notice summaries | UNVERIFIED | 2026-27 | Not modelled | — | Unknown | Confirm with AICTE |
| Portal API, data exchange | none found | UNVERIFIED | — | None | — | Blocked | Ask AICTE |
| Status labels shown on the portal | none current | UNVERIFIED | — | Our own labels | P3 | Labelled as ours | Ask AICTE |

## 10. Questions for AICTE

1. Is there an authorised interface for approval data (read or write), and what is its authentication model?
2. Are Permanent Id, Application Id and file number stable, and what are their exact formats?
3. Which status labels does the portal show institutions at each stage?
4. Are committee reports and decisions available electronically, and with what versioning?
5. How are public-notice revisions and court-ordered extensions published in machine-readable form?
6. What is NSWS's role for new institutions, and does it expose application status?
