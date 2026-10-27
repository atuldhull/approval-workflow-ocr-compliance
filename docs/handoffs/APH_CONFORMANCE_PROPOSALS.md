# APH conformance: proposals for discussion

**These are proposals, not agreed work.** They come from a clause-by-clause read of the Approval Process Handbook
2024-27 against the latest pushed `person-1` (`f6f597c`) and `person-2` (`a9db919`) branches on 25 Oct 2026, read-only.
Nothing here changes anyone's files or work pack; the team decides what to take, and when.

Sources and evidence labels are in `AICTE_INTEGRATION_READINESS.md`.

## Person 1

### P1-1 Executive Committee decision and Council ratification on Chapter II routes
- **Now:** Chapter II routes end at their last committee stage, and a bureau officer issues the LoA, EoA or LoD
  directly. `EC` and `COUNCIL` appear only on `NEW_INSTITUTION`.
- **APH:** the Standing Hearing Committee's recommendations go to the Executive Committee, whose decision is uploaded
  with a speaking order (2.23.3); EC decisions are ratified by the Council (1.10a, 2.25a).
- **Impact:** a letter can be issued with no decision step, so the audit trail cannot show who decided.
- **Smallest change:** a decision step (`EC`) before letters, recording the decision and its speaking-order reference,
  with Council ratification as a recorded event rather than a stage if that fits the grammar better.
- **Contracts:** new or extended `wf.*` event types need all-three approval.
- **Tests:** a letter cannot be issued without a recorded EC decision; the decision event names the decider role.

### P1-2 Appeal path
- **Now:** `appeal:` defines the window (`APPEAL_7D`) and `max_appeals: 1`; there is no SAC stage.
- **APH:** one appeal to the Council within 7 days of upload of the decision (2.24a; Chapter I: from issue of the LoD,
  1.11a), heard by the Standing Appellate Committee, which may recommend, not recommend, or send the case back for
  scrutiny or an expert visit before a second SAC hearing, then a final Council decision (1.11d, 2.24).
- **Smallest change:** `SAC` as an appeal-only stage with an optional loop back to `SCRUTINY` or `EVC`, ending in a
  Council decision; the 7-day window must be open to file.
- **Tests:** an appeal after 7 days is refused; a second appeal is refused; an SAC referral back to EVC returns to SAC.

### P1-3 Deficiency is not rejection; add rejection with a speaking order
- **Now:** `issue_lod` moves the case to `REJECTED`, a terminal state. There is no LoR.
- **APH:** letters are LoA, LoD or LoR, and an LoR carries a speaking order with reasons (1.10b). An institution may
  appeal an LoD (1.11a).
- **Impact:** the system shows a deficiency as a final rejection and leaves no room for the appeal the handbook grants.
- **Smallest change:** a non-terminal `DEFICIENCY_ISSUED` outcome for LoD (appealable), and `issue_lor` → `REJECTED`
  requiring a speaking-order reference.
- **Tests:** an LoD leaves the case appealable; an LoR without reasons is refused.

### P1-4 Region-filtered case list
- **Now:** `GET /applications` returns 403 to regional officers (by design until it can filter).
- **Smallest change:** filter by the principal's region before returning; the platform policy already scopes regional
  access per case.
- **Tests:** a Southern officer sees only Southern cases; a forged region claim is refused (the token validation
  already rejects malformed region claims).

### P1-5 Official identifiers (only when an authorised source exists)
- **Proposal:** nullable `aicte_permanent_id` on institutions and `aicte_application_id` on applications, set only by
  an authorised import, never typed in and never generated. Formats seen on letters: `1-` followed by digits.
- **Contracts:** yes (case context and events).

## Person 2

### P2-1 Deposit penalty and withdrawal
- **Now:** `DEPOSIT_15D` has `penalty_tiers` marked "suggestion only"; nothing happens after 31 July.
- **APH 2.25(f):** proof of deposit plus Affidavit 3 within 15 days of intimation, else a 10% penalty up to 31 May and
  20% up to 31 July of the calendar year, "beyond which the approval shall be withdrawn". New programmes for
  Government institutions need no deposit (2.25e).
- **Smallest change:** mark the tiers as verified with clause 2.25(f), and add an expiry outcome that raises a
  withdrawal alert for the bureau (the decision itself stays with Person 1's workflow).
- **Tests:** penalty tier by date; withdrawal alert after 31 July; Government institutions exempt.

### P2-2 LoA validity
- **APH 1.10b(ii):** an LoA for a new institution is valid for two academic years for affiliation and state
  requirements, then stands cancelled; such institutions apply for EoA from the next year regardless.
- **Smallest change:** an obligation on LoA registration with a two-academic-year expiry and reminders.

### P2-3 Public notice and academic calendar
- **Now:** `AICTE_PROCESSING` (30 days) and `INSTITUTION_RESPONSE` (15 days) are labelled demo assumptions. Versioned
  working-day calendars now exist (`a9db919`) but hold holidays, not AICTE's dates.
- **APH:** processing periods are "as per Public Notice Period" (Table 2.2), and no EoA may be granted after the
  academic calendar's last date (2.25j). For 2026-27, the original calendar (approval by 30 Apr) was revised after
  the Supreme Court extended the time for grant of approval to 14 Sep 2026 (order of 12 Aug 2026).
- **Smallest change:** a versioned "approval calendar" record per academic year (each date with its source document
  and the revision it superseded), and deadlines that name the version they used.
- **For the frontend:** add the calendar version to the deadline API response so the case screen can show it (today
  it says "Calendar version: not supplied by the deadline service"). Shared contract: yes.

### P2-4 EoA deficiency window
- **Now:** `EOA_DEFICIENCY_6M` (verified from letter text) is right; real EoA letters say "complied within Six Months
  from the date of issue of this EoA". APH 2.25(c) adds that deficiencies must be met before the next EoA. Keep both.

### P2-5 Letter fields
- **Proposal:** when `cmp.approval_letter` is built, store the file number, date of approval, letter type, intake
  table and deficiency block as on real letters, plus the source reference. Generate nothing that imitates an AICTE
  letter; samples are marked as samples.

## Shared contracts (all three)

| Change | Needed by |
|---|---|
| Decision, appeal and LoR events (P1-1 to P1-3) | P1, read by P2 and P3 |
| Official identifiers in case context (P1-5) | P1, P2, P3 |
| Calendar version on `DeadlineOut` (P2-3) | P2, shown by P3 |
| Imported-event provenance fields (external source, id, version, payload hash) | Any future connector |
| C5: checkpoint publication fields in `openapi.json` (already proposed, `docs/proposals/`) | P3 |
