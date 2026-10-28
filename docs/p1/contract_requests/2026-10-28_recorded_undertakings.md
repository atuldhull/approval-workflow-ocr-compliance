# Officer-recorded undertakings and official LoA rules — three-way approval request

Date: 28 October 2026. P2. Status: **approved by Person 1, Person 2 and Person 3 on 2026-10-28**. Shares the `cmp.obligation_created v2` schema, the `cmp_0002` migration and the OpenAPI refresh with the document-validity request of the same date.

## Why this is needed

Obligations were created only from registered letters; an officer could not record an undertaking an institution gave (with its clause, what it asks and the evidence that meets it). The handbook rules `DEPOSIT_15D` and `NO_ADMISSION_AFFIDAVIT_7D` were written but never opened, the LoA still used the demo rule `LOA_DEPOSIT_AFFIDAVIT_15D`, and per-rule `reminders:` were parsed and ignored.

## Exact changes

### API (generated OpenAPI, no hand edits)

New `POST /api/compliance/obligations` (`ObligationRecordIn`): `application_id`, `kind` (any `ObligationKind` except `DOCUMENT_VALIDITY`), `title` (1–200), `evidence_required` (1–500), `source_clause` (up to 32 of letters, digits, space and `. ( ) / -`; optional only with a rule that has its own clause), and exactly one of `due_date` (today or later) or `rule_id` (a rule marked `recordable: true`) with optional `anchor_date` (not in the future, default today). Returns `ObligationOut` (201). Action `compliance.obligation.record`: regional officer (own region), bureau officer, bureau head. Honours `Idempotency-Key`.

### Columns (migration `cmp_0002`)

`cmp.obligation.title`, `evidence_required` (free text, kept in the row, never in an event) and `recorded_by`.

### Event

`cmp.obligation_created v2` (see the document-validity request). No text from the request is put in the event.

### Rules (deadlines.yaml)

- `DEPOSIT_15D`: verified, cl. 2.25(f) p.47, anchored on the LoA issue date (the intimation); reminders 7, 2 and 1 days before (demo assumption). Its penalty tiers (10 % up to 31 May, 20 % up to 31 July, then withdrawal of approval) are shown on the obligation as `penalty_notes` for the competent authority; the system never applies a penalty.
- `AFFIDAVIT3_REMAINING_1M` (new): verified, Affidavit 3 item 5 p.205, one month from the LoA.
- `NO_ADMISSION_AFFIDAVIT_7D`: verified, cl. 1.10(b)(i) p.24, `recordable` (opened when an officer records it).
- `LOA_VALIDITY_2Y`: verified, cl. 1.10(b)(ii) p.25, two academic years counted as 24 months from issue.
- `UNDERTAKING_DUE_DATE` (new): due on the date the undertaking states (`due: on_anchor_date`), source `verified_letter_text`, reminders 7 and 2 days before (demo assumption).
- `LOA_DEPOSIT_AFFIDAVIT_15D`: no longer opened; kept so clocks opened under it still resolve.

A registered LoA now creates DEPOSIT and AFFIDAVIT on `DEPOSIT_15D` and an UNDERTAKING on `AFFIDAVIT3_REMAINING_1M` (three obligations instead of two).

## Impact if refused

Officers keep no record of undertakings outside letters, and the LoA obligations stay on a demo duration although the handbook value is known.
