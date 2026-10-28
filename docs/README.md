# Documentation index

Start with the [project README](../README.md). Everything below is plain Markdown in this repository; owners are
listed in [OWNERSHIP.md](OWNERSHIP.md).

## Design and operation

- [ARCHITECTURE.md](ARCHITECTURE.md) — modular monolith, ports between modules, rulesets, audit ledger, demo switches.
- [OWNERSHIP.md](OWNERSHIP.md) — owner of every folder and database schema.
- [TEAM_WORKFLOW.md](TEAM_WORKFLOW.md) — branches, pull requests and checks the team works with.
- [CONTRACT_APPROVAL.md](CONTRACT_APPROVAL.md) — why changes under `contracts/` need all three members, and how CI enforces it.
- [SECURITY.md](SECURITY.md) — sign-in (demo, Keycloak), Cerbos policies, roles and scopes, demo-only settings.
- [AUDIT.md](AUDIT.md) — hash chain, signed checkpoints, witness, replay and what each layer can detect.
- [IDEMPOTENCY.md](IDEMPOTENCY.md) — `Idempotency-Key` semantics for retried commands.
- [RULES_EVIDENCE.md](RULES_EVIDENCE.md) — every timer, route and rule: APH clause and page, demo assumption, or not built.
- [NOTIFICATIONS.md](NOTIFICATIONS.md) — notifier worker, channels, retries, dead letters and delivery guarantees.
- [screenshots/](screenshots/) — screenshots used in the project README (synthetic data).

## Module notes

- [backend/app/evc/README.md](../backend/app/evc/README.md) — EVC queue, expert pool, selector, scheduling (Person 1).
- [backend/app/documents/README.md](../backend/app/documents/README.md) — upload, scanning, text extraction, fact review (Person 2).
- [backend/app/documents/FIELD_CANDIDATE_SPEC_TEMPLATE.md](../backend/app/documents/FIELD_CANDIDATE_SPEC_TEMPLATE.md) — field-candidate extraction spec v1 (Person 2).
- [backend/app/compliance/README.md](../backend/app/compliance/README.md) — letters, obligations and evidence (Person 2).
- [backend/app/analytics/README.md](../backend/app/analytics/README.md) — projections, dashboards, scorecard (Person 3).
- [calendars/README.md](../calendars/README.md) — versioned working-day calendars (Person 2).
- [generator/documents/README.md](../generator/documents/README.md) — synthetic document and OCR fixtures (Person 2).
- [infra/keycloak/README.md](../infra/keycloak/README.md) — local Keycloak realm and the demo accounts.

## Frontend

- [frontend/DESIGN.md](../frontend/DESIGN.md) — design system: colour, type, states and wording rules.
- [frontend/MOTION.md](../frontend/MOTION.md) — motion and rendering rules.
- [frontend/SEMANTIC_MOTION_MAP.md](../frontend/SEMANTIC_MOTION_MAP.md) — what each figure encodes and where its data comes from.
- [frontend/REDESIGN_PLAN.md](../frontend/REDESIGN_PLAN.md) — plan for the workspace redesign.
- [frontend/REDESIGN_REPORT.md](../frontend/REDESIGN_REPORT.md) — what the redesign changed and how it was checked.
- [frontend/WORKSPACE_REPORT.md](../frontend/WORKSPACE_REPORT.md) — workspace screens per role, verification and backend gaps met.
- [frontend/SHOWCASE_REFERENCE.md](../frontend/SHOWCASE_REFERENCE.md) — reference study and art direction for the public showcase.
- [frontend/SHOWCASE_REPORT.md](../frontend/SHOWCASE_REPORT.md) — how the showcase was built and checked.

## Handoffs between members

- [handoffs/INTEGRATION_MATRIX.md](handoffs/INTEGRATION_MATRIX.md) — state of every point where the platform meets the other modules.
- [handoffs/PERSON1_FROM_P3.md](handoffs/PERSON1_FROM_P3.md) — requests from Person 3 to Person 1.
- [handoffs/PERSON2_FROM_P3.md](handoffs/PERSON2_FROM_P3.md) — requests from Person 3 to Person 2.
- [handoffs/APH_CONFORMANCE_PROPOSALS.md](handoffs/APH_CONFORMANCE_PROPOSALS.md) — where the prototype differs from the APH, with proposals.
- [handoffs/AICTE_INTEGRATION_READINESS.md](handoffs/AICTE_INTEGRATION_READINESS.md) — what connecting to AICTE systems would need.

## Contract proposals

- [proposals/PERSON3_CONTRACT_CHANGES.md](proposals/PERSON3_CONTRACT_CHANGES.md) — contract changes proposed by Person 3, each approved separately.
- [proposals/alert-events/README.md](proposals/alert-events/README.md) — deadline alert event schemas (v1) for review.
- [proposals/compliance-events/](proposals/compliance-events/) — compliance event schemas (letter registered, obligation created, evidence submitted and verified).
- [proposals/document-events/](proposals/document-events/) — document event schemas (uploaded, scanned, fact reviewed and confirmed).
- [proposals/openapi-checkpoint-publication.patch](proposals/openapi-checkpoint-publication.patch) — OpenAPI change for checkpoint publication.
- [proposals/openapi-reports-exports.patch](proposals/openapi-reports-exports.patch) — OpenAPI change for reports and exports.

## Person 2

- [P2_48_HOUR_EXECUTION_PLAN.md](P2_48_HOUR_EXECUTION_PLAN.md) — Person 2's execution plan and status for documents, compliance and deadlines.

## Person 1 (`docs/p1/`)

- [p1/ENGINEERING_RULES.md](p1/ENGINEERING_RULES.md) — what Person 1 owns and the hard rules for workflow and EVC code.
- [p1/RUN.md](p1/RUN.md) — generator and answer-key verification, one command per seed.
- [p1/ASSUMPTIONS.md](p1/ASSUMPTIONS.md) — every demo assumption in the workflow and EVC modules, with its code.
- [p1/00_repo_audit.md](p1/00_repo_audit.md) — repository audit at the start of Person 1's work (24 October 2026).
- [p1/week1_status.md](p1/week1_status.md) — week 1 integration checkpoint: submission to ledger, end to end.
- [p1/acceptance_report.md](p1/acceptance_report.md) — acceptance evidence for each Person 1 task.
- [p1/generator_report.md](p1/generator_report.md) — generator and answer-key verification results.
- [p1/category_mix.md](p1/category_mix.md) — demo category mix used by the scale generator.
- [p1/selector_report.md](p1/selector_report.md) — the simulated panel selector and its limits.
- [p1/edf_report.md](p1/edf_report.md) — earliest-deadline-first scheduling baseline and its metrics.
- [p1/answer_key_schema.md](p1/answer_key_schema.md) — per-seed answer key format ([schema](p1/answer_key.schema.json), [example](p1/answer_key_example.json)); routing expectations in [expected_routes.csv](p1/expected_routes.csv).
- [p1/wireframes.md](p1/wireframes.md) — early low-fidelity wireframes from Person 1 for Person 3.

Plans (`docs/p1/plans/`):

- [01_answer_key_schema.md](p1/plans/01_answer_key_schema.md) — answer-key proposal.
- [1.1_transition_grammar.md](p1/plans/1.1_transition_grammar.md) — data-driven transition grammar.
- [1.2_workflow_persistence.md](p1/plans/1.2_workflow_persistence.md) — workflow persistence.
- [1.3_workflow_engine.md](p1/plans/1.3_workflow_engine.md) — workflow engine and integration contract.
- [1.4_case_api.md](p1/plans/1.4_case_api.md) — case action and read APIs.
- [1.5_intake_checklist.md](p1/plans/1.5_intake_checklist.md) — intake checklist, DSC and route.
- [1.6_route_acceptance.md](p1/plans/1.6_route_acceptance.md) — route acceptance tests.
- [2.1_deficiency_loop.md](p1/plans/2.1_deficiency_loop.md) — persisted deficiency loop.
- [2.2_rescrutiny.md](p1/plans/2.2_rescrutiny.md) — re-scrutiny scope and rejected-item rollover.
- [2.3_committee_workspace.md](p1/plans/2.3_committee_workspace.md) — committee workspace.
- [2.4_letter_issuance.md](p1/plans/2.4_letter_issuance.md) — letter issuance (blocked on a contract change).
- [2.5_scale_generator.md](p1/plans/2.5_scale_generator.md) — scale generator.
- [2.6_answer_key_verifier.md](p1/plans/2.6_answer_key_verifier.md) — answer-key verifier.
- [3.1_evc_schema.md](p1/plans/3.1_evc_schema.md) — EVC storage and seed.
- [3.2_evc_queue.md](p1/plans/3.2_evc_queue.md) — EVC queue and workflow integration.
- [3.3_expert_pool.md](p1/plans/3.3_expert_pool.md) — expert pool management.
- [3.4_simulated_selector.md](p1/plans/3.4_simulated_selector.md) — deterministic panel selector.
- [3.5_edf_baseline.md](p1/plans/3.5_edf_baseline.md) — EDF baseline and shared scheduling metrics.
- [3.6_evc_cpsat_and_publication.md](p1/plans/3.6_evc_cpsat_and_publication.md) — CP-SAT planner, propose/publish API and publication.
- [3.7_evc_scheduling_decisions.md](p1/plans/3.7_evc_scheduling_decisions.md) — EVC scheduling decisions taken on 28 October 2026.
- [4.1_runtime_guard_facts.md](p1/plans/4.1_runtime_guard_facts.md) — runtime guard facts from a trusted server loader.
- [4.2_idempotent_p1_posts.md](p1/plans/4.2_idempotent_p1_posts.md) — idempotent Person 1 POST endpoints.
- [4.3_checklist_read.md](p1/plans/4.3_checklist_read.md) — checklist read endpoints.
- [4.4_routing_answer_key.md](p1/plans/4.4_routing_answer_key.md) — routing answer key.
- [4.5_frontend_read_gaps.md](p1/plans/4.5_frontend_read_gaps.md) — read endpoints the frontend needed.

Contract requests (`docs/p1/contract_requests/`):

- [2026-10-25_intake_item_events.md](p1/contract_requests/2026-10-25_intake_item_events.md) — intake item state-change event.
- [2026-10-25_transition_runtime.md](p1/contract_requests/2026-10-25_transition_runtime.md) — transition runtime contract changes (team review needed).
- [2026-10-26_committee_workspace.md](p1/contract_requests/2026-10-26_committee_workspace.md) — committee workspace integration.
- [2026-10-26_deficiency_review_events.md](p1/contract_requests/2026-10-26_deficiency_review_events.md) — deficiency review event (approved).
- [2026-10-26_letter_issuance.md](p1/contract_requests/2026-10-26_letter_issuance.md) — letter issuance (team review needed).
- [2026-10-26_rescrutiny_rollover.md](p1/contract_requests/2026-10-26_rescrutiny_rollover.md) — re-scrutiny rollover.
- [2026-10-27_edf_proposals.md](p1/contract_requests/2026-10-27_edf_proposals.md) — EDF proposal audit schemas and scheduling permission.
- [2026-10-27_evc_publication.md](p1/contract_requests/2026-10-27_evc_publication.md) — EVC publication event and scheduling routes.
- [2026-10-27_evc_queue.md](p1/contract_requests/2026-10-27_evc_queue.md) — EVC queue integration.
- [2026-10-27_expert_pool.md](p1/contract_requests/2026-10-27_expert_pool.md) — expert pool contracts and permissions.
- [2026-10-27_runtime_guard_facts.md](p1/contract_requests/2026-10-27_runtime_guard_facts.md) — runtime guard facts, idempotent POSTs, checklist reads.
- [2026-10-27_selector_preview.md](p1/contract_requests/2026-10-27_selector_preview.md) — simulated selector preview in the OpenAPI.
- [2026-10-28_evc_discard.md](p1/contract_requests/2026-10-28_evc_discard.md) — EVC schedule discard event and response fields.
- [2026-10-28_frontend_read_gaps.md](p1/contract_requests/2026-10-28_frontend_read_gaps.md) — read endpoints for the frontend.

## Reference

- [reference/SIH26262_Team_Split.txt](reference/SIH26262_Team_Split.txt) — how the problem statement was split between the three members ([PDF](reference/SIH26262_Team_Split.pdf)).
- [reference/SIH26262_Person1_Work_Pack.txt](reference/SIH26262_Person1_Work_Pack.txt) — Person 1's work pack ([PDF](reference/SIH26262_Person1_Work_Pack.pdf)).
