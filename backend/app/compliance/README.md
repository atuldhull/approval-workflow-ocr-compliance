# compliance (Person 2)

Approval letters, the obligations they create, and the evidence that meets them. Schema `cmp`, migration chain
`backend/migrations/versions/compliance/` (branch label `compliance`). The verification decision lives on the
`evidence` row rather than a separate `verification` table.

- `approval_letter`: an issued LoA/EoA/LoD/LoR/corrigendum with the provenance of its issue date. A
  `PORTAL_EVENT` date needs the letter number (`f_no`); a `CONFIRMED_FACT` date needs an officer-confirmed or
  corrected fact from a document of the same application whose value equals the issue date.
- `obligation`: kind (`UNDERTAKING`, `AFFIDAVIT`, `LETTER_CONDITION`, `DEPOSIT`, `DOCUMENT_VALIDITY`,
  `RECURRING_FILING`), source letter and clause, the source status of its rule, an optional due date from the
  deadlines module, and who met it with which evidence. A `DOCUMENT_VALIDITY` row also names the document version,
  the date it is valid until and where that date comes from (`validity_basis`: `DOCUMENT_FACT`,
  `OFFICER_RECORDED`, `APH_PERIOD`), and for a land lease the EoA stop year and whether the live lease covered the
  longest course at submission. An officer-recorded row carries `title`, `evidence_required` and `recorded_by`.
- `evidence`: one immutable document version offered against one obligation, and the human decision on it.

## What a letter creates (`rules.py`)

| Letter | Obligations / clocks | Rule | Source status |
| --- | --- | --- | --- |
| LoA | DEPOSIT and AFFIDAVIT (security deposit and Affidavit 3), 15 days from issue (cl. 2.25(f), p.47) | `DEPOSIT_15D` | verified |
| LoA | UNDERTAKING: Affidavit 3's remaining requirements, one month from issue (p.205) | `AFFIDAVIT3_REMAINING_1M` | verified |
| LoA | letter validity, two academic years counted as 24 months from issue (cl. 1.10(b)(ii), p.25) | `LOA_VALIDITY_2Y` | verified |
| EoA listing deficiencies | LETTER_CONDITION, six months from issue | `EOA_DEFICIENCY_6M` | verified letter text |

The six-month condition is created only when the registering bureau officer records that the EoA lists
deficiencies; an EoA without them creates nothing. `DEPOSIT_15D` replaced the demo rule `LOA_DEPOSIT_AFFIDAVIT_15D`,
which stays in the ruleset only so clocks opened under it still resolve. Its penalty tiers (10 % up to 31 May,
20 % up to 31 July, then withdrawal; cl. 2.25(f)) are shown on the obligation as `penalty_notes` for the competent
authority; nothing here applies a penalty.

## Officer-recorded obligations

`POST /api/compliance/obligations` (`compliance.obligation.record`: regional officer of the case's region, bureau
officer, bureau head) records an undertaking or another kind with its clause, what it asks (`title`) and the
evidence that meets it, timed either by the due date it states (rule `UNDERTAKING_DUE_DATE`, due on that date) or
by a rule marked `recordable` in deadlines.yaml, counted from `anchor_date` (default today): today only
`NO_ADMISSION_AFFIDAVIT_7D` (cl. 1.10(b)(i), p.24). Events carry no text from the request.

## Document validity (`validity.py`, APH cl. 6.17)

Tracked document types (`rules.VALIDITY_DOCUMENTS`): `LEASE_DEED` and `LAND_DEED` (6.17(a)), `BUILDING_COMPLETION`
(occupancy or completion certificate, 6.17(g)), `STRUCTURAL_STABILITY` (6.17(h)) and `FIRE_NOC` (6.17(i)).

- Opening: when the second officer confirms a fact (four-eyes review) the documents module calls the hook
  `validity.on_fact_confirmed`. A confirmed `valid_until` (any tracked type) or `lease_end_date` (lease types)
  opens a `DOCUMENT_VALIDITY` obligation on rule `DOCUMENT_EXPIRY`, due on that date. A confirmed
  `certificate_issue_date` on a structural stability certificate opens one valid five years from issue
  (`STRUCTURAL_STABILITY_VALIDITY`, 6.17(h), p.73). `POST /api/compliance/validity`
  (`compliance.validity.record`, same roles as above) records the date by hand for a scanned-clean version.
- Lease: `eoa_stop_year` from `lease_eoa_stop_year` (2.1(e), p.28) with the longest course from the request or
  `LEASE_EOA_STOP.max_course_duration_years` (demo assumption, 4), and `live_lease_ok` (6.17(a), p.72) at the
  application's submission date.
- Reminders: `DOCUMENT_EXPIRY` reminds the institution 90, 30 and 7 days before expiry, then the `document_expiry`
  ladder raises the regional officer at expiry, the bureau officer 7 days and the bureau head 30 days after (all
  demo assumptions). The clock is marked BREACHED after the expiry date and the obligation reads `overdue`.
- Renewal: the institution uploads a new version of the same document and submits it as evidence (only a newer
  version of that document is accepted). Officers confirm its expiry in fact review; while the old record is not
  met that date waits. Accepting the evidence meets the old record, closes its clock (late if breached) and opens
  the next record from the new version's confirmed date (or, if none yet, when it is confirmed or recorded).
- Reads: `validity_state` (`VALID`, `EXPIRING_SOON` within the earliest reminder, `EXPIRED`,
  `RENEWAL_UNDER_REVIEW`, `RENEWED`) and `days_left` are computed on read from the system clock.

## Rules

- Acknowledged is not the same as met: an obligation is `MET` only when an officer accepts evidence.
- Evidence must be a document version of the same application that the scanner approved (`AVAILABLE`).
- Verification is by a human officer; `SYSTEM` is refused. A rejection needs a code from `vocab.RejectionReason`
  (proposed list, pending team approval); `OTHER_SEE_NOTE` also needs a note. Note text goes to the note store
  and events carry only its hash.
- `LetterIn.f_no` is stored as `f_no` (the plan's `fr_no` is the same value); events carry only its SHA-256.

## API

| Method | Path | Action |
| --- | --- | --- |
| POST | `/api/compliance/letters` | `compliance.letter.register` |
| GET | `/api/compliance/letters`, `/api/compliance/letters/{id}` | `compliance.read` |
| GET | `/api/compliance/obligations`, `/api/compliance/obligations/{id}` | `compliance.read` |
| POST | `/api/compliance/obligations` | `compliance.obligation.record` |
| POST | `/api/compliance/validity` | `compliance.validity.record` |
| POST | `/api/compliance/obligations/{id}/evidence` | `compliance.evidence.submit` |
| POST | `/api/compliance/evidence/{id}/verify` | `compliance.evidence.verify` |
| GET | `/api/compliance/evidence/{id}/note` | `compliance.evidence.verify`, or `compliance.read` for the owning institution |

POSTs honour an optional `Idempotency-Key`. Lists take `application_id` or `region` (and `status`, `kind`);
institutions see only their own records and regional officers only their region.

## Verification notes

`GET /api/compliance/evidence/{id}/note` returns `{evidence_id, has_note, note, redacted, verified_role,
verified_at}`. Officers who may verify that obligation's evidence (committee under the assignment rule, the
regional officer of its region, bureau officer and head) and the owning institution may read the text. Auditors
are refused (403): `has_note` on the evidence tells them a note exists, and the policy gives them no reason to read
officers' free text, so this stays closed until the team decides otherwise. `NotesPort` has no read method, so the
note is read from the platform note store by `evidence.note_ref` and checked against `evidence.note_hash`; a
mismatch is 409 `NoteIntegrityError` and a redacted note comes back as `note: null, redacted: true`. Events never
carry the text. A `NotesPort.read` would replace the direct read once contracts allow it.

## Demo letters

`python -m app.compliance.demo_seed` (refused unless `DEMO_MODE=true`; safe to rerun) registers three synthetic
LoAs, each on a new DEMO application of a fictional institution, numbered `F.No. DEMO-SEED/<key>/<year>`. Issue
dates come from `ClockPort.now()` (so from the demo clock), never a fixed date: `SOUTH-CURRENT` and
`NORTH-CURRENT` are issued two days ago and their obligations fall due in the future; `SOUTH-OVERDUE` is issued
the rule's duration plus five days ago, so its obligations are five days overdue and the timer worker raises the
reminders, breach and first escalation for the escalation demo. The deadline rules are not changed.
