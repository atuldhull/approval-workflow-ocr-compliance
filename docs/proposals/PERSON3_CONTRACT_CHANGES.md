# Proposed contract changes from Person 3

Nothing here is active until all three approve the pull request that contains it (`contracts-approval/designated-approvals` status).
Items are independent and can be approved one by one.

## Status at a glance

| # | What | State |
|---|---|---|
| C1 | OpenAPI snapshot for the platform endpoints | **Committed on `person-3`** (`bcc63e4`) - still needs the three-way approval when the integration PR is opened |
| C2 | `RecipientPort` | Proposed only; nothing in `contracts/` changed |
| C3 | `stage` / `assigned_to` on `ResourceRef` | Proposed only; waits for Person 1's assignment data |
| C4 | `Idempotency-Key` in the snapshot | Waits for Person 1 to apply the idempotency patch |
| C5 | Checkpoint publication endpoint and fields | Patch file only, **not applied**; re-verified to apply cleanly and to make `check_contracts.py` pass |
| C6 | Reports and exports endpoints | Patch file only, **not applied**; applies on top of C5 and `check_contracts.py` passes with both (Python 3.12) |
| C7 | Document audit events (`doc.*` v1) | Schema files only in `docs/proposals/document-events/`, **not copied into `contracts/events/`** |

Any API change after these were prepared means regenerating the snapshot (`python scripts/check_contracts.py
--write`) on the integration branch and reviewing the whole diff again, rather than applying an old patch blindly.

| # | Change | Files | Why | State |
|---|---|---|---|---|
| C1 | OpenAPI snapshot gains 13 new endpoints (auth, notifications, audit, analytics). Existing operations are unchanged. | `contracts/openapi.json` | The snapshot must match the served API, otherwise CI fails | Separate commit on `person-3`, ready to review |
| C2 | `RecipientPort` (resolve a role to an opaque group id; check for a vacancy) and `FakeRecipients` | `contracts/ports.py`, `contracts/fakes.py` | Lets Person 2 address alerts by role without contact details; matches Person 2's interface resolution note | Proposal; implementation exists in `platform/recipients.py` |
| C3 | `ResourceRef` gains `stage: Stage \| None = None` and `assigned_to: tuple[UUID, ...] = ()` | `contracts/types.py`, `fakes.py` | Policy cannot check stage or committee assignment without them | Proposal; policy and Cerbos generator would add the rules in the same PR |
| C5 | OpenAPI snapshot: `POST /api/audit/checkpoints/publish`, and `status` + `publish_error` on `CheckpointOut`. Nothing existing changes. | `contracts/openapi.json` | Recoverable checkpoint publication (docs/AUDIT.md) | **Not applied** - exact patch in `docs/proposals/openapi-checkpoint-publication.patch` (`git apply` it in the integration PR). Until then `check_contracts.py` reports the snapshot as out of date on `person-3`. |
| C4 | `Idempotency-Key` header on application create and submit | `contracts/openapi.json` (after Person 1 applies the patch in `docs/IDEMPOTENCY.md`) | Safe retries | Waiting for Person 1 |

## How to approve and apply C5

C5 adds one endpoint (`POST /api/audit/checkpoints/publish`) and two fields on `CheckpointOut` (`status`,
`publish_error`); nothing existing changes. Checked on 2026-10-24: `git apply --check` passes, and with the patch
applied in a scratch worktree `python scripts/check_contracts.py` prints `contracts ok`.

1. On the integration branch (not `person-3`):
   ```bash
   git apply docs/proposals/openapi-checkpoint-publication.patch
   python scripts/check_contracts.py          # must print: contracts ok
   git add contracts/openapi.json
   git commit -m "Refresh OpenAPI snapshot for checkpoint publication"
   ```
2. If the API changed again since, regenerate instead (`python scripts/check_contracts.py --write`) and review the
   diff - the patch is the reviewed version.
3. Open the PR; the contract-approval status needs both teammates other than the author on the final commit.

Until C5 is applied, `check_contracts.py` fails on `person-3`. That is expected and must not be disabled.

## C6 - reports and exports

C6 adds three endpoints from the Person 3 work pack; nothing existing changes:

- `GET /api/dashboards/pendency?region=` - applications in process by regional office and stage, with the ledger
  head and a snapshot hash so the report can be reproduced (officers and auditor; region-scoped like the dashboard).
- `GET /api/reports/{type}` - the same through the generic report path; `pendency` is the only type so far.
- `POST /api/exports` with `{"format": "ocel2"}` - the event log as OCEL 2.0 (event type, time, role, ruleset and
  case id only; no payloads, notes or personal references), for the bureau and the auditor.

Exact patch: `docs/proposals/openapi-reports-exports.patch`, generated with Python 3.12 (the CI and Docker
version; 3.13 words HTTP 422 differently and the check would fail). Apply it after C5:

```bash
git apply docs/proposals/openapi-checkpoint-publication.patch
git apply docs/proposals/openapi-reports-exports.patch
python scripts/check_contracts.py          # must print: contracts ok (run with Python 3.12)
```

## C7 - document audit events

Person 2's document endpoints need four events. The proposed schemas are in `docs/proposals/document-events/`;
on approval they move to `contracts/events/doc/` unchanged. They carry identifiers, hashes and verdicts only:
no file content, no extracted values, no names or notes (`value_hash` / `note_hash` are sha256 of what stays in
the documents schema, the same pattern as `note_hash` in the ledger).

| Event | Emitted when |
|---|---|
| `doc.document_uploaded` v1 | a new version is stored in quarantine (same transaction as the row) |
| `doc.document_scanned` v1 | the scanner returns `CLEAN` or `INFECTED` for that version |
| `doc.fact_reviewed` v1 | an officer accepts, corrects or rejects a proposed fact |
| `doc.fact_confirmed` v1 | an officer confirms a fact; only confirmed facts may drive deadlines or obligations |

The permissions these endpoints call are already in `policy.py` (and the generated Cerbos policies):
`document.upload` (institution, own records), `document.facts.read` (institution for its own documents, officers,
auditor), `document.fact.review` (scrutiny committee, regional officer), `document.fact.confirm` (officers only;
an institution never confirms its own facts). `document` is region-scoped and, for the committee,
assignment-scoped like a case. Build the `ResourceRef` from the owning application on the server, never from the
request.

Proposed behaviour for the open questions (for all three to agree with the schemas):

- **Versions.** Each upload for an (application, doc_type) adds a version with `version_no` + 1. The current
  version is the newest `CLEAN` one; older versions stay readable and their facts stay attached to them.
- **Duplicate uploads.** The same sha256 for the same application and doc_type returns the existing version
  (200, no new version, no event). A retry with the same `Idempotency-Key` replays the first response. The same
  file for a different application is a separate document.
- **Scanning.** A version is `scan_pending` until the scanner answers; `INFECTED` stays in quarantine and is never
  served. If the scanner is unavailable the version stays `scan_pending` (fail closed) and can be rescanned.
  Locally: `docker compose --profile scanning up -d clamav` (clamd on 127.0.0.1:3310).
- **Fact visibility.** Proposed facts exist only after a `CLEAN` scan and are shown only to roles with
  `document.fact.review`, and only after the extraction transaction has committed (commit before reveal).
  Institutions see confirmed facts and the review status, not raw OCR proposals.

## C2 - RecipientPort

```python
# contracts/ports.py - provided by the platform module
@runtime_checkable
class RecipientPort(Protocol):
    def resolve(self, role: Role, resource: ResourceRef) -> UUID: ...
    def has_members(self, session: Session, recipient_ref: UUID) -> bool: ...

# contracts/fakes.py
class FakeRecipients:
    def __init__(self):
        self.vacant: set[UUID] = set()

    def resolve(self, role, resource) -> UUID:
        return uuid5(NAMESPACE_URL, f"{role}|{resource.region or '*'}|{resource.owner_institution_id or '*'}")

    def has_members(self, session, recipient_ref) -> bool:
        return recipient_ref not in self.vacant
```

Privacy and replay: the group id is deterministic and holds no personal data, so it can sit in events and
outbox rows. Addresses are resolved only at delivery time from erasable `personal_data`. A vacancy found at
alert time lets Person 2 escalate inside the same transaction. A vacancy found only at delivery time ends as a
`NO_RECIPIENT` dead letter, visible on the delivery screen; it is not silently dropped.

## C3 - stage and assignment in ResourceRef

```python
@dataclass(frozen=True)
class ResourceRef:
    type: str
    id: UUID | None = None
    owner_institution_id: UUID | None = None
    region: str | None = None
    stage: Stage | None = None              # new: the case's current stage, when known
    assigned_to: tuple[UUID, ...] = ()      # new: officers assigned to the case, when known
```

Both have defaults, so existing callers keep working. Once approved, `policy.py` would restrict committee actions to
assigned cases and stage-specific actions to the matching stage; the Cerbos policies regenerate automatically.
