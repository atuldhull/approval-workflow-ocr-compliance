# P1 low-fidelity wireframes for P3

25 October 2026. P1 supplies domain requirements; P3 owns every screen. These are text designs and proposed acceptance criteria, not implemented features or approved API changes. Basis: ENGINEERING_RULES.md, 00_repo_audit.md, the P1 Work Pack (especially 1.1/1.2/1.4/6/7), and current intake/workflow API models. No code or contracts change in this task.

## Reading this document

- **CURRENT** means an endpoint/response field exists in the checked-out code. It does not mean every wireframe feature is implemented. **PROPOSED** means a P1 field or interaction still to build and review with P3.
- `docs/p1/api_plan.md` does not exist. Only the nine endpoint patterns explicitly listed in Work Pack 1.2 are specified as calls below. Work Pack paths omit the real `/api` prefix; this document includes it. `{id}` means the application's UUID except in admin ruleset paths, where its representation remains to be agreed. The current submit route names its path parameter `{application_id}`; this is the same URL shape.
- Every missing integration is marked **TO BE BUILT (later task)**. No numbered implementation plan exists, so section names identify the work, without inventing task numbers or additional URL paths.
- Existing read DTOs are documented as evidence, but read URLs outside the allowed list are not introduced as integration calls here. Data needed to reload/deep-link a page, list institutions/categories, or read committee/ruleset details is an explicit integration gap until an API plan names the calls. A create/submit response can seed the case view; it cannot replace an authorized fresh read after navigation or a conflict.
- Proposed dotted field paths are design names, not claims about today's OpenAPI. P1 must resolve these in later endpoint work; any shared-contract change follows ENGINEERING_RULES.md. No reason-code catalog, policy, legal clause, committee API, or expert API is approved by this document.
- All synthetic fixtures show DEMO. Demo overlays display the server's simulation banner. All displayed times come from server/ClockPort-backed values; P3 may format them with an explicit timezone, but must not derive deadlines from browser time. Never render unavailable values as zero, success, or verified law.

### Allowed call register

| Alias | Call | Current availability |
|---|---|---|
| C | `POST /api/applications` | CURRENT: ApplicationIn -> ApplicationOut; 201 |
| S | `POST /api/applications/{id}/submit` | CURRENT: no request body -> ApplicationOut; 200 |
| A | `POST /api/cases/{id}/actions` | TO BE BUILT (later task) (guarded transitions/commands) |
| Q | `GET /api/evc/queue` | TO BE BUILT (later task) (queue and scheduling context) |
| P | `POST /api/evc/schedule:propose` | TO BE BUILT (later task) (dates-only proposal) |
| U | `POST /api/evc/schedule:publish` | TO BE BUILT (later task) (publish reviewed run) |
| R | `POST /api/admin/rulesets` | TO BE BUILT (later task) (register candidate revision) |
| V | `POST /api/admin/rulesets/{id}/validate` | TO BE BUILT (later task) (candidate validation) |
| G | `POST /api/admin/rulesets/{id}/approve` | TO BE BUILT (later task) (authorized approval) |

### Shared interaction and permission rules

Current identity is P3's X-Demo-User / X-Demo-Role / X-Demo-Institution / X-Demo-Region headers. This is demo auth, not a production login design. Current institution ownership is checked, but region/stage/assignment restrictions and most future action policies do not exist yet. Roles below are **target visibility**, subject to P3 authorization: use existing Role values; do not invent ADMIN or EVC_EXPERT roles. Assigned member is a resource attribute, not a new enum role. SYSTEM has no human screen. See ASSUMPTIONS.md WF-001 through WF-004.

Hide or disable unauthorized actions, and require server authorization regardless of button visibility. Do not trust a client-selected institution or assignment. Keep typed form contents after validation/network errors; clear protected contents on logout or 403. Provide loading, inline validation and an accessible error summary; focus the first invalid control. Mark pending requests and prevent duplicate clicks. P3's Idempotency-Key middleware remains future work: do not promise safe automatic retries of writes. Existing repeat submit returns 409. After an uncertain write, obtain an authorized fresh state through the future read integration before offering retry.

Current domain error shape is `{error, detail}` for ContractError (422 ValidationFailed, 404 NotFound, 403 Forbidden, 409 Conflict). Framework header/body validation and 401 use FastAPI `detail` shapes; P3 must support both. For future structured guard errors, `reason_code` is a **PROPOSED** field. Until supplied, show a safe generic message plus the server's supported error detail, not a fabricated reason code. Distinguish no records from failed load; never show stale data as freshly confirmed.

## 1. Institution: create, checklist, submit and route plan

**Purpose:** create a draft, complete the category checklist and DSC requirement, then submit and see the pinned route and its source. **Roles:** INSTITUTION for its own institution. Officers/AUDITOR do not file on its behalf in this design.

```text
+------------------------------------------------------------------+
| New application                                      DEMO        |
| Institution: [own institution, read only]                         |
| Category: [select category v]   Academic year: [2027-28]           |
| [Create draft]   Draft ID: ...   Status: DRAFT                     |
| Category checklist [requirements not yet available]               |
| [ ] Mandatory item ...      Evidence: [reference] [Select]        |
| [ ] DSC confirmed                                                |
| Missing mandatory items: ...            [Submit] (when ready)     |
| Route: SCRUTINY -> EVC -> SHC (as applicable)                      |
| Pinned ruleset: aph-2024-27@r1   Source: [citation / unavailable]   |
+------------------------------------------------------------------+
```

**Data mapping**

| Shown/input field | Endpoint and response/request mapping |
|---|---|
| Institution ID, category, academic year | C request: `institution_id`, `category`, `academic_year` (CURRENT); year pattern YYYY-YY, category uppercase code |
| Draft ID/status/timestamps | C/S response: `id`, `status`, `created_at`, `submitted_at` (CURRENT) |
| Institution display name; category labels/options | CURRENT DTO names: `InstitutionOut.name`, `RouteOut.category/label`; authorized options read integration TO BE BUILT (later task) (not an allowed call here) |
| Checklist/evidence/DSC/readiness | PROPOSED `checklist.items[].id/label/mandatory/status/evidence_refs[]`, `dsc_confirmed`, `can_submit`, `missing_item_ids[]`; checklist read/write integration TO BE BUILT (later task); not accepted by current C or returned by S |
| Route/current stage/pin | S response `route[].stage/when`, `current_stage`, `ruleset_rev` (CURRENT); DRAFT values may be null |
| Clause source | PROPOSED S response `route_citation.doc/clause/page/status`; TO BE BUILT (later task) (citation exposure); not an existing ApplicationOut field |

**Buttons -> calls:** Create draft -> C with the three CURRENT fields. Submit -> S using returned ID, only after future readiness checks; today S does not enforce checklist/DSC. Select evidence/checklist save/DSC save -> **TO BE BUILT (later task)** (intake/P2 evidence integration; no URL invented). Route display consumes S response, with a clear not-yet-available placeholder for missing citations. Initial category preview requires the future options/read integration; no hardcoded route lookup in the browser.

**Empty/error states:** no authorized institution/options -> no create button and an explicit unavailable state; no category-specific checklist -> readiness unknown, not complete. New draft has no submitted route. 422 -> retain inputs and identify invalid field/missing item; 403 -> clear unauthorized data; 409 repeat submit -> refresh via future authorized read rather than submit again. Source unknown -> "Citation unavailable - DEMO ASSUMPTION", never invent a clause. Table 2.3's global YAML source must not be blindly attributed to NEW_INSTITUTION's Chapter I route.

**Acceptance checks for P3**

1. With an INSTITUTION fixture, C sends exactly institution_id/category/academic_year; 201 displays returned id/status. Missing/wrong-format inputs show validation without losing valid values; an officer cannot create through a hidden or direct action.
2. Target behavior, pending checklist backend: one missing mandatory item or DSC requirement prevents submission in UI **and** a direct S request is rejected server-side. Unknown checklist readiness is not treated as complete. This server behavior is not present today.
3. After S succeeds, display the returned pin and ordered route, preserving SHC `as_applicable`; show a supplied citation or explicit unavailable state. A fixture with SELF_DISCLOSURE must not display EVC/SHC, and no source is inferred for NEW_INSTITUTION.

## 2. Case page: stages, actions and deficiencies

**Purpose:** view a case's pinned workflow, authoritative current stage and deficiency history. **Roles:** own-case INSTITUTION; authorized SCRUTINY_COMMITTEE, RO_OFFICER, BUREAU_OFFICER, BUREAU_HEAD; AUDITOR read-only. Scope/assignment checks are future P3 policy work.

```text
+------------------------------------------------------------------+
| Case <id>  DEMO   IN_PROCESS   Pinned: aph-2024-27@r1               |
| Plan: SCRUTINY -> EVC -> SHC (as applicable)                       |
| Current: RESCRUTINY     Visits: SCRUTINY / DEFICIENT / RESCRUTINY   |
| Available actions: [Record deficiency] [Complete] [Revert]         |
| Deficiencies: [Open 1] [Closed 1] [All]                            |
| Item ID | Raised at | Status       | Response reference           |
| ...     | ...       | OPEN         | ...                          |
| ...     | ...       | RESOLVED     | ...                          |
| [Open compliance form]  [Open Re-Scrutiny]                         |
+------------------------------------------------------------------+
```

**Data mapping**

| Shown field | Endpoint/field mapping |
|---|---|
| Case identity, state, plan and pin | C/S `id`, `status`, `route[].stage/when`, `current_stage`, `ruleset_rev` CURRENT; fresh case read TO BE BUILT (later task) |
| Visit history | PROPOSED read fields `stage_visits[].id/stage/entered_at/left_at`; model fields exist but are not returned by ApplicationOut; TO BE BUILT (later task) |
| Available actions | PROPOSED `available_actions[].action/enabled/block_reason_code/target_stages[]`; read integration TO BE BUILT (later task); not derived from role labels alone |
| Deficiency tabs/rows | PROPOSED `deficiencies[].id/items[].id/status/raised_at/response_ref`, `open_item_count`, `resolved_item_count`; TO BE BUILT (later task); UI "Closed" means proposed canonical RESOLVED, not a third state |
| Post-action state | PROPOSED A response `application.id/status/current_stage/ruleset_rev`, `available_actions[]`, `deficiencies[]`, `state_version`; TO BE BUILT (later task) |

**Buttons -> calls:** Record deficiency/Open compliance/Open Re-Scrutiny navigate to screens 3/4 without mutation. Complete -> A, PROPOSED request `action: complete`, `expected_state_version`; Revert -> confirmation/reason form then A, PROPOSED `action: authorised_revert`, `target_stage`, `reason_code`, `note`, conditional `second_approver_ref`, `expected_state_version`. These action names occur in YAML, but A and its payload are **TO BE BUILT (later task)**. Tabs filter already authorized rows locally; reload/initial deep link -> **TO BE BUILT (later task)** (fresh case read). Do not use S to advance a submitted case.

**Empty/error states:** no deficiencies -> "No deficiencies recorded" with zero counts only after successful load; DRAFT -> no current stage/visits yet; no available actions -> read-only explanation; failed action/read -> show failure, not empty history. 404 -> case not found; 403 -> no case content; 409 stale state -> require reload before another write; reason codes unavailable -> do not invent choices.

**Acceptance checks for P3**

1. Render plan and current_stage separately: a RESCRUTINY current stage remains visible even when not in the base route plan. Display the pinned r1 key after a demo overlay is loaded; never replace it with the current default.
2. Given one OPEN and one RESOLVED item, tabs show 1/1/2 and the resolved row retains its response reference. A failed deficiency load shows an error, not zero open items.
3. Only server-enabled actions can be selected; direct unauthorized/stale commands receive 403/409. A failed mutation leaves displayed confirmed state unchanged and prompts a fresh read rather than optimistic advancement.

## 3. Record deficiency and submit compliance forms

**Purpose:** record itemized deficiencies with a coded reason and protected note, and let the institution respond to those items. **Roles:** SCRUTINY_COMMITTEE for record_deficiency in SCRUTINY (as current YAML declares); own-case INSTITUTION for submit_compliance in DEFICIENT. Other views read-only unless future policy/YAML explicitly permits.

```text
+--------------------------------+---------------------------------+
| Record deficiency              | Submit compliance               |
| Case/stage/version: ...        | Case/stage/version: ...         |
| Reason code: [select v]         | Open items                      |
| Item 1: [requirement reference] | ID ... [response note]          |
| [Add item] [Remove item]        |        [evidence references]    |
| Note: [text, protected]         | ID ... [response note]          |
| [Cancel] [Record deficiency]    | [Cancel] [Submit compliance]    |
| Preview: AICTE clock pauses;    | Preview: response clock closes; |
| response clock opens (DEMO)     | AICTE clock resumes (DEMO)      |
+--------------------------------+---------------------------------+
```

**Data mapping**

| Form field | Endpoint/field mapping |
|---|---|
| Case/stage/version, selectable open items | CURRENT C/S id/current_stage; PROPOSED authorized case fields `state_version`, `deficiencies[].items[].id/status/requirement_ref`; read integration TO BE BUILT (later task) |
| Reason choices and requirement labels | PROPOSED `reason_codes[].code/label`, `requirements[].id/label`; TO BE BUILT (later task); no current reason enum/catalog exists |
| Recorded deficiency | PROPOSED A request `action: record_deficiency`, `reason_code`, `note`, `items[].requirement_ref`, `expected_state_version`; response `deficiency.id`, `deficiency.items[].id/status`, `application.current_stage`, `note_ref`, `note_hash` |
| Compliance response | PROPOSED A request `action: submit_compliance`, `responses[].item_id/note/evidence_refs[]`, `expected_state_version`; response `response.id`, `deficiency.items[].response_ref/status`, `application.current_stage` |
| Clock consequence preview | PROPOSED `clock_effects[].rule_id/operation/clock_kind/source_status` returned by future read/guard metadata; not a browser-computed due date; TO BE BUILT (later task) |

All A payloads/results above are **TO BE BUILT (later task)**. Free text is a command input over HTTP, not event payload content: the backend must call notes.create and append only note_ref/note_hash to events; personal information requires personal.store. No frontend call to an internal port is specified. Evidence uses P2-owned references; an upload integration is outside this allowed endpoint list and remains **TO BE BUILT (later task)**.

**Buttons -> calls:** Add/remove item edits local form state. Cancel discards local changes after unsaved-change confirmation, no API. Record deficiency -> A using proposed record payload; Submit compliance -> A using proposed response payload. On success use returned state, then future fresh read; never infer that submission itself verifies or resolves every item. Preview is explanatory, not a separate timer request. P1's command coordinates P2 timers atomically.

**Empty/error states:** missing reason catalog -> record disabled with "Reason codes not available"; no items -> inline error, no record; no open items -> no compliance mutation. 422 missing reason/item/evidence -> retain form and focus error; 403 wrong actor/stage -> disable and clear protected context; 409 stale version -> reload items before retry. Clock failure -> whole command fails; no partial success message or independently submitted clock calls.

**Acceptance checks for P3**

1. Record requires a reason code and at least one requirement-linked item; a successful fixture creates item IDs and displays DEFICIENT. Inspect the resulting event fixture: note text is absent; only references/hash are present.
2. Compliance sends only displayed eligible item IDs and evidence references. A successful response moves to RESCRUTINY but does not automatically mark all items RESOLVED; previously resolved items cannot be silently rewritten.
3. Simulate a P2 clock failure and a stale-state 409: neither form reports success or advances the case. Preserve editable values where safe and require refreshed item/version context before resubmission; repeated clicks create no second in-flight request.

## 4. Re-Scrutiny: open items only

**Purpose:** review only outstanding items and trace each to the institution's response before allowing progression. **Roles:** assigned/authorized SCRUTINY_COMMITTEE; authorized officers/AUDITOR read-only; institution may see its own outstanding items but cannot resolve or complete committee work.

```text
+------------------------------------------------------------------+
| Re-Scrutiny - Case <id>  DEMO   Current: RESCRUTINY                 |
| OPEN ITEMS ONLY                                      Open: 1     |
| Item ID | Requirement | Response ref | Evidence refs | Review     |
| ...     | ...         | ...          | ...           | [Open]     |
| Review: [Accept response] [Still deficient]  Note: [protected]     |
| Resolved history is available on Case page, outside this list     |
| [Save review]   [Complete Re-Scrutiny] (disabled while open > 0)   |
+------------------------------------------------------------------+
```

**Data mapping:** PROPOSED authorized Re-Scrutiny read `application.id/current_stage/state_version`, `open_items[].id/requirement_ref/response_ref/evidence_refs[]/status`, `open_item_count`, `available_actions[]`; **TO BE BUILT (later task)** (open-item projection). Labels/evidence content come through authorized read integrations, not unrestricted file links. PROPOSED review input `item_id`, `outcome` (RESOLVED or OPEN), `reason_code`, `note`, `expected_state_version`; result `item.id/status/response_ref` and refreshed counts/version. This review-save integration is **TO BE BUILT (later task)**; no new action name or URL is approved here.

**Buttons -> calls:** Open shows the item's response/evidence through **TO BE BUILT (later task)** (authorized detail read). Accept response/Still deficient set local review outcome. Save review -> **TO BE BUILT (later task)** (review command; missing from section 1.2/API plan). Complete Re-Scrutiny -> A, proposed `action: complete`, `expected_state_version`, guarded by `open_items == 0` in YAML; A is **TO BE BUILT (later task)**. History navigates to screen 2 locally.

**Empty/error states:** successful open_items=[] -> "No open items" and enable completion only if the server also permits it. Missing response/evidence -> explicit unavailable state, not assumed compliance. Failed list/count request -> completion disabled. 403 -> no unauthorized item content; 409 -> refresh before a second review; 422 guard failure -> retain list and show structured reason if available.

**Acceptance checks for P3**

1. With OPEN, RESOLVED, OPEN fixture items, this list displays exactly the two OPEN IDs; resolved history does not leak into a filter/pagination refresh. Server projection, not just CSS filtering, supplies open-only content.
2. An accepted item disappears only after confirmed server RESOLVED status; its response/evidence references remain traceable on the case history. A failed save leaves it in the open list.
3. With one open item, Complete is disabled and a direct A complete command is rejected; after open_item_count=0 and server permission, completion follows the case's next pinned-route stage rather than hardcoding EVC for every category.

## 5. Committee workspace

**Purpose:** let assigned members work tasks, record observations and append authored report versions without overwriting history. **Roles:** SCRUTINY_COMMITTEE when assigned; authorized RO_OFFICER/BUREAU_OFFICER/BUREAU_HEAD and AUDITOR read-only. Other committee types/membership policy remain for P3/P1 agreement; no new Role enum is assumed.

```text
+------------------------------------------------------------------+
| Committee <id> / Case <id>   DEMO   Assignment: <member reference>  |
| Tasks: ID | Assignee ref | State | Due (if supplied)               |
|        ...| ...          | OPEN  | ...                            |
| Observations: ID | Item/task ref | Author ref | Note [View]        |
| [Add observation]  [Save task work]                               |
| Report versions (append only)                                    |
| v2 | Author ref ... | Submitted at ... | [View]                    |
| v1 | Author ref ... | Submitted at ... | [View]                    |
| [New report version]                 No edit/delete old version   |
+------------------------------------------------------------------+
```

**Data mapping:** all PROPOSED, **TO BE BUILT (later task)** (committee read/write integration): `committee.id`, `application.id`, `membership.member_ref`, `tasks[].id/assignee_ref/status/due_at`, `observations[].id/task_id/item_id/author_ref/note_ref/created_at`, `report_versions[].id/version/author_ref/created_at/note_ref`, and `can_write`. No committee model, task model, report response or committee-specific action exists today. due_at is optional and displayed only when supplied by the backend. P3-resolved display labels may accompany references after authorization; no personal names enter workflow event payloads.

**Buttons -> calls:** select task/View observation/View report -> **TO BE BUILT (later task)** (authorized reads). Add observation/Save task work/New report version -> **TO BE BUILT (later task)** (committee commands). Proposed command fields: task_id/item_id and note for observation; task_id, proposed outcome and expected_state_version for task work; base_version and report note for append. Author and timestamp are server-attributed, never trusted from editable fields. No endpoints outside the allowed list are invented, and no generic A action is falsely claimed for committee writes. Old report versions expose View only.

**Empty/error states:** no assignment -> read-only/403 as policy decides, not a writable empty workspace; no tasks -> "No tasks assigned"; no versions -> "No report submitted"; missing author metadata -> "Attribution unavailable", never a guessed author. Missing authorized note content -> unavailable placeholder. A concurrent base-version 409 refreshes history and preserves a local draft; validation failure creates no version.

**Acceptance checks for P3**

1. An assigned member can open only authorized tasks; changing the task/member reference in a direct command cannot write another member's work. Read-only users have no mutation controls and receive 403 on direct writes.
2. Adding a report version appends v2 without altering v1's contents, author or timestamp; refresh shows both, ordered by version. Old versions have no edit/delete operation.
3. An observation retains task/item linkage, author reference and protected note reference. A stale-base 409 leaves existing report history unchanged and offers draft recovery, not a silent overwrite.

## 6. EVC queue, expert pool and proposed schedule

**Purpose:** inspect EVC demand and eligible panel context, propose conflict-free dates, understand choices and publish a reviewed run. **Roles:** proposed RO_OFFICER scheduler in scope; BUREAU_OFFICER/BUREAU_HEAD for review/publish when P3 policy allows; AUDITOR read-only. Expert access is assignment-scoped future policy, not a newly invented role. Panel selector authority is ruleset metadata, not automatically a human login permission.

```text
+------------------------------------------------------------------+
| EVC scheduling  DEMO   Ruleset: ...   SIMULATION banner if needed  |
| Queue: Request ID | Case ID | Region | Ready at | Target date     |
|        [ ] ...    | ...     | ...    | ...      | ...             |
| Expert pool: Ref | Availability | COI eligibility | Panel ref     |
| ...              | ...          | ELIGIBLE        | ...           |
| Panel source: AUTHORISED SELECTOR STAND-IN (DEMO)                  |
| [Propose dates]    Dates only; panel membership is not optimized   |
| Proposed run: ...  Solver: ...  Hard violations: ...  EDF: ...     |
| Request | Proposed slot | Expert/panel refs | [Why this slot]      |
| ...     | ...           | ...               | ...                |
| [Publish reviewed run]                                            |
+------------------------------------------------------------------+
```

**Data mapping** (all PROPOSED; Q/P/U are **TO BE BUILT (later task)**)

| Widget | Allowed call / proposed response fields |
|---|---|
| Queue/context | Q `queue[].request_id/application_id/region/ready_at/target_at/ruleset_key`, `snapshot_version` |
| Expert/panel context | Q proposed `expert_pool[].expert_ref/availability[]/coi_eligibility`, `panels[].panel_ref/expert_refs[]`, `selector_label`, `can_propose`, `can_publish`; inclusion in Q requires agreement; a separate expert API is not assumed |
| Proposed table | P `run_id`, `input_snapshot_version`, `status`, `assignments[].request_id/slot_start/slot_end/panel_ref/expert_refs[]`, `hard_violation_count`, `solver_status`, `edf_metrics`, `proposal_metrics`, `metric_definitions` |
| Why panel | P `assignments[].why.reason_codes[]/constraint_refs[]/alternative_slots[]`; labels map codes for display, with no claimed legal EVC duration |
| Publication | U `run_id`, `status`, `published_at`, `assignments[]`; server-derived logical timestamps |

**Buttons -> calls:** Reload queue -> Q. Propose dates -> P with PROPOSED `request_ids[]`, `input_snapshot_version`, explicit logical planning horizon; no user-supplied expert reassignment. Why this slot expands the returned explanation locally, no extra endpoint. Publish -> confirmation, then U with PROPOSED `run_id` and `input_snapshot_version`; never publish by resending a table edited in the browser. Availability/COI edits are outside the named endpoints and **TO BE BUILT (later task)** if requested later; current design is read-only pool context.

**Empty/error states:** empty queue -> no proposal call; no eligible panel/availability -> UNSCHEDULABLE with reason codes, not blank slots marked success. Timeout/solver unknown -> no publish. 403 outside scope -> no queue/expert details; 409 queue/availability changed -> invalidate proposal, reload Q and propose again. Missing EDF/score definition -> "Comparison unavailable", not a performance claim. r3-DEMO banner remains visible, and dates/durations without official basis are DEMO ASSUMPTION.

**Acceptance checks for P3**

1. An empty queue sends no P request; an unschedulable request shows a coded reason and cannot be published as a successful assignment. Display the supplied selector stand-in label and simulation banner.
2. For a valid fixture, table and Why panel show the exact P slot/panel refs and reasons. Hard violations must be zero before Publish is enabled; CP-SAT chooses dates only, and comparison uses the same queue/metric definition as EDF without promising it always wins.
3. Publish sends run_id plus input snapshot version, not editable assignments. A 409 stale run or unauthorized 403 publishes nothing; a successful U result displays its status/time and freezes that run's presented assignments.

## 7. Admin rulesets: list, validate, approve and demo diff

**Purpose:** inspect versioned candidates, validate before approval, and compare r1 with the unverified r3-DEMO overlay without changing existing case pins. **Roles:** proposed BUREAU_HEAD for candidate registration/approval; BUREAU_OFFICER/RO_OFFICER for permitted read/validation; AUDITOR read-only. Approval policy and separation of duties are unconfirmed (WF-001), not a current entitlement.

```text
+------------------------------------------------------------------+
| Rulesets  DEMO                                        [Register]  |
| Key                  | Status          | Default | Validation      |
| aph-2024-27@r1       | verified_text   | Yes     | ...             |
| aph-2024-27@r3-DEMO  | unverified_demo | No      | ...             |
| Selected: ...  [Validate]  [Approve] (if policy + checks permit)    |
| Compare: [r1 v] [r3-DEMO v] [Compare locally]                      |
| SIMULATION - reported corrigendum NOT verified                    |
| Field                    | r1               | r3-DEMO             |
| roles.evc_constituted_by  | REGIONAL_OFFICER | COUNCIL             |
| Routes / submit clocks   | same base        | inherited           |
| Existing application pins remain unchanged                        |
+------------------------------------------------------------------+
```

**Data mapping**

| Field | Source/availability |
|---|---|
| Key/status/default/banner/routes | CURRENT `RulesetOut.key/status/is_default/banner/routes[].category/label/stages[].stage/when` DTO; list/detail read integration is outside section 1.2 and **TO BE BUILT (later task)** in an API plan; do not call validation to emulate a list read |
| Role difference, base/source/effective metadata | PROPOSED detail fields `roles.evc_constituted_by`, `extends`, `source`, `effective_from`, `clocks_on_submit`; **TO BE BUILT (later task)** (read exposure). These are not all in RulesetOut; effective_from is currently ignored by the loader |
| Candidate registration | R PROPOSED request `ruleset_key`, `candidate_ref`; response `id/key/status`; **TO BE BUILT (later task)** |
| Validation | V PROPOSED response `validation_id`, `candidate_version`, `valid`, `issues[].code/path`, `validated_at`; **TO BE BUILT (later task)** |
| Approval | G PROPOSED request `validation_id`, `candidate_version`; response `key/status/approved_by_ref/approved_at`; **TO BE BUILT (later task)** |

**Buttons -> calls:** Register -> R after local candidate selection (candidate upload/authoring integration is **TO BE BUILT (later task)**, no upload URL invented). Validate -> V for a selected registered ID. Approve -> G after policy/validation confirmation; approval does not implicitly change default revision or migrate cases. Reload/list/select comparison revisions -> **TO BE BUILT (later task)** (authorized list/detail reads). Compare locally operates only on two successfully loaded, version-identified responses; no fabricated diff endpoint. Current YAML changes EVC constitution metadata only; it does not change route stages or deadline keys.

**Empty/error states:** no registered candidates -> empty list and permitted Register action; missing list integration -> "Ruleset listing not connected", not zero rulesets. Invalid candidate -> show V issues, Approve disabled; unavailable validation -> unknown, not valid. Outside demo mode r3 loading is refused: show refusal rather than bypassing it to compute a diff. 403 cannot validate/approve; 409 changed candidate invalidates prior validation. Status `verified_text` is displayed as metadata, not an independent legal verification claim.

**Acceptance checks for P3**

1. With r1/r3 fixtures, display exactly REGIONAL_OFFICER -> COUNCIL, unchanged route lists, and the unverified SIMULATION banner. A non-demo refusal is visible and cannot be suppressed by the Compare control.
2. Failed/missing/stale validation disables Approve; direct unauthorized or changed-version G requests are rejected. Successful approval displays server attribution without treating it as a default-switch or automatic r3 production authorization.
3. Compare, register, validate and approve never rewrite an existing application's ruleset_rev. Reopen a case pinned to r1 and verify its route/citation still use r1 after candidate operations.

## 8. Route BPMN view

**Purpose:** provide a read-only route-version diagram and equivalent ordered text; distinguish visual explanation from a running BPMN/workflow engine. **Roles:** authorized officers and AUDITOR; INSTITUTION for its own pinned route context. Same authorized data scope as the case/ruleset read, no new role.

```text
+------------------------------------------------------------------+
| Route view  DEMO   Version: aph-2024-27@r1   Category: NEW_PROGRAMME|
| [Choose authorized route/version]   [Show text]   [Fit diagram]     |
| (Start) -> [SCRUTINY] -> [EVC] -> <SHC applicable?>                |
|                                      | Yes -> [SHC] -> (End)      |
|                                      | No ----------> (End)      |
| Current stage: RESCRUTINY (workflow loop; not in base route plan)  |
| Plan source: [citation / unavailable]                             |
| Read-only explanatory BPMN view; no execution controls            |
+------------------------------------------------------------------+
```

**Data mapping:** CURRENT S `ruleset_rev`, `category`, `route[].stage/when`, `current_stage` can seed this case view. CURRENT RulesetOut DTO `key`, `routes[].category/label/stages[].stage/when` describes a version's plan; authorized reload/version selection is **TO BE BUILT (later task)** (read integration outside the allowed endpoint list). PROPOSED `route_citation.doc/clause/page/status` and optional `transition_definitions[].from/action/to/guard/timers` exposure are **TO BE BUILT (later task)**; transitions are currently discarded by RuleSet loading, so do not pretend the diagram has received them. No BPMN XML, process-instance ID or execution endpoint exists or is required for this text design.

**Buttons -> calls:** Choose route/version -> **TO BE BUILT (later task)** (authorized route read). Show text/Fit diagram are local rendering controls with no API calls. For a case view, any comparison version is clearly separate from its immutable pinned context. No Complete/Advance/Run button: state-changing actions belong to screen 2/A. No download endpoint is invented.

**Empty/error states:** null DRAFT route -> "Submit to obtain pinned route"; unknown/empty route -> explicit load/validation error rather than invented Start/End success. Failed version read -> keep a stale-state label or clear diagram; outside-demo overlay -> refusal. Missing transition metadata -> show route sequence only and note that deficiency/revert loops are unavailable; if current stage is absent from the plan, display it separately without highlighting a wrong node. Citation unavailable stays explicit.

**Acceptance checks for P3**

1. Render returned stage order faithfully: NEW_PROGRAMME retains conditional SHC; SELF_DISCLOSURE renders a single stage; NEW_INSTITUTION includes EC and COUNCIL. Its visible source is supplied data, never borrowed Table 2.3 metadata.
2. Text and diagram convey the same order/conditions, keyboard users can access the text alternative, and the pin remains visible. A RESCRUTINY current stage is shown separately until actual loop metadata exists, not falsely mapped to SCRUTINY.
3. No diagram control mutates a case or executes a process. A failed or unauthorized version load provides no fictitious diagram, and selecting a comparison version leaves the case's pinned ruleset unchanged.

## Handoff and implementation boundaries

P1 builds authorized projections/commands and source attribution; P3 builds screens, access policy, identity display and future idempotency middleware; P2 supplies document/evidence/clock data through agreed integration. The most immediate UI blockers are missing checklist/DSC/citation fields, authorized reload/action metadata, deficiency/review/committee backends, EVC services, and admin candidate APIs. P3 can test the three acceptance checks per screen with explicit mocks now; future endpoint behavior checks remain pending implementation. This document's existence and passing backend regression tests do not mean these screens or endpoints are built.

No additional wireframe code, endpoint, event, table, reason enum, API snapshot or shared contract is introduced. No new legal rule or clause is assumed. Open product decisions are recorded as WF-001 through WF-004 in ASSUMPTIONS.md. Existing script/test checks are run unchanged before this documentation is committed and pushed to person-1.

## Verification for this documentation task

- Content inspection: eight ASCII wireframes, each with purpose, roles, field mappings, button calls, empty/error states and exactly three acceptance checks; specified URLs match the nine Work Pack 1.2 patterns.
- Python 3.12/Linux, read-only repository mount, dedicated disposable PostgreSQL 16: `python -m pytest -p no:cacheprovider` -> **76 passed, 1 dependency deprecation warning in 84.93 seconds**. Cache provider disabled only to keep the source mount read-only; no tests skipped or changed.
- `python scripts/check_contracts.py` -> exit 0, `contracts ok`.
- `python scripts/check_migration_heads.py` -> exit 0, `checked 3 migration chains`.
- Whitespace review passes. No new tests were added for a documentation-only handoff. Only this file and the WF assumptions in ASSUMPTIONS.md changed. These regression results do not claim any proposed screen, field, policy or endpoint is implemented.
