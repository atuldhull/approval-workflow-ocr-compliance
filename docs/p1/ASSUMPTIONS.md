# P1 assumptions

## Answer-key proposal (24 October 2026)

- DEMO ASSUMPTION AK-001: proposal version `0.1.0` uses canonical UTC `YYYY-MM-DDTHH:MM:SSZ` logical instants supplied explicitly by a scenario/ClockPort. No wall-clock default is allowed. These are fictional scenario times, not APH dates.
- DEMO ASSUMPTION AK-002: one file contains one seed, one pinned ruleset key, and exactly one workflow expectation record per application. Category is the existing YAML route key; institution category is a proposed synthetic classification code, not an APH institution taxonomy.
- DEMO ASSUMPTION AK-003: RO identifiers are synthetic uppercase codes; nine official RO names/codes are not asserted. Stable UUIDs will be supplied by the future generator; the models create no random IDs.
- DEMO ASSUMPTION AK-004: counts are exact array totals, late/delay durations use elapsed seconds, and item states are snapshots at each loop's `as_of_clock`. A route plan retains SHC `as_applicable`; `expected_visited_stages` records the chosen path at `route_outcome.at_clock`.
- DEMO ASSUMPTION AK-005: P2/P3 reserved extension objects must currently be `{}`. Unknown extension fields are rejected until a reviewed schema version adds them. Empty means not supplied/not scored, never zero expected alerts or a passed tamper test.
- DEMO ASSUMPTION AK-006: illustrative 30-day AICTE_PROCESSING and 15-day INSTITUTION_RESPONSE expectations follow the existing demo-assumption YAML, not legal deadlines. Sample EVC dates and letters are fictional planted expectations, not implemented workflow behavior or APH requirements.
- DEMO ASSUMPTION AK-007: P3 compares exact clock operations/instants and stable expectation IDs; tolerance, alert/escalation dedup keys and ledger targets await team agreement. No production event types, new shared ports, or legal clauses are introduced by this proposal.
