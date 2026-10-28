# Document validity records — three-way approval request

Date: 28 October 2026. P2. Status: **approved by Person 1, Person 2 and Person 3 on 2026-10-28**. The event schema, the migration and the regenerated OpenAPI are committed on their own so they can be reviewed, approved or reverted independently of the compliance code.

## Why this is needed

APH 2024-27 cl. 6.17 requires the land lease (a), the occupancy or completion certificate (g), the structural stability certificate (h) and the fire safety certificate (i) to be valid, and cl. 2.1(e) stops extensions of approval once the live lease equals the longest course. Nothing tracked when a confirmed document expires: the `lease_end_date` fact had no consumer, `lease_eoa_stop_year` was never called and the `DOCUMENT_VALIDITY` obligation kind was never created. An obligation row could not name the document it is about or the date it is valid until, and `cmp.obligation_created v1` (`additionalProperties: false`) could not carry them.

## Exact changes

### Event schema: `contracts/events/cmp/obligation_created.v2.json`

All v1 fields unchanged, plus (all required, all nullable):

```text
document_id          uuid       the document (checklist item) a validity record is about
document_version_id  uuid       the version whose date it records
doc_type             pattern ^[A-Z][A-Z0-9_]{0,63}$
valid_until          date       the last day the document is valid
validity_basis       enum DOCUMENT_FACT | OFFICER_RECORDED | APH_PERIOD
eoa_stop_year        pattern ^[0-9]{4}-[0-9]{2}$   land lease only (cl. 2.1(e))
live_lease_ok        boolean    land lease only: the live lease covered the longest course at submission (6.17(a))
```

Every obligation is now written as v2 (letter obligations carry nulls in the new fields), following the repo's convention for `wf.application_submitted`: the v1 schema stays so events already in the ledger still validate and replay. The analytics compliance projection handles both versions.

### Migration `cmp_0002` (compliance chain)

Adds nullable columns to `cmp.obligation`: `document_id` (FK `doc.document`), `document_version_id` (FK `doc.document_version`), `doc_type`, `valid_until`, `validity_basis`, `validity_fact_id` (FK `doc.fact`), `eoa_stop_year`, `live_lease_ok`, plus `title`, `evidence_required` and `recorded_by` used by the recorded-undertakings request of the same date. Checks: `validity_basis` vocabulary; a `DOCUMENT_VALIDITY` row names its document, version, type, date and basis; a `DOCUMENT_FACT` basis names its fact; `eoa_stop_year` format. Partial unique indexes: one validity record per document version, and one not yet met per (application, doc_type). No row is rewritten; downgrade drops them again.

### Generated OpenAPI

Refreshed with `python scripts/check_contracts.py --write` (Python 3.12), no hand edits:

- `ObligationOut` gains `document_id`, `document_version_id`, `document_version_no`, `doc_type`, `valid_until`, `validity_basis`, `validity_state` (`VALID`, `EXPIRING_SOON`, `EXPIRED`, `RENEWAL_UNDER_REVIEW`, `RENEWED`, computed on read from the system clock), `days_left`, `eoa_stop_year`, `live_lease_ok`, `title`, `evidence_required` and `penalty_notes` (all optional with null/empty defaults).
- `GET /api/compliance/obligations` takes an optional `kind` filter.
- New `POST /api/compliance/validity` (`ValidityRecordIn`: `document_version_id`, exactly one of `valid_until` or `issue_date`, optional `max_course_duration_years` 1–10 for a lease) returning `ObligationOut`.

### Policy

Two actions in `backend/app/platform/policy.py`, Cerbos policies regenerated with `scripts/gen_cerbos_policies.py`: `compliance.validity.record` and `compliance.obligation.record`, both for the regional officer (own region only), bureau officer and bureau head.

### Rules (Person 2's deadlines.yaml)

A rule can now fall due on its anchor date (`due: on_anchor_date`) instead of a duration after it; duration rules are unchanged. New rules: `DOCUMENT_EXPIRY` (verified requirement cl. 6.17; due on the document's own expiry date; reminders 90/30/7 days before and the `document_expiry` ladder are demo assumptions) and `STRUCTURAL_STABILITY_VALIDITY` (verified, cl. 6.17(h) p.73: 60 months from issue, used only to work out an expiry). A rule's `reminders:` list is now honoured: one reminder to the clock's owner per offset, in place of the ladder's advance steps; acknowledging such a reminder does not stop the levels at and after the due time.

## Consumers

- Documents: `confirm_fact` calls registered hooks inside its unit of work after `doc.fact_confirmed`; compliance registers `validity.on_fact_confirmed`. The documents module imports nothing from compliance.
- Analytics: the compliance projection folds `cmp.obligation_created` v1 and v2 alike.
- Reports and notifications (Person 3) can read validity from `cmp.obligation` (`kind = 'DOCUMENT_VALIDITY'`, `valid_until`, `doc_type`, `status`) joined to its clock in `dl.deadline` (`status` BREACHED = expired and not renewed), and from `dl.alert` rows of rule `DOCUMENT_EXPIRY`.

## Impact if refused

Without the v2 schema every obligation write fails with `no contract schema` and rolls back; without the migration the validity record cannot name its document or date. Reverting this request means reverting the schema, migration and OpenAPI commit together with the compliance and frontend commits that use them.
