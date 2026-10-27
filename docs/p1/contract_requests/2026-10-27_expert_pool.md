# Expert pool contracts and P3 permission request

Status: the user explicitly approved both the proposed contract changes and the four P3 permission additions on 27 October 2026. Implementation proceeds under those approvals.

## Why

The requested three audit events require schemas; four new endpoints require regenerated OpenAPI and dedicated permissions (P3 currently rejects unknown actions). The pure eligibility core needs the pinned YAML expert policy through the existing RulesetPort, rather than importing workflow internals or reading another schema. All storage already exists except an optional opaque personal_ref column in evc.expert (P1 migration).

AGENTS: "If a task seems to need a change in contracts/: STOP, do not edit it, and write the proposed change"; platform/auth.py also requires approval.

## Exact shared value-type addition

Append this defaulted field to RuleSet in contracts/types.py (no existing positional argument or required field changes):

```diff
     banner: str | None = None
+    expert_pool: dict[str, Any] = field(default_factory=dict)
```

No ports.py or enums.py change. Workflow registry supplies the validated expert_pool YAML mapping and overlays inherit it. Empty defaults preserve existing callers; eligibility fails explicitly if policy is unavailable, rather than silently choosing a region rule.

## Exact fake changes

Allow deterministic personal references in tests without changing default fake behavior:

```diff
 class FakePersonalData:
-    def __init__(self):
+    def __init__(self, *, reference_factory=uuid4):
         self.rows: dict[UUID, dict[str, Any]] = {}
+        self.reference_factory = reference_factory

     def store(self, uow, data: dict[str, Any], purpose: str) -> UUID:
-        ref = uuid4()
+        ref = self.reference_factory()
         self.rows[ref] = data
         return ref
```

Existing FakeRulesets uses the new empty default; tests needing policy supply RuleSet.expert_pool explicitly. No new port/fake registration in scripts/check_contracts.py is needed.

## Exact new schemas

Files are contracts/events/evc/<name>.v1.json. Each schema is the JSON below (formatting may be expanded). Event type is evc.<name>, event_version=1. No names, emails, phones or remarks appear in payloads.

### expert_registered.v1.json

```json
{"$schema":"https://json-schema.org/draft/2020-12/schema","type":"object","additionalProperties":false,"required":["expert_id","user_ref","region","expertise_tags","active","personal_ref"],"properties":{"expert_id":{"type":"string","format":"uuid"},"user_ref":{"type":"string","format":"uuid"},"region":{"type":"string","pattern":"^[A-Z][A-Z0-9_]*$"},"expertise_tags":{"type":"array","uniqueItems":true,"items":{"type":"string","pattern":"^[A-Z][A-Z0-9_]*$"}},"active":{"type":"boolean"},"personal_ref":{"type":["string","null"],"format":"uuid"}}}
```

### availability_set.v1.json

```json
{"$schema":"https://json-schema.org/draft/2020-12/schema","type":"object","additionalProperties":false,"required":["expert_id","changes"],"properties":{"expert_id":{"type":"string","format":"uuid"},"changes":{"type":"array","minItems":1,"maxItems":732,"items":{"type":"object","additionalProperties":false,"required":["date","slot_part","available"],"properties":{"date":{"type":"string","format":"date"},"slot_part":{"enum":["AM","PM"]},"available":{"type":"boolean"}}}}}}
```

### coi_recorded.v1.json

```json
{"$schema":"https://json-schema.org/draft/2020-12/schema","type":"object","additionalProperties":false,"required":["expert_id","institution_ref","source","reason_code"],"properties":{"expert_id":{"type":"string","format":"uuid"},"institution_ref":{"type":"string","format":"uuid"},"source":{"enum":["INSTITUTION_LINK","PRIOR_ENGAGEMENT","RECUSAL"]},"reason_code":{"enum":["INSTITUTION_LINK","PRIOR_ENGAGEMENT","RECUSAL"]}},"oneOf":[{"properties":{"source":{"const":"INSTITUTION_LINK"},"reason_code":{"const":"INSTITUTION_LINK"}}},{"properties":{"source":{"const":"PRIOR_ENGAGEMENT"},"reason_code":{"const":"PRIOR_ENGAGEMENT"}}},{"properties":{"source":{"const":"RECUSAL"},"reason_code":{"const":"RECUSAL"}}}]}
```

## Exact P3 auth permission additions

Add only these entries to POLICY in backend/app/platform/auth.py; existing policy logic and entries remain unchanged:

```python
"evc.expert.register": {Role.RO_OFFICER, Role.BUREAU_OFFICER, Role.BUREAU_HEAD},
"evc.availability.set": {Role.RO_OFFICER, Role.BUREAU_OFFICER, Role.BUREAU_HEAD},
"evc.coi.record": {Role.RO_OFFICER, Role.BUREAU_OFFICER, Role.BUREAU_HEAD},
"evc.expert.read": {Role.RO_OFFICER, Role.BUREAU_OFFICER, Role.BUREAU_HEAD, Role.SCRUTINY_COMMITTEE, Role.AUDITOR},
```

P1 additionally enforces RO expert-region scope, including before list totals/pagination, since current P3 object-region enforcement covers application resources only. Unknown user_ref validation remains a P3 integration follow-up: no user-directory lookup port exists, and no user master is copied or queried directly.

## OpenAPI impact

Generate contracts/openapi.json using python scripts/check_contracts.py --write after implementation. It will add POST /api/evc/experts, POST /api/evc/experts/{id}/availability, POST /api/evc/coi and GET /api/evc/experts, with typed bodies, filters, coded errors and response fields. Optional personal input is routed exclusively through PersonalDataPort; responses expose personal_ref only. The existing queue contract is retained. No hand editing OpenAPI, P2 deadline changes, or scripts changes are proposed.

## Delivery

Keep shared types, fakes, schemas and generated OpenAPI together in the explicitly approved contract commit, mention approval in its message, and run full tests/contracts/migration checks before pushing person-1. The YAML region/COI policy remains DEMO ASSUMPTION; existing r1 checksum protection is retained with fresh disposable demo test databases.
