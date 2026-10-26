# Per-seed answer key: proposal 0.1.0

Update (scale-generator task, 26 October 2026): P1 now produces this proposed format with `generator/cases/scale_generator.py`; see category_mix.md for CLI/replay, DEMO assumptions and coverage limits. The generator task explicitly authorizes P1 use of the proposal; P2/P3 adoption still awaits review. Historical references below to a future generator describe the original proposal scope. Reserved extensions and the 0.1.0 schema/models are unchanged.

**PROPOSED_TEAM_REVIEW. DEMO data only. Not an agreed shared contract.** This schema intentionally lives in `docs/p1/`, not `contracts/`. It adds no API, table or event type. The separately authorized P1 scale generator now produces this format; P2/P3 must review the questions below before integrating their scorecard/extensions.

## Artifacts and validation

- `answer_key.schema.json`: JSON Schema draft 2020-12, ID `urn:sih26262:p1:answer-key:0.1.0`.
- `answer_key_example.json`: hand-written fictional scenario, not output from the current seed script.
- `generator/cases/answer_key_models.py`: Pydantic models; `answer_key_json_schema()` produces the checked-in schema exactly. Schema and models are kept in sync by tests.
- `tests/test_answer_key_schema.py`: positive/negative structural validation, semantic validation, deterministic serialization and YAML route consistency.

JSON consumers must use a draft 2020-12 validator **with format checking enabled**. Pydantic consumers call `AnswerKey.model_validate_json(...)`, then serialize with `model_dump_json()`. All fields are required, including nullable fields; unknown fields are forbidden at every object level. Strings are enums, UUIDs, version/ruleset tokens, uppercase codes or constrained ISO dates/instants. There are no names, reasons, arbitrary notes, personal data, free-text payloads or actual production event envelopes.

The pinned jsonschema setup does not install its optional RFC3339 date-time checker. Merely passing its default FormatChecker does not guarantee date-time checking is active. The tests explicitly register a `date-time` checker using `datetime.fromisoformat` (the schema regex separately enforces UTC spelling), and include an impossible calendar date as a regression. P3 must likewise provide a working date-time format checker or run the Pydantic validator; do not silently ignore this format.

The JSON Schema defines structural validity. Pydantic additionally enforces relational invariants (below) that draft 2020-12 cannot express. P3 should run both validations, or implement equivalent semantic checks; schema-only validation does not prove reference/count consistency. Tests explicitly demonstrate this boundary.

## Header and identity

One file per nonnegative integer seed. `header` contains schema_version (fixed 0.1.0), review_status (fixed PROPOSED_TEAM_REVIEW), label (DEMO), seed, generator_version (three numeric components), ruleset_key, generated_at_clock and counts. `generated_at_clock` is a caller-supplied logical scenario instant, never an automatically obtained wall-clock timestamp. Future generator code must obtain time from ClockPort and stable IDs from its seeded deterministic strategy. No model reads a clock or generates a UUID.

All instants are canonical UTC `YYYY-MM-DDTHH:MM:SSZ`, without fractional seconds; dates are real `YYYY-MM-DD`. Canonical UTC makes direct timestamp ordering unambiguous. The header timestamp identifies generation on the logical clock, not an upper bound on future planted expectations. All sample timings are DEMO ASSUMPTIONS, not legal/APH claims. `counts` contains exact totals for institutions, applications, deficiency_loops, deficiency_items, late_responses, evc_delays, letters and clock_expectations. It does not include unprovided P2/P3 metrics.

`institutions[]`: id, region, ro_id, category, label. Region/RO and institution category are proposed synthetic uppercase codes; no official nine-RO vocabulary or APH institution taxonomy is asserted. `applications[]`: id, institution_id, category, route_id, pinned_ruleset_key, label. Application category and route_id are the same **existing YAML category key**, not a numeric route ID. All applications use the header's pinned key in this proposal. Need mixed revisions? Split files until the team agrees a revised format.

## Planted workflow expectations

Exactly one `workflow_expectations[]` record per application, joined by application_id:

| Field | Meaning |
|---|---|
| deficiency_loop_count | Exact length of deficiency_loops, including still-open loops |
| deficiency_loops | UUID, recorded_at_clock, as_of_clock, optional paired response_id/responded_at_clock, nonempty items |
| items | UUID, OPEN/RESOLVED, nullable resolved_at_clock/resolution_response_id; resolved items reference that loop's response/time |
| late_responses | response_id, loop_id, expected_by_clock, responded_at_clock, positive late_by_seconds |
| evc_delays | request_id, planned_at_clock, actual_at_clock, positive delay_seconds |
| route_outcome | at_clock, expected_stage_list of `{stage, when}`, expected_visited_stages and expected_status |
| letters_to_issue | UUID, type from existing LetterType, issue_at_clock, lists_deficiencies boolean |

Item state is a snapshot at the loop's as_of_clock, not a claim the item stays open forever. One response per loop is represented in this version; multiple attempts require separate loops or a reviewed extension. A resolved item uses the loop response's time; no unrecorded resolution event is invented. Late-response duration is exact elapsed seconds after expected_by_clock, not calendar/working-day arithmetic. EVC delay likewise uses exact elapsed seconds. Loop counts, IDs, times and resolution references are validated.

`expected_stage_list` preserves the pinned YAML route plan: strings normalize to `when: always`, SHC mapping retains `as_applicable`. `expected_visited_stages` is the ordered observed path expected at route_outcome.at_clock, including DEFICIENT/RESCRUTINY when applicable and omitting an unselected optional stage. It is not mechanically identical to the plan. expected_status uses ApplicationStatus. Models validate shared enums; the future generator must resolve the actual pinned YAML route (including demo restrictions), and the scorecard must check it. Unknown new uppercase route IDs are structurally allowed for future reviewed rulesets, not proof of a published route. A test verifies this example against the real r1 YAML.

The example has an open item at the July snapshot and future August EVC/letter expectations. It is an answer key of planted checkpoints, not an exhaustive legal transition history; the future scenario generator must supply intermediate resolutions before advancing. Letter expectations do not invoke CompliancePort, create P2 obligations or assert eligibility. P2 owns the meaning of subsequent legal deadlines.

## Clock expectations

Each entry has a stable expectation UUID, application_id, subject_type (`application`, `obligation`, `evc_request`), subject_id, rule_id, clock_kind, clock_owner, at_clock and basis (`RULESET` or `DEMO_ASSUMPTION`). These are scorecard operation names, **not new domain event types**.

| operation | Additional data / constraint |
|---|---|
| OPEN | anchor_at_clock, expected_due_date, expected_due_at_clock; supports LEGAL and INTERNAL |
| PAUSE / RESUME | INTERNAL only; LEGAL is rejected by schema and models |
| CLOSE | outcome MET or WAIVED, matching current DeadlinePort close behavior |

`OPEN.at_clock` is the expected command time; anchor_at_clock can be an earlier logical instant. due_date is P2's civil date; due_at_clock is the corresponding UTC deadline instant. The example follows current P2 end-of-day IST conventions (18:29:59Z), 30 calendar days AICTE_PROCESSING and 15 calendar days INSTITUTION_RESPONSE; both durations are existing demo assumptions. P2 must confirm civil-date/timezone semantics and future rule coverage. Rule IDs are uppercase codes resolved against the pinned ruleset, not a list of invented legal rules.

Array order breaks ties for operations at the same instant; the example closes INSTITUTION_RESPONSE then resumes AICTE_PROCESSING. P3 should compare each expectation by stable ID plus subject/rule/operation/instant, not database-generated ledger sequence numbers. Actual event-to-operation matching, dedup keys and tolerances await review. No requirement is made to add events to contracts here. The proposal can express operations currently missing production ledger schemas; it does not claim they work today.

Semantic validation covers unique IDs per entity kind, exactly one workflow record per application, institution/application references, category=route_id, pin equality, exact counts, loop/resolution/late-response references, correct positive durations and clock-to-application subject references. External obligation IDs, the full chronological clock state machine, future intermediate workflow events, rule-derived due-date calculations and observed ledger comparison require the future generator/scorecard and owners' implementations. A schema pass alone cannot verify them.

## Reserved extensions: intentionally empty

`p2_extensions` and `p3_extensions` are required **empty objects `{}`**. Their models declare no fields and their schema disallows additional properties. This preserves ownership and prevents untyped free text from slipping into expected values. Empty is NOT zero expected alerts, zero OCR errors or a successful tamper check. P3 must report these metrics as NOT_SUPPLIED, outside this proposed file's empty objects, until reviewed data exists.

P2 reservation scope: per-document OCR date truth and document/version identifiers; script vocabulary; degradation levels; planted reviewer errors; expected alerts, alert identities, duplicates and escalation targets/times. **P1 does not define or populate these fields.** P2 proposes their machine-checkable types/enums and a version update.

P3 reservation scope: ledger tamper targets, mutation kinds, expected verification result and independent-checkpoint reference. **P1 does not define or populate these fields.** This version cannot score alert/escalation, OCR or tamper metrics; it prepares only the workflow/clock foundation and ownership boundaries. No empty object may be silently interpreted as a passing score.

## Determinism and evolution

Serialize identical validated input identically; fixed explicit seed/IDs/times and list ordering are required. Counts are derived from recorded arrays. Exact same-seed output across generator versions is not promised; compare generator_version/schema_version/ruleset_key too. There is no random or real-time default in these models. Changes, especially extension contents, require P2/P3 team review and an explicit schema-version decision; this document does not approve shared contracts. Assumptions AK-001 through AK-007 are recorded in ASSUMPTIONS.md. The scale generator is implemented separately; P2/P3 scorecard integration remains a future task.

## TEAM REVIEW NEEDED

1. P2/P3: Are canonical UTC instants, per-seed single-ruleset files, snapshot semantics and zero timing tolerance acceptable?
2. P2: Which document/date-truth fields, script/degradation enums and reviewer-error outcomes should p2_extensions define?
3. P2/P3: What expected-alert identity, dedup key, escalation target/level and logical-time rules will the scorecard compare?
4. P3: Which stable tamper targets, mutation enums and trusted-checkpoint results should p3_extensions define?
5. P2/P3: Who approves schema versions, RO/category vocabularies, extension readiness and NOT_SUPPLIED metric reporting?
