# Deficiency review event — approved

The user explicitly approved the additional wf.deficiency_item_decided.v1 schema and OpenAPI regeneration, leaving shared ports/types/enums/fakes unchanged. The officer review endpoint was also explicitly approved.

The task authorizes four deficiency wf schemas. The separately approved officer review endpoint also changes each item's decision state, which AGENTS.md hard rule 6 requires us to record. Add one further schema and regenerate OpenAPI for the requested APIs. No shared port, enum, type or fake signature needs changing; existing FakeLedger already accepts EventIn, so contracts/fakes.py should remain byte-identical.

Exact additional file diff:

```diff
--- /dev/null
+++ b/contracts/events/wf/deficiency_item_decided.v1.json
@@
+{
+  "$schema": "https://json-schema.org/draft/2020-12/schema",
+  "type": "object",
+  "additionalProperties": false,
+  "required": ["application_id", "deficiency_id", "item_id", "state", "decided_by"],
+  "properties": {
+    "application_id": {"type": "string", "format": "uuid"},
+    "deficiency_id": {"type": "string", "format": "uuid"},
+    "item_id": {"type": "string", "format": "uuid"},
+    "state": {"type": "string", "enum": ["ACCEPTED", "REJECTED"]},
+    "decided_by": {"type": "string", "format": "uuid"}
+  }
+}
```

Reason_code and protected remarks use the existing EventIn envelope (note_ref/note_hash), not payload prose. Impact on fakes.py: none; positive/negative tests use the real ledger plus existing fake adapters. Impact on openapi.json: regenerate with python scripts/check_contracts.py --write for deficiency reads/review and structured action payload fields. No P2/P3 runtime or deadline YAML edits are requested.
