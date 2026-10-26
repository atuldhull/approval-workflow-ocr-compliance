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
