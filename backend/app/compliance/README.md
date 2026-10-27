# compliance (Person 2)

Approval letters, the obligations they create, and the evidence that meets them. Schema `cmp`, migration chain
`backend/migrations/versions/compliance/` (branch label `compliance`). The verification decision lives on the
`evidence` row rather than a separate `verification` table.

- `approval_letter`: an issued LoA/EoA/LoD/LoR/corrigendum with the provenance of its issue date. A
  `PORTAL_EVENT` date needs the letter number (`f_no`); a `CONFIRMED_FACT` date needs an officer-confirmed or
  corrected fact from a document of the same application whose value equals the issue date.
- `obligation`: kind (`UNDERTAKING`, `AFFIDAVIT`, `LETTER_CONDITION`, `DEPOSIT`, `DOCUMENT_VALIDITY`,
  `RECURRING_FILING`), source letter and clause, the source status of its rule, an optional due date from the
  deadlines module, and who met it with which evidence.
- `evidence`: one immutable document version offered against one obligation, and the human decision on it.

## What a letter creates (`rules.py`)

| Letter | Obligations / clocks | Rule | Source status |
| --- | --- | --- | --- |
| LoA | DEPOSIT and AFFIDAVIT, 15 days from issue (cl. 1.12) | `LOA_DEPOSIT_AFFIDAVIT_15D` | demo assumption |
| LoA | letter validity, 24 months from issue | `LOA_VALIDITY_2Y` | demo assumption |
| EoA listing deficiencies | LETTER_CONDITION, six months from issue | `EOA_DEFICIENCY_6M` | verified letter text |

The six-month condition is created only when the registering bureau officer records that the EoA lists
deficiencies; an EoA without them creates nothing. `NO_ADMISSION_AFFIDAVIT_7D` (cl. 1.10(b)(i)) is in the
ruleset but is not opened yet: nothing records the "no admissions" fact.

## Rules

- Acknowledged is not the same as met: an obligation is `MET` only when an officer accepts evidence.
- Evidence must be a document version of the same application that the scanner approved (`AVAILABLE`). The
  documents schema has no such state yet, so submission stays closed until the scanner integration lands.
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
| POST | `/api/compliance/obligations/{id}/evidence` | `compliance.evidence.submit` |
| POST | `/api/compliance/evidence/{id}/verify` | `compliance.evidence.verify` |

POSTs honour an optional `Idempotency-Key`. Lists take `application_id` or `region`; institutions see only their
own records and regional officers only their region.
