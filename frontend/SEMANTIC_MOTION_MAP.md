# Semantic motion map

Per screen: A purpose, B/C source fields, D/F visual meaning, E scroll behaviour, G interactions, H/I/J shared rules below.

## Rules shared by every route

H. Scroll and selection only inspect existing data. They never write status, approve a stage, mark a message read, commit OCR, sign a checkpoint, run replay, or retry delivery. Those remain explicit existing actions.
I. An absent source produces an explicit unavailable/empty state. No filler objects. A bounded visual subset states its limit; full operational lists remain below.
J. Reduced motion keeps every record available with a stationary presentation. Standard view/no WebGL shows the same labelled records. All selections are native keyboard-operable buttons. Background rendering never owns scroll or blocks forms.

Colours encode recorded state, never scroll progress. Champagne identifies available evidence; amber is current/attention; muted mocha is pending/unknown. Inspection focus is an outline, not a success colour. Descriptions and labels accompany every colour.

## Institution overview
A. Understand each application's current position and open its case.
B/C. `/applications`: id, category, status, current_stage, route[].stage; existing deadline lookup supplies due_date, rule_id, status and application id.
D/F. A branching 2D workflow atlas: one labelled lane per actual application, one stop per returned route stage. Drafts have no fabricated route. Current stage has an explicit pointer. Upcoming obligations use actual dates.
E. 0% complete scope; 25% first application; 50% middle lane; 75% last lane; 100% settle on figures and due list. Movement highlights the inspected lane, not completion.
G. Select a lane, inspect status, open the selected case using its real id.
H/I/J. Shared rules. Unknown stage is explicitly unknown. Missing deadlines remain unavailable/empty.

## Application list
A. Choose a real case.
B/C. Same application records, category, id, status, current_stage and route.
D/F. A portfolio of case dossiers with route summaries, rather than a fake multi-case corridor.
E. Reveal dossiers in dataset order, settle at existing list/create controls.
G. Select/open an existing case; create/submit through existing explicit actions.
H/I/J. Shared rules. No implied sequence connecting different applications.

## Application detail / approval route
A. Understand the selected case's prescribed route and recorded position.
B/C. `/applications/:id`: route[].stage/when, current_stage, status; `/cases/:id/timeline`: event_type, seq, at, role; `/deadlines?subject_id=:id`: due_date, rule_id, status, explanation. The timeline does not necessarily expose per-stage timestamps or completion outcomes.
D/F. A bronze corridor with exactly one labelled gateway per returned stage. Current stage illuminated amber; earlier route positions labelled “Before current · completion not supplied” unless explicit completion evidence exists. Conditional stages remain conditional. No invented deficiency branch: a returning path requires explicit transition data, which this adapter currently lacks.
E. 0% corridor overview; 25/50/75% camera advances among real gateways; 100% last prescribed gateway, with unchanged status. Reversing scroll retraces the view. On-screen detail follows inspection focus.
G. Gateway hotspot and list button focus the actual stage. Existing workflow list, case timeline and deadline details remain.
H/I/J. Shared rules. No route for draft. No invented stage-specific timestamp/deadline association; available case-wide dates are separately labelled.

## Bureau dashboard
A. Compare actual regional workload within available scope.
B/C. `/analytics/dashboard`: scope.region/as_of, sections applications.data.by_region, by_stage, by_status; section status/source.
D/F. An architectural sectional chart: one labelled regional span per supplied region. Its width is proportional to the supplied count; a numeric label is authoritative. Overall status totals are explicitly scope-wide, not falsely attributed to the selected region.
E. Whole scope → focus a supplied region → inspect its count → reach operational statistics.
G. Select a regional span. No region navigation/data fetch is invented.
H/I/J. Shared rules. One region means one span. Unavailable section means no geometry.

## Officer dashboard
A. Understand recorded case age, not a fabricated priority queue.
B/C. Dashboard scope.region and ageing.data.buckets. No individual officer work queue is exposed here.
D/F. A tiered review register, one tier per returned age bucket, labelled with counts. Length encodes quantity. It is explicitly an aggregate, not a list of assigned cases or an urgency ranking.
E. Scope → each age category → source note → available operational figures.
G. Inspect a tier; use existing controls below. Never infer overdue from age alone.
H/I/J. Shared rules; no invented actionable queue.

## Fact review
A. Enter an independent reading, then compare it with the machine reading, then decide; a second officer confirms.
B/C. `/documents` (clean versions only), `/document-versions/:id/facts`: field_key, status, page_number, suggestion_visible, reviewed_value, reviewed_by; the machine reading only from `/document-facts/:id/entry` (or `/reveal`) or when the server marks it visible.
D/F. A 2D fact register: one record per extracted fact, carrying only its field, page and review state. No machine value ever enters the register. No page surface is drawn: the backend serves no page images yet.
E. Register overview → focused fact → settle at the reading controls. Scroll never commits, reveals, reviews or confirms.
G. Choose a version; enter reading; review decision (accept/correct/reject, note); confirm (different officer). Auditors read only.
H/I/J. Shared rules. Extraction without a configured text reader says so plainly. The four-eyes refusal is shown as a rule.

## Documents
A. Follow each checklist document and version through the malware scan; institutions upload.
B/C. `/applications/:id/documents` (institution) or `/documents` (officers): doc_type, versions[].version_no/original_filename/scan_status/uploaded_at/scanned_at, current_version_id.
D/F. One record per checklist document; colour from the newest version's scan state (pending = attention, infected = broken). Each scan state is explained in words beside its badge.
E. Register → focused document → upload form and version list.
G. Upload (Idempotency-Key per upload, reused on retry); rescan a pending version; institutions open confirmed facts only.
H/I/J. Shared rules. No download link: the backend has none.

## Alerts
A. See deadline alerts addressed to the role, their ladder level and status, and acknowledge.
B/C. `/alerts`: level, role, status, reason, template, raised/escalated/acknowledged_at, subject_id, region.
D/F. One record per raised alert level; escalated reads as broken, acknowledged as checked, vacant as unknown.
E. Register → focused alert → list with actions.
G. Acknowledge only where the alert's role is the caller's; demo mode adds "Run timers now" beside time travel.
H/I/J. Shared rules. Scroll never acknowledges.

## Audit
A. Distinguish hash continuity, independent anchoring, and replay consistency.
B/C. `/ledger/verify` response checked/ok/first_bad_seq; `/audit/verify` status/assurance/checkpoint_seq/entries_after_checkpoint; `/audit/checkpoints` actual records; local replay response from explicit `/audit/replay` action. No full ledger-event endpoint is available to this view.
D/F. Three separate evidence stations: chain summary, checkpoint assurance, replay result. Actual checkpoint records are additional labelled anchors, with pending publication explicit. Do NOT generate event #1..N from checked count.
E. History coverage summary → independent witness → checkpoint coverage → replay station. No connection is drawn claiming one assurance proves another.
G. Inspect stations; existing replay/sign/publish actions remain separate and role-restricted.
H/I/J. Shared rules; unchecked/not-run/incomplete/failure displayed verbatim. No invented event chronology or implied full coverage.

## Compliance
A. Inspect letters, the obligations they create, and the evidence that meets them.
B/C. `/compliance/letters`, `/compliance/obligations` (kind, due_date, status, source_status, source_clause, state_origin), `/compliance/obligations/:id` with evidence[].
D/F. Evidence archive sections: one compartment per recorded obligation, labelled with kind and due date; the evidence tab shows its status only once evidence exists.
E. Index → focused obligation → detail with evidence → existing tables.
G. Open an obligation; institutions submit one clean version as evidence; officers accept or reject with a reason code; bureau registers letters.
H/I/J. Shared rules; opening never approves evidence; only an officer's acceptance meets an obligation.

## EVC preview
A. Compare candidate dates and coordination information.
B/C. EVC_SAMPLE: request, institution, slot, experts, conflicts.
D/F. A dated 2D schedule axis, positions proportional to parsed sample slot timestamps (explicit IST); labelled sample candidates, expert counts, conflicts. No identities or confirmations invented.
E. Full date range → earlier slot → later slot → coordination table.
G. Inspect slot; approve stays disabled.
H/I/J. Shared rules; invalid dates use an undated list, not arbitrary timeline placement.

## Inbox
A. Understand each recorded notification's source category and read state.
B/C. `/notifications/inbox`: id, template, created_at, read_at and subject fields when present.
D/F. Source-to-message diagram: template category connects to its actual notification card. If specific triggering event/application linkage is absent, say so. Unread is a label and emphasis, never a simulated delivery.
E. Available groups → inspect unread/read record → practical inbox.
G. Select record and open its existing details. Mark-read remains the explicit existing action.
H/I/J. Shared rules; no guessed provenance.

## Delivery
A. Understand recorded message outcomes and actual attempts.
B/C. `/notifications/outbox`: id/template/channel/status/attempts/created_at/last_error; selected `/outbox/:id/attempts`: attempt_no/outcome/provider/error_category/finished_at.
D/F. Independent message lanes, each terminating at its currently reported state. After selecting Attempts, render discrete recorded attempt nodes ordered by attempt number, with actual outcome/time. Never connect pending to delivered as an inferred event.
E. Outbox scope → selected message → recorded attempts → explicit retry controls.
G. Select a message; request its attempts with existing read API. Requeue retains confirmation and role restriction.
H/I/J. Shared rules; zero attempts is zero nodes; no endless retry pulse or fake historical states.

## Deadlines (embedded overview/case)
A. Understand recorded due dates and responsibility.
B/C. Existing deadlines array: id, due_date, status, clock_kind, rule_id, explanation; application.submitted_at when present.
D/F. A horizontal calendar-date axis with exact relative positions for available due dates; submitted marker only when timestamp supplied. Explicit demo/source explanations retained. Do not invent start date or statutory duration.
E. Overview → earliest date → latest date → explanations. Focus only, no clock advancement.
G. Inspect labels and existing explanations/open-case controls.
H/I/J. Shared rules; one date yields one marker with exact text and no invented elapsed fraction.

## Scorecard
A. Inspect what was measured, evidence and uncertainty.
B/C. analytics/scorecard.items: key/title/kind/result/note/source/ruleset; existing outcomeTone logic.
D/F. An evidence matrix/instrument panel: one row per category, measurement method separate from outcome; no numeric gauge without a numeric result. NOT_EVALUATED remains untested.
E. Categories → method → recorded result → underlying evidence cards.
G. Inspect a category; existing result details remain.
H/I/J. Shared rules, null result shows note, never pass.

## Transitions
Preserve current navigation/history/focus lifecycle. Opening a known case uses a restrained dossier-to-route entrance keyed to actual case selection. Unrelated navigation uses a short dissolve/vertical shift. Do not invent OCR, audit or delivery links between records whose linkage is not available.
