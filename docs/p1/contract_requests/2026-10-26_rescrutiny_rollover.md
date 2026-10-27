# Re-Scrutiny rollover contract request

APPROVED: Person 1 explicitly authorized this schema and OpenAPI regeneration on 26 October 2026, leaving shared ports/types/enums/fakes unchanged.

ENGINEERING_RULES.md requires explicit authorization before contracts edits. This task needs the generated OpenAPI updated for GET /cases/{id}/rescrutiny and lineage/closure metadata. Rejected rounds must be superseded without falsely emitting an all-accepted deficiency_closed event. Propose the following exact additional event schema; existing event schemas remain unchanged.

```diff
--- /dev/null
+++ b/contracts/events/wf/deficiency_superseded.v1.json
@@
+{
+  "$schema": "https://json-schema.org/draft/2020-12/schema",
+  "type": "object",
+  "additionalProperties": false,
+  "required": ["application_id", "deficiency_id", "next_deficiency_id"],
+  "properties": {
+    "application_id": {"type": "string", "format": "uuid"},
+    "deficiency_id": {"type": "string", "format": "uuid"},
+    "next_deficiency_id": {"type": "string", "format": "uuid"}
+  }
+}
```

Lineage is persisted in wf.deficiency_item.previous_item_id and exposed by the API; the existing recorded/responded/decided events retain item IDs. Impact on contracts/fakes.py: none; FakeLedger already accepts EventIn. Request authorization to leave ports/types/enums/fakes byte-identical and regenerate only openapi.json plus this wf schema. No P2/P3 runtime or deadline YAML edit is needed.
