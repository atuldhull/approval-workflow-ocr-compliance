# Letter issuance contract request — TEAM REVIEW NEEDED

Status: proposed only. The user explicitly instructed: if LetterIn lacks a needed field, write a contract request and do not edit contracts/. This request records that blocker; letter issuance has not been enabled and no shared contract or production code is changed.

## What is missing and why

`contracts/types.py:LetterIn` contains application_id, institution_id, letter_type, academic_year, issue_date, issue_date_source, lists_deficiencies and optional f_no/issue_date_fact_id/document_version_id. It has **no ruleset_rev**. The task requires the pinned case revision to reach P2 through `CompliancePort.register_letter(uow, LetterIn(...))`, whose signature has no separate ruleset argument. EventIn.ruleset_rev does not transmit that information to P2. Do not hide it in f_no, a document/fact reference, an ad-hoc attribute on the frozen dataclass, or another owner's table.

The source field is currently an unconstrained `str` documented as PORTAL_EVENT / CONFIRMED_FACT. Agree explicit CLOCK / SIMULATED semantics with P2 before introducing them; a clock fallback must not masquerade as a confirmed fact or portal event. Existing LetterType already includes CORRIGENDUM, so no LetterType enum addition is required.

## Exact proposed shared type and fake diff

```diff
--- a/contracts/types.py
+++ b/contracts/types.py
@@ class LetterIn:
-    issue_date_source: str  # PORTAL_EVENT | CONFIRMED_FACT
+    issue_date_source: str  # PORTAL_EVENT | CONFIRMED_FACT | CLOCK | SIMULATED
     lists_deficiencies: bool
+    ruleset_rev: str  # required pinned key, e.g. aph-2024-27@r1
     f_no: str | None = None
--- a/contracts/fakes.py
+++ b/contracts/fakes.py
@@ class FakeCompliance:
     def register_letter(self, uow, letter: LetterIn) -> UUID:
+        if not letter.ruleset_rev:
+            raise ValueError("ruleset_rev is required")
+        if letter.issue_date_source not in {"PORTAL_EVENT", "CONFIRMED_FACT", "CLOCK", "SIMULATED"}:
+            raise ValueError("unsupported issue_date_source")
         self.letters.append(letter)
         return uuid4()
```

This deliberately makes ruleset_rev required. Repository search finds one LetterIn constructor, in workflow/engine.py; update it in the same authorized implementation. External P2 callers/consumers must also agree to the new required field. CompliancePort's method signature stays unchanged. Update FakeCompliance alongside the shared type, then cover exact argument forwarding with the transactional test adapter; the shared in-memory fake alone does not prove rollback.

## Exact proposed issuance-event schema

Do not add this file until contract edits are explicitly authorized. Existing wf event schemas stay unchanged.

```diff
--- /dev/null
+++ b/contracts/events/wf/letter_issuance_triggered.v1.json
@@
+{
+  "$schema": "https://json-schema.org/draft/2020-12/schema",
+  "type": "object",
+  "additionalProperties": false,
+  "required": ["application_id", "letter_id", "letter_type", "lists_deficiencies", "issue_date", "issue_date_source", "inbound_event_ref", "ruleset_rev", "simulation_status"],
+  "properties": {
+    "application_id": {"type": "string", "format": "uuid"},
+    "letter_id": {"type": "string", "format": "uuid"},
+    "letter_type": {"type": "string", "enum": ["LOA", "EOA", "LOD", "CORRIGENDUM"]},
+    "lists_deficiencies": {"type": "boolean"},
+    "issue_date": {"type": "string", "format": "date"},
+    "issue_date_source": {"type": "string", "enum": ["PORTAL_EVENT", "CLOCK", "SIMULATED"]},
+    "inbound_event_ref": {"anyOf": [{"type": "string", "format": "uuid"}, {"type": "null"}]},
+    "ruleset_rev": {"type": "string", "pattern": "^[a-z0-9-]+@[A-Za-z0-9-]+$"},
+    "simulation_status": {"type": "string", "enum": ["SIMULATED", "NOT_SIMULATED"]}
+  }
+}
```

The event records the ID actually returned by P2. Mock portal events retain their inbound_event_ref and carry SIMULATED provenance; the reference distinguishes that origin from a simulated clock fallback. Any real clock fallback uses CLOCK. No raw text, personal display data or copied approval-letter content is emitted. The event envelope also retains the pinned ruleset and actor.

## P1 implementation after approval

1. Keep the authorisation, decision, concurrency and last-applicable-stage guards. Resolve the date from a trusted P1 inbound-event record when supplied, validating its case/type; otherwise use ClockPort.now().date() in the team-agreed civil timezone. Never treat client-provided provenance as trusted. Confirm IST versus UTC date rollover with P2; do not invent an APH date rule.
2. No inbound_event model exists today. Add only the necessary P1 provenance/idempotency record and a trusted ingestion boundary, or an agreed provider; do not fabricate a portal event. Derive mock labels from trusted simulation context. Date/provenance fields in the current local LetterPayload and guard-fact confirmation need an explicit compatibility plan.
3. Enable the hook by default only with a clean missing-dependency failure; never register FakeCompliance in production. P2's compliance package is currently a placeholder with no real registration. P1 must not create/write cmp.approval_letter or open the EOA_DEFICIENCY_6M clock itself. P2 confirms conditions and owns subsequent obligations.
4. Add a minimal wf issuance receipt keyed uniquely by (application_id, letter_type), containing only P2's returned reference and the case pin. It is a duplicate-prevention record, not a copy of the letter. Lock the case before checking/registering; receipt, transition, timers and events commit atomically. Do not inspect P2 tables or P3 ledger internals for duplicate detection.
5. Add an EOA-with-deficiencies YAML variant guarded by independently confirmed letter/decision data. Only EOA may have lists_deficiencies=true. Preserve all 22 route stage lists. Existing open-items guards must not be silently removed: decide separately how officer-confirmed letter conditions relate to unresolved workflow items.
6. Corrigendum currently has neither an action/route template nor a P3 permission. Ordinary actions are correctly refused on terminal cases. Agree a data-driven amendment rule preserving the existing decision, requiring an earlier issued-letter reference, and avoiding reopening stages/timers. If a new generic transition schema is needed, version it rather than silently broadening transition_applied.v1's action/from-state enums. Do not invent a terminal-reopening policy to make the test pass.

## OpenAPI, fakes and team impact

- P1 local action/result schemas need date/provenance/returned-letter metadata and corrigendum support. Regenerate `contracts/openapi.json` with `python scripts/check_contracts.py --write` only in the separately authorized implementation; review existing request-field compatibility. LetterIn itself is not an HTTP schema, so adding its field alone does not warrant an invented public endpoint.
- P2 must consume and retain the pinned ruleset/source correctly, confirm CLOCK/SIMULATED handling, implement the real port transactionally, and preserve responsibility for letters/conditions/obligations. No P2 source edit is proposed here.
- P3 must approve the narrow prospective `case.corrigendum` policy (proposed BUREAU_OFFICER), simulation metadata and the new event/projector fields. No P3 runtime edit is performed or authorized by this request.
- After explicit shared-contract authorization, edit types.py and fakes.py together, add the approved event schema, refresh OpenAPI if the API changes, run full tests/contracts/heads, and mention the contract change in the commit message.

## Required acceptance evidence after approval

Exact LetterIn arguments for LOA, EOA, LOD and CORRIGENDUM; EOA true/false deficiency variants and rejection of true for other types; pinned ruleset forwarding; valid/foreign/missing inbound references; trusted mock labels; logical-clock fallback including a civil-date boundary; duplicate same-case/type rejection (including concurrent calls); P2 register failure and post-register ledger failure rolling back receipts/state/visits/timers/events plus transactional fake effects; no P2 letter row written by P1. These tests have not been implemented or claimed as passing in this request-only task.
