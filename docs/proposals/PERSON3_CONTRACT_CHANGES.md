# Proposed contract changes from Person 3

Nothing here is active until all three approve the pull request that contains it (`contracts-approval/designated-approvals` status).
Items are independent and can be approved one by one.

| # | Change | Files | Why | State |
|---|---|---|---|---|
| C1 | OpenAPI snapshot gains 13 new endpoints (auth, notifications, audit, analytics). Existing operations are unchanged. | `contracts/openapi.json` | The snapshot must match the served API, otherwise CI fails | Separate commit on `person-3`, ready to review |
| C2 | `RecipientPort` (resolve a role to an opaque group id; check for a vacancy) and `FakeRecipients` | `contracts/ports.py`, `contracts/fakes.py` | Lets Person 2 address alerts by role without contact details; matches Person 2's interface resolution note | Proposal; implementation exists in `platform/recipients.py` |
| C3 | `ResourceRef` gains `stage: Stage \| None = None` and `assigned_to: tuple[UUID, ...] = ()` | `contracts/types.py`, `fakes.py` | Policy cannot check stage or committee assignment without them | Proposal; policy and Cerbos generator would add the rules in the same PR |
| C4 | `Idempotency-Key` header on application create and submit | `contracts/openapi.json` (after Person 1 applies the patch in `docs/IDEMPOTENCY.md`) | Safe retries | Waiting for Person 1 |

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
