# documents (Person 2)

## Phase 1 prototype status

The current work adds byte-signature detection, bounded streaming/hash and
structure-validation primitives, a configurable private local quarantine
adapter, and document metadata/version models with a documents migration.
These are backend foundations only. The HTTP upload and download APIs are **not
enabled** because the repository does not yet provide document-scoped
authorization or an idempotency handler. The referenced frontend
document-review adapter is also absent.

Do not upload real documents. Malware scanning is not configured. The documents
migration defines only `QUARANTINED` and `REJECTED`; no code path can mark a
file available. Database enforcement remains pending PostgreSQL validation.
Any eventual download must wait for scanner and authorization integration. No
OCR, PDF text extraction, fact extraction, review workflow, or deadline
integration is implemented.

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
  Pillow validates allowlisted PNG/JPEG structure and decodes only after the
  configured pixel limit is checked.
- Dependency choice: `pypdf==6.19.0` is used for strict PDF parsing and page
  counts; `Pillow==13.0.0` is used for PNG/JPEG verification and bounded
  decoding. Neither package performs malware scanning or makes a file safe.
- Storage keys include the SHA-256 digest, institution/application scope, and
  a unique staging operation ID. Uploaded filenames never form paths. The
  operation ID prevents one request's rollback from deleting another request's
  object. Database-level hash uniqueness remains scoped to application and
  institution.
- Returning an existing version for an HTTP retry is not wired because the
  repository has no `Idempotency-Key` handling or upload service yet.
- `CasePort` resolves the authoritative application, institution, and region
  for future service use. The documents migration also checks application
  ownership when a document row is inserted or its ownership fields are
  updated. A future workflow that transfers an application's institution
  would need a Person 1-approved composite foreign key on
  `wf.application(id, institution_id)` to preserve that relationship over time;
  no workflow transfer behavior is implemented here.
- No project convention identifies a logical document when changed bytes are
  uploaded. Only the schema's version relationship exists; automatic version
  matching/creation remains blocked until that identity rule is agreed.

The byte-signature check is only an initial filter. Structural validation does
not prove a file is malware-free. Objects remain private in quarantine; no
content-reading API exists. Staging reconciliation removes only unowned
temporary `.part` files and never deletes persisted document objects.
Retention and persisted-document deletion remain unimplemented.

## Later OCR and fact work

- `fact` and `ocr_run` tables and processing remain future work.
- Candidate facts must retain immutable document-version and page/span provenance.
- Facts must remain proposed until the approved human-review workflow confirms
  or corrects them. OCR output must never automatically open a deadline.
- The Indic model's ownership and licence must be confirmed before submission.
