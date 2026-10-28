# SAC appeal, Letter of Rejection, Only-EVC routes and the case summary — three-way approval request

Date: 28 October 2026. P1. Status: **approved by Person 1, Person 2 and Person 3 on 2026-10-28**. The shared changes below are committed on their own so they can be reviewed or reverted independently of the workflow code.

## Why this is needed

APH 2024-27 cl. 1.11(a) (p.25) and cl. 2.24(a) (p.45): an institution aggrieved by the decision may appeal once, within 7 days of the LoD, to the Council; the Standing Appellate Committee (SAC) hears it and recommends, does not recommend, or recommends a Scrutiny Committee / EVC (cl. 1.11(d)); the Council's decision is final (cl. 1.11(e), 2.24(f)). A Letter of Rejection carries a speaking order with the specific reasons (cl. 1.10(b), p.24). Until now `issue_lod` ended the case outright, the `appeal:` block in routes.yaml and the APPEAL_7D rule were never read, and there was no SAC stage. The deadline worker also had no way to act when a clock with an expiry action (APPEAL_7D `on_expiry: close_appeal_window`) is breached.

## Exact changes

- `contracts/enums.py`: `Stage.SAC`. The SAC is open to every route without being part of its plan (routes.yaml `appeal.stage`), so no route stage list changes. `LetterType.LOR` already existed.
- `contracts/events/wf/transition_applied.v1.json`, `stage_entered.v1.json`, `stage_exited.v1.json`, `committee_formed.v1.json`: **additive** enum values only — state `SAC`, committee type `SAC`, actions/outcomes `file_appeal`, `close_appeal_window`, `sac_recommend`, `sac_not_recommend`, `sac_refer_scrutiny`, `sac_refer_evc`, `return_to_sac`, `issue_lor`. Every stored event still validates and every consumer keyed on (type, version 1) keeps reading it, which is why these are not new versions (the payload shape is unchanged).
- New schemas, aggregate `application`, written in the transition's unit of work; every string is a UUID, enum, pattern or const, and grounds / speaking orders travel only as the envelope's note_ref / note_hash:

```text
wf.appeal_window_opened.v1  application_id, appeal_id, lod_letter_ref, deadline_id, rule_id, max_appeals: const 1
wf.appeal_filed.v1          application_id, appeal_id, filed_by, deadline_id
wf.appeal_lapsed.v1         application_id, appeal_id, deadline_id
wf.appeal_recommended.v1    application_id, appeal_id, hearing_no >= 1,
                            recommendation: RECOMMEND | NOT_RECOMMEND | REFER_SCRUTINY | REFER_EVC, report_ref, recommended_by
wf.appeal_decided.v1        application_id, appeal_id, outcome: LOA | EOA | LOR, letter_ref, decided_by,
                            speaking_order_hash: sha-256 hex | null
```

- `contracts/ports.py`: `DeadlineExpiryPort.run_due(limit) -> int`, provided by the workflow (`app.workflow.appeal.Expiry`) and called by the deadline worker after it marks clocks BREACHED; optional (not wired = no-op). `contracts/fakes.py`: `FakeDeadlineExpiry`; `scripts/check_contracts.py` maps the fake.
- Migration `wf_0007` (workflow chain, one head): `wf.appeal` (one row per case, unique on application_id = an appeal lies once) and `SAC` added to `ck_wf_committee_type`.
- `contracts/openapi.json` regenerated with `python scripts/check_contracts.py --write` (Python 3.12): `GET /api/cases/{id}/summary`, `GET /api/cases/{id}/appeal`, `SAC` in the stage enums, the new committee type.

## Behaviour (P1)

`issue_lod` keeps the case at its decision stage (`$current`), registers the LoD and opens APPEAL_7D from its issue date. While the window is open only `file_appeal` (institution, own case, before the clock runs out) or `close_appeal_window` (SYSTEM via the worker once APPEAL_7D is BREACHED, or an officer recording the lapse) can follow. Filing moves the case to SAC; a member of the case's SAC committee records the recommendation citing the SAC's latest report; a referral sends the case back to Scrutiny or EVC and, at the decision stage, `return_to_sac` (never a second LoD) brings it before another SAC hearing. The bureau head records the Council's final decision: LoA / EoA, or `issue_lor` with a mandatory speaking order (protected note). The system records these human decisions and never makes one.

## Policy (P3)

`case.file_appeal` INSTITUTION; `case.close_appeal_window` SYSTEM, BUREAU_OFFICER; `case.sac_*` SCRUTINY_COMMITTEE, BUREAU_OFFICER; `case.return_to_sac` BUREAU_OFFICER; `case.issue_lor` BUREAU_HEAD; BUREAU_HEAD added to `case.issue_loa` / `case.issue_eoa` (the template still limits the ordinary letters to BUREAU_OFFICER). Cerbos policies regenerated.

## Deadlines (P2)

No change to APPEAL_7D (already verified, cl. 2.24(a)). One demo-assumption rule `EVC_NEW_INSTITUTION` (14 calendar days, INTERNAL/COMMITTEE) for the new-institution route's own EVC timeline (routes.yaml `evc_rule_id`); the APH sets no EVC duration. The deadline worker gains `run_expiry_actions()`.

## Impact if refused

Reverting the shared commit removes the SAC stage, the appeal events and the expiry port; the workflow would then refuse to load the appeal templates, so the workflow commit must be reverted with it.
