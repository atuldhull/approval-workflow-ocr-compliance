# P1 assumptions

## Answer-key proposal (24 October 2026)

- DEMO ASSUMPTION AK-001: proposal version `0.1.0` uses canonical UTC `YYYY-MM-DDTHH:MM:SSZ` logical instants supplied explicitly by a scenario/ClockPort. No wall-clock default is allowed. These are fictional scenario times, not APH dates.
- DEMO ASSUMPTION AK-002: one file contains one seed, one pinned ruleset key, and exactly one workflow expectation record per application. Category is the existing YAML route key; institution category is a proposed synthetic classification code, not an APH institution taxonomy.
- DEMO ASSUMPTION AK-003: RO identifiers are synthetic uppercase codes; nine official RO names/codes are not asserted. Stable UUIDs will be supplied by the future generator; the models create no random IDs.
- DEMO ASSUMPTION AK-004: counts are exact array totals, late/delay durations use elapsed seconds, and item states are snapshots at each loop's `as_of_clock`. A route plan retains SHC `as_applicable`; `expected_visited_stages` records the chosen path at `route_outcome.at_clock`.
- DEMO ASSUMPTION AK-005: P2/P3 reserved extension objects must currently be `{}`. Unknown extension fields are rejected until a reviewed schema version adds them. Empty means not supplied/not scored, never zero expected alerts or a passed tamper test.
- DEMO ASSUMPTION AK-006: illustrative 30-day AICTE_PROCESSING and 15-day INSTITUTION_RESPONSE expectations follow the existing demo-assumption YAML, not legal deadlines. Sample EVC dates and letters are fictional planted expectations, not implemented workflow behavior or APH requirements.
- DEMO ASSUMPTION AK-007: P3 compares exact clock operations/instants and stable expectation IDs; tolerance, alert/escalation dedup keys and ledger targets await team agreement. No production event types, new shared ports, or legal clauses are introduced by this proposal.

## Wireframe design assumptions (25 October 2026)

- DEMO ASSUMPTION WF-001: target screen visibility and write permissions in wireframes.md are proposals using existing roles. Committee assignment, regional scope, EVC publish authority and ruleset approval/separation of duties require P3 policy agreement; they are not today's implemented policy.
- DEMO ASSUMPTION WF-002: no api_plan.md or numbered future prompt schedule exists. The literal label "TO BE BUILT in prompt X.Y" means an unassigned future integration task. Only Work Pack 1.2 endpoint patterns are specified as calls; missing reads/committee/review integrations receive no invented URL.
- DEMO ASSUMPTION WF-003: proposed field/action payload names are UI handoff requirements, not approved contracts. "Closed" deficiency items display the proposed RESOLVED state. Checklist/DSC/source metadata, available actions, concurrency versions and committee fields still need backend design; no official Annexure checklist or legal clause is fabricated.
- DEMO ASSUMPTION WF-004: the BPMN screen is a read-only explanatory route visualization, not a workflow engine. Conditional SHC, current stage and unavailable loop/source metadata must remain explicit. Ruleset comparison never changes a case pin, and missing metrics/source fields are unavailable rather than guessed.
