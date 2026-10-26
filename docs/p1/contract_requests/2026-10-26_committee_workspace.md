# Committee workspace integration request

APPROVED on 26 October 2026: the user explicitly authorized the five policy additions and generated OpenAPI refresh, leaving shared ports/types/enums/fakes unchanged.

The task explicitly requests four wf event schemas. Also request authorization to regenerate contracts/openapi.json for the six requested endpoints, leaving shared ports/types/enums/fakes byte-identical (existing FakeLedger/Notes/Authz interfaces already suffice).

P3 Authz currently rejects unknown committee actions. Exact proposed addition to backend/app/platform/auth.py POLICY, with all existing role/object/region checks retained:

```diff
@@ POLICY
+    "committee.create": {Role.SCRUTINY_COMMITTEE, Role.BUREAU_OFFICER},
+    "committee.task.assign": {Role.SCRUTINY_COMMITTEE, Role.BUREAU_OFFICER},
+    "committee.observation.add": {Role.SCRUTINY_COMMITTEE, Role.BUREAU_OFFICER},
+    "committee.report.add": {Role.SCRUTINY_COMMITTEE, Role.BUREAU_OFFICER},
+    "committee.read": EVERYONE,
```

P1 will additionally require actual membership for every write, caller inclusion on formation, member assignees/authors, and CasePort-derived institution/RO scope. These additions do not change existing case-action roles, auth headers or contract signatures. No P3 database table is written directly.

Schemas (all draft 2020-12 objects, required properties exactly as listed, additionalProperties false):

- committee_formed.v1: application_id UUID, committee_id UUID, type enum SCRUTINY/RESCRUTINY/EVC/SHC/EC/COUNCIL, members nonempty array of strict objects {user_ref UUID, role enum CHAIR/MEMBER/SECRETARY}.
- task_assigned.v1: application_id UUID, committee_id UUID, task_id UUID, title_key pattern ^[A-Z][A-Z0-9_]*$, assignee_user_ref UUID.
- observation_added.v1: application_id UUID, committee_id UUID, task_id UUID, observation_id UUID, author_user_ref UUID, body_note_ref UUID, body_note_hash pattern ^[0-9a-f]{64}$.
- report_version_added.v1: application_id UUID, committee_id UUID, report_version_id UUID, version_no integer >=1, parent_version UUID or null, author_user_ref UUID, content_note_ref UUID, content_note_hash pattern ^[0-9a-f]{64}$.

Raw text stays in NotesPort. OpenAPI includes typed inputs/outputs and report diff metadata based only on hashes/references; NotesPort has no read method, so P1 must not read platform note bodies or claim a textual diff. Fake signatures/implementations need no edits; real-ledger/rollback tests will verify behavior. No other P2/P3 edit is requested.
