# Intake item state-change event request

APPROVED: Person 1 explicitly authorized this additional wf schema during task 1.5, alongside submitted v2 and generated OpenAPI. The request is implemented in that task; no ports/types/enums/fakes edit is authorized or required.

The current intake task authorizes a new wf.application_submitted.v2 schema if its payload changes. Application items also change state; ENGINEERING_RULES.md requires a ledger event for each such change. Proposed additional new file: contracts/events/wf/application_item_updated.v1.json.

Exact proposed payload properties (all required, additionalProperties false): application_id UUID, item_key uppercase coded key, state enum PROVIDED/MISSING, document_ref UUID or null. EventIn already supplies actor/time/reason/note envelope fields. No prose or P2 document content. Existing ports/types/enums remain unchanged. FakeLedger already accepts EventIn; tests will assert the real ledger validates the new payload and rolls it back atomically. OpenAPI must be regenerated for the items endpoint and route-plan/DSC responses; no shared fake signature changes are needed.

Requested authorization is only this new wf schema in addition to the explicitly requested submitted v2 schema and generated OpenAPI. Do not apply before authorization.
