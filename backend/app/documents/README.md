# documents (Person 2)

## Status

Upload, malware scan, fact extraction, fact review and confirmation are
available over HTTP (see "API" below). There is still **no download
endpoint**: no route returns file bytes. Do not upload real documents; use
synthetic files only. The frontend document-review adapter is not built yet.

Extraction goes through a replaceable `TextEngine` (`extraction.py`). The
default is the local engine in `text_engine.py`: pypdf for PDF text layers,
the Tesseract command line for images and pages without a text layer (see
"Text engine configuration"). `service.configure(engine=...)` installs another
one (tests use fakes). Document migration downgrade/re-upgrade
(doc_0004 to doc_0003 and back) was verified on the disposable test database;
rerun that after document migration changes.

## API

All routes are under `/api`. Authorization uses a `ResourceRef` of type
`document` built on the server from the owning application (`CasePort`):
owner institution and region, never request fields. Regional officers must
match the application's region.

| Method and path | Permission | Notes |
|---|---|---|
| `POST /applications/{id}/documents` (multipart `doc_type`, `file`) | `document.upload` | `Idempotency-Key` required (422 without). 201 new version, 200 when the same bytes already exist for this item. |
| `GET /applications/{id}/documents` | `document.facts.read` | Documents with all versions; `current_version_id` is the newest clean one. |
| `GET /documents?region=&doc_type=` | `document.facts.read` | Across applications. Institutions get their own; regional officers always their own region. |
| `POST /document-versions/{id}/scan` | `document.upload` | Rescan a `scan_pending` version; 503 if the scanner cannot answer. |
| `POST /document-versions/{id}/extract` | `document.fact.review` | Clean versions only. Returns run state and fact ids, after commit. |
| `GET /document-versions/{id}/facts` | `document.facts.read` | What is shown depends on the role, see below. |
| `POST /document-facts/{id}/entry` `{value}` | `document.fact.review` | Commits the reviewer's own reading, then reveals the suggestion. |
| `POST /document-facts/{id}/reveal` | `document.fact.review` | Shows it again, to the same reviewer only. |
| `POST /document-facts/{id}/review` `{decision, value?, note?}` | `document.fact.review` | `ACCEPTED`, `CORRECTED` or `REJECTED`; optional `Idempotency-Key`. |
| `POST /document-facts/{id}/confirm` | `document.fact.confirm` | Optional `Idempotency-Key`. 409 `FourEyesViolation` if the caller reviewed the fact. |

Rules the endpoints follow:

- **Versions.** `doc_type` is the checklist item code (`^[A-Z][A-Z0-9_]*$`).
  One document per (application, doc_type); each upload with new bytes adds
  version n+1. Older versions stay readable with their facts.
- **Duplicates.** The same sha256 for the same application and doc_type returns
  the existing version (200, no new version, no event). The same file for
  another application is a separate document. The same file under a second
  doc_type of the same application is refused with 409, because version hashes
  are unique per application.
- **Idempotency.** The upload fingerprint is `{sha256, filename, doc_type}` plus
  the application id, never raw bytes. A replay returns the first response with
  `Idempotent-Replayed: true`; the retry's own staged copy is deleted.
- **Scanning.** New versions are `QUARANTINED` and `scan_pending`. The scan runs
  after the upload commits. `clean` makes the version `AVAILABLE`; `infected`
  makes it `REJECTED` and it stays in quarantine. If clamd cannot answer, the
  version stays `scan_pending` (fail closed) and can be rescanned. A verdict is
  immutable once recorded (database trigger).
- **Facts.** Extracted only after a clean scan. Committee and regional officers
  see proposals, but not the OCR value until they have entered their own
  reading (type before reveal). Bureau officer/head and auditor see proposed and
  confirmed facts read-only. Institutions see only confirmed values and review
  counts, never raw OCR proposals.
- **Review and confirm** are separate steps. `state` keeps the review outcome
  (`ACCEPTED` is stored as the existing FactState `CONFIRMED`); confirmation
  sets `confirmed_by`/`confirmed_at`. The database also refuses a confirmation
  by the reviewer. Only confirmed facts (`service.confirmed_facts`) may drive
  deadlines or obligations.
- **Events.** `doc.document_uploaded`, `doc.document_scanned`,
  `doc.fact_reviewed` and `doc.fact_confirmed` v1 go through the ledger in the
  same transaction as the change. Payloads hold ids, hashes and verdicts only.
  `value_hash` is the sha256 of the reviewed value (of the empty string for a
  rejection); a review note goes to the note store and only its hash is in the
  event. The schemas in `contracts/events/doc/` still need three-way approval.

## Scanner configuration

`CLAMAV_HOST` (default `127.0.0.1`), `CLAMAV_PORT` (default `3310`) and
`CLAMAV_TIMEOUT_SECONDS` (default `30`). Locally:
`docker compose --profile scanning up -d clamav`. The first start downloads
signatures and can take a few minutes; scans answer 503 until clamd is ready.

## Text engine configuration

`service.engine()` builds the engine on first use from the environment, like
the storage and scanner adapters:

| Variable | Default | Meaning |
|---|---|---|
| `DOCUMENT_TEXT_ENGINE` | `local` | `local` = pypdf + Tesseract; `none` = no engine, extraction answers 503. Anything else is a configuration error (503). |
| `DOCUMENT_TESSERACT_CMD` | `tesseract` | Binary name or path, looked up on `PATH`. |
| `DOCUMENT_OCR_LANGUAGES` | `eng+hin` | Tesseract languages to use; only the installed ones are passed (`--list-langs`). |
| `DOCUMENT_OCR_TIMEOUT_SECONDS` | `60` | Per image; a timeout fails the run with `TIMEOUT`. |

How a clean version is read:

- **PDF page with a text layer:** `pypdf` `extract_text()`, page by page. One
  token per word; confidence `1`, because the text was read, not recognised.
- **Image, or PDF page without a text layer:** its embedded images go to
  `tesseract stdin stdout -l eng+hin tsv`. Word confidences are Tesseract's
  own, scaled to 0..1, and are **uncalibrated** (the run's `model_version` says
  so, e.g. `pypdf 6.19.0; tesseract 5.3.4; confidence uncalibrated`). No
  threshold uses them.
- **Tesseract missing** (binary not found, or none of the configured languages
  installed) while a page needs it: the run is `FAILED` with
  `ADAPTER_UNAVAILABLE` and can be retried with another extract call once
  Tesseract is there. Such a run is never recorded as an empty success. A
  mixed PDF fails as a whole; no partial batch of facts is kept.
- Other failures: unreadable PDF or unsupported type `INPUT_REJECTED`,
  Tesseract error or unparseable output `PROCESSING_FAILED`, timeout `TIMEOUT`.
- Token scripts come from `ocr.detect_script`; the candidate extractor then
  converts Indic digits to ASCII and normalises dates exactly as before. Every
  value is a `PROPOSED` fact until a reviewer enters, reviews and confirms it.

The backend image installs `tesseract-ocr`, `tesseract-ocr-eng` and
`tesseract-ocr-hin`. Running the backend outside Docker without Tesseract
still reads text-layer PDFs; scans then fail as above. Nothing is sent off the
machine. Accuracy on real AICTE documents has not been measured.

## Prototype configuration

- `DOCUMENT_STORAGE_DIR` must be an absolute path outside this repository and
  any served/static directory. There is no default storage path. Set
  `DOCUMENT_SERVED_ROOTS` to any additional served/static roots outside this
  repository, separated by the OS path separator. The adapter does not inspect
  Windows ACLs; on Windows the configured directory must inherit an ACL
  restricted to the service user.
- `DOCUMENT_MAX_UPLOAD_BYTES` defaults to `10485760` (10 MiB). It may be
  configured lower, but not higher than the approved 10 MiB cap.
- `DOCUMENT_MAX_PDF_PAGES` and `DOCUMENT_MAX_IMAGE_PIXELS` must be configured
  as positive integers before uploads can be enabled. There are no approved
  page or pixel defaults. `pypdf` validates strict PDF structure and page count;
  Pillow applies the configured pixel limit as `Image.MAX_IMAGE_PIXELS` before
  opening or decoding images, and also checks dimensions explicitly. Its
  decompression-bomb warnings and errors are rejected. The pixel limit has no
  repository default and must be explicitly configured.
- Dependency choice: `pypdf==6.19.0` is used for strict PDF parsing and page
  counts; `Pillow==13.0.0` is used for PNG/JPEG verification and bounded
  decoding. Neither package performs malware scanning or makes a file safe.
- Storage keys include the SHA-256 digest, institution/application scope, and
  a unique staging operation ID. Uploaded filenames never form paths. The
  operation ID prevents one request's rollback from deleting another request's
  object. Database-level hash uniqueness remains scoped to application and
  institution.
- `CasePort` resolves the authoritative application, institution, and region
  for every document request. The documents migration also checks application
  ownership when a document row is inserted or its ownership fields are
  updated. A future workflow that transfers an application's institution
  would need a Person 1-approved composite foreign key on
  `wf.application(id, institution_id)` to preserve that relationship over time;
  no workflow transfer behavior is implemented here.
- A logical document is identified by (application, doc_type). Documents
  inserted before doc_0004 have no doc_type and are not versioned by the API.

The byte-signature check is only an initial filter. Structural validation does
not prove a file is malware-free; that is the scanner's job. Objects remain
private in quarantine; `open_private()` is used only by the scanner and the
text engine. Staging reconciliation removes only unowned
temporary `.part` files and never deletes persisted document objects.

## Prototype history protection

Ordinary `DELETE` and `TRUNCATE` are rejected for `doc.document`,
`doc.document_version`, `doc.ocr_run`, and `doc.fact`. OCR runs and facts are
audit history; incorrect results should be rejected or superseded rather than
deleted. This is a prototype safeguard, not a permanent-retention declaration
or an erasure mechanism. Any future erasure process must be designed and
approved separately.

`TRUNCATE` is permitted only inside a transaction where the test harness has
set the transaction-local PostgreSQL setting `awoc.test_reset` to exactly
`on`. The shared test fixture must set this only around its controlled test
reset; the application does not set it. Coordinating that fixture change is
still required before client-fixture tests can reset document tables. Database
owners and superusers can disable or alter triggers, so these guards prevent
ordinary application mistakes and are not a substitute for appropriate
database permissions.

## Later OCR and fact work

- The replaceable `OcrAdapter` interface has no configured production adapter;
  a `TextEngine` built on it can be installed for extraction instead of the
  local engine. Adapters must declare script support; routing uses explicit hints or a
  homogeneous detected script and fails closed for mixed or unsupported text.
- OCR runs have queued/running/succeeded/failed states. A retry is a new linked
  attempt and is allowed only after failure. Retry creation is idempotent per
  failed attempt, with a database uniqueness guard. Failures use stable codes
  and do not store raw exception text. The database rejects a transition to RUNNING
  unless the document version is `AVAILABLE`, which only a clean scan sets.
- Facts retain the document-version ID, OCR-run ID, page, source-text span,
  original text, normalized candidate, confidence, script, and normalization
  outcome. Database triggers require a successful run and protect source
  provenance and review ordering.
- All OCR facts begin as `PROPOSED`; confidence is recorded but no threshold is
  invented. Ambiguous dates have no normalized value. Conflicting candidates
  are marked but remain proposed. Only a human review can confirm, correct, or
  reject a fact.
- The backend review helper records the reviewer's own value before it returns
  the OCR suggestion; the entry endpoint commits that value before revealing.
- Date normalization accepts calendar-unambiguous numeric forms, retains the
  original string, and leaves multiple valid interpretations ambiguous. It
  creates candidate values only; legal deadlines and date conventions remain
  outside this module.
- The local engine uses Tesseract (Apache-2.0) and pypdf only. A dedicated
  Indic model still needs ownership/licensing and resource limits agreed; the
  supplied Indic model is not bundled or invoked. External translation is not
  integrated. The local engine does not go through `AdapterRouter`: one
  Tesseract call reads `eng+hin` together, and each token's script is
  detected afterwards.
