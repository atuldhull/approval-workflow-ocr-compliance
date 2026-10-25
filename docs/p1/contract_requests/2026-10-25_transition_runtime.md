# Proposed transition runtime contract changes - TEAM REVIEW NEEDED

## Status after task 1.3

The user explicitly authorized new wf.* event schemas in task 1.3. That task adds transition_applied, stage_entered and stage_exited schemas; the checked-in schemas supersede the illustrative transition payload below. Shared ports/types/enums/fakes remain unchanged. The engine reads its own persisted wf route/transition definitions, so it does not require the proposed RuleSet.workflow_definition field. Conditional timer closes require a trusted workflow-local fact provider; production live-clock inspection remains a P2 integration decision. The remaining proposals below are still unapproved and must not be applied implicitly.

25 October 2026. Request only: **do not apply** without explicit authorization and team agreement. Static validation/template expansion in task 1.1 needs no contract changes. A future engine must not bypass RulesetPort to obtain the workflow definition or emit an unregistered event. This request blocks that runtime wiring/emission, not the independent validator or YAML work.

## What and why

Keep existing Stage, Role, ApplicationStatus and LetterType values. No enums.py change is required: the action vocabulary is locally checked YAML data; no shared Action enum exists. If the team wants one later, agree it separately before consumers import it. Do not add DRAFT or terminal statuses to Stage; these are status nodes.

Propose a backwards-compatible RuleSet field carrying a JSON-compatible validated/expanded workflow definition through existing RulesetPort.get. Do not import P1-local Pydantic classes into contracts. Producers normalize models/edges into plain JSON-compatible data. The precise normalized edge/version format must be agreed before runtime consumers are implemented.

Proposed exact minimal shared-type/fake diff:

```diff
--- a/contracts/types.py
+++ b/contracts/types.py
@@
     banner: str | None = None
+    workflow_definition: dict[str, Any] = field(default_factory=dict)
--- a/contracts/fakes.py
+++ b/contracts/fakes.py
@@
             deadline_rules={}, clocks_on_submit=("AICTE_PROCESSING",),
+            workflow_definition={},
```

The empty default is intentionally "runtime definition not provided", never permission to skip validation or silently allow a transition. When the future engine consumes this field, FakeRulesets needs a valid agreed normalized example and new behavioral tests; the above fake change alone does not prove runtime behavior. Existing ports.py signatures and current HTTP endpoints remain unchanged. No OpenAPI diff is expected for the field alone because RuleSet is not directly an API response model; new action endpoints or exposed grammar fields will need their own OpenAPI update. Run check_contracts.py --write only with authorization and a real API change, then review the generated diff.

## Proposed event schema exact new-file content

Path: `contracts/events/wf/transition_applied.v1.json` (not added by task 1.1). wf.application_submitted keeps its existing schema; every other configured token is proposed wf.transition_applied. Its canonical action excludes aliases.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "wf.transition_applied v1",
  "type": "object",
  "additionalProperties": false,
  "required": ["application_id", "action", "from_state", "to_state", "ruleset_rev"],
  "properties": {
    "application_id": {"type": "string", "format": "uuid"},
    "action": {"type": "string", "enum": ["advance", "record_deficiency", "submit_compliance", "start_rescrutiny", "advance_to_evc", "complete_evc", "advance_to_shc", "issue_loa", "issue_eoa", "issue_lod", "reject", "withdraw", "revert"]},
    "from_state": {"type": "string", "enum": ["SELF_DISCLOSURE", "SCRUTINY", "RESCRUTINY", "DEFICIENT", "EVC", "SHC", "EC", "COUNCIL"]},
    "to_state": {"type": "string", "enum": ["SELF_DISCLOSURE", "SCRUTINY", "RESCRUTINY", "DEFICIENT", "EVC", "SHC", "EC", "COUNCIL", "APPROVED", "REJECTED", "WITHDRAWN"]},
    "ruleset_rev": {"type": "string", "pattern": "^[a-z0-9-]+@[A-Za-z0-9-]+$"}
  }
}
```

Reason codes and note_ref/note_hash remain EventIn envelope fields; no prose or personal values are added to payloads. Whether a generic event suffices for deficiency/letter projection detail needs P3 review before handler implementation. Additional schemas must be separately requested if required. FakeLedger already accepts EventIn objects, but runtime tests must assert new payloads and rollback behavior; schema validity is not proof of projector correctness.

## P2/P3 impact and unresolved runtime decisions

If P2 chooses an inspection port rather than a published read-only view for close.if_live, the exact proposed additional diff is:

```diff
--- a/contracts/ports.py
+++ b/contracts/ports.py
@@
 class DeadlinePort(Protocol):
+    def is_live(self, uow: UnitOfWork, subject: SubjectRef, rule_id: str) -> bool: ...
--- a/contracts/fakes.py
+++ b/contracts/fakes.py
@@
 class FakeDeadlines:
+    def is_live(self, uow, subject: SubjectRef, rule_id: str) -> bool:
+        for operation, recorded_subject, recorded_rule in reversed(self.calls):
+            if (recorded_subject, recorded_rule) == (subject, rule_id) and operation in {"open", "close"}:
+                return operation == "open"
+        return False
```

This optional port addition requires P2's real implementation to inspect/lock its live row in the caller's uow (RUNNING or PAUSED), plus rollback/concurrency tests, before wiring it. It changes protocol conformance, so merely editing the fake is insufficient. No HTTP endpoint is implied. This proposal is not applied here.

- P2: confirm close/pause/resume ledger schemas and emission, actual CompliancePort registration, and safe same-uow lookup for conditional `close.if_live`. Existing DeadlinePort has no inspection method; do not read dl tables directly. An agreed read-only view or separate port request is required before implementing that condition.
- P3: agree guard/reason catalogs, policy, action API concurrency/idempotency, event projector fields and normalized definition shape. No auth policy or middleware is changed here.
- Scope of these proposed diffs: contracts/types.py, contracts/fakes.py, the new event JSON Schema, and optionally contracts/ports.py for P2-approved inspection instead of a view. enums.py stays unchanged. Apply only in one expressly authorized commit, update fakes alongside contracts, run full checks, and mention the contract change in the commit message.
