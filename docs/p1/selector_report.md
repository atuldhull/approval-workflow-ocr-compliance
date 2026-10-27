# SIMULATED authorised selector (stand-in)

This is a deterministic demonstration selector under `backend/app/evc/selector.py`. The work pack references APH 1.8(a) as automated, not random. The official clause/report section is unavailable here, so this implementation does not claim to be the official authorised selector. All policy and output carry SIMULATED / DEMO ASSUMPTION labels. P3 user identity verification remains pending.

The scheduler entry point is `select_panel(request, date, slot_part)`. Its immutable SelectorRequest includes EligibilityRequest, category, SelectorPolicy and AssignmentFact history. `selector_service.selector_request(session, request_id)` materializes those facts using own EVC tables and published CasePort/RulesetPort interfaces. Selection performs no I/O, clock lookup, mutation or reservation. The future scheduler must authorize, refresh facts and reserve/publish atomically; a preview is not a reservation.

## Ordered criteria and explanation fields

| Order | Criterion | Machine-readable explanation | Preference |
| --- | --- | --- | --- |
| 1 | Hard eligibility | `eligibility_passed=true` for ranked rows | Existing active, COI, availability, region and reservation checks must pass |
| 2 | Expertise | `expertise_matches`, `matched_expertise_tags` | More distinct configured tags; configured minimum must pass |
| 3 | Workload | `workload_assignments` | Fewer distinct assignment/expert memberships |
| 4 | Rotation | `last_assignment_date`, `rotation_days`, `rotation_ordinal` | No earlier assignment first, then oldest earlier date |
| 5 | Stable tie-break | `expert_id` (UUID string) | UUID numeric order inside Python; no 128-bit JSON integer |

These are lexicographic priorities, not an opaque weighted sum. Higher expertise can dominate workload. All proposed/published memberships count toward workload, including future/same-day commitments. Rotation uses only dates earlier than the candidate date; null means no earlier-date assignment, even if future commitments exist. Identical history duplicates count once and conflicting duplicates are rejected.

The pinned YAML defaults are `panel_size: 3`, `required_expertise_tags: [DEMO]`, `category_expertise_tags: {}` and `minimum_expertise_matches: 1`, under version DEMO_SELECTOR_V1 and SELECTOR_POLICY_UNCONFIRMED. Category-specific mappings are explicit overrides validated against route IDs. No category-to-domain or official panel size is guessed. Cached r1 checksums stay immutable; changed r1 demonstration sources need a fresh disposable demo database.

The result is SELECTED with exactly N distinct IDs, or INSUFFICIENT_CANDIDATES with an empty panel and the qualified ranking retained. Selected flags are all false on shortage. COI experts cannot re-enter through expertise or workload ranking.

## Read-only API

`GET /api/evc/requests/{id}/panel-preview?date=YYYY-MM-DD&slot_part=AM|PM` returns the exact selector_label `SIMULATED authorised selector (stand-in)`, simulation_status SIMULATED, source_status DEMO_ASSUMPTION, pinned ruleset key, policy version, requested size, status, panel and scored ranking. No personal details are returned; identities remain P3_USER_REF_UNVERIFIED.

Existing evc.expert.read and authoritative CasePort/AuthzPort case.timeline scope apply. Institutions cannot read it; RO readers require their own case and SAME_REGION policy. Cross-region previews require an existing global pool-reader role. QUEUED/PROPOSED requests only; invalid policy/state is a coded 422, missing request 404, forbidden scope 403, and a changed case reference 409. The preview creates no ledger rows, assignments or schedule runs.

## Controlled 100-request comparison

The test `test_workload_balance_improves_over_100_requests_against_first_fit` uses the same ten fictional DEMO experts, equal qualifications, date/part availability and 100 requests with N=3 for both algorithms. Between requests, the harness appends explicit hypothetical assignment facts. The pure selector itself remains unchanged and stateless. First-fit takes the first three eligible UUIDs on each request.

| Measured result | Simulated selector | Naive first-fit |
| --- | --- | --- |
| Total assignment memberships | 300 | 300 |
| Per-expert loads | 30 for all ten | 100 for three; 0 for seven |
| Maximum minus minimum load | 0 | 100 |
| Integer variance numerator `n*sum(load^2)-sum(load)^2` | 0 | 210000 |

The selector improves balance on this controlled cohort. This is not a universal fairness or optimisation claim for unequal expertise, different availability, COIs or region constraints. Determinism, permutation invariance, hard exclusions, each ranking priority, shortages, history edge cases and API label/scope/no-write behavior are independently tested.

Focused verification: 68 tests passed, including all 43 new cases and existing policy/eligibility/schema regressions. Final full suite: **6239 passed**, zero failures/errors/skips, one existing Starlette/AnyIO warning (1513.62 seconds). Contract generation/check passed; migration checker verified four chains with one head each (plat_0001, wf_0006, evc_0003, dl_0001). The tested source matched 174 code/data files in the actual checkout. No new event, table or migration; generated OpenAPI is the only protected-file edit. See plans/3.4_simulated_selector.md for the exact commands, environment and file list.
