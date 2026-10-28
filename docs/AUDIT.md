# Audit: hash chain, signed checkpoints, replay

## What each layer proves

| Layer | Detects | Cannot detect alone |
|---|---|---|
| Hash chain (`plat.ledger_entry`, `GET /api/ledger/verify`) | An edited, missing or reordered event anywhere before the newest entry | The whole chain rebuilt with fresh hashes; the newest entries cut off |
| Signed checkpoint + witness (`GET /api/audit/verify`) | Both of the above, for everything up to the checkpoint | Changes after the latest checkpoint (until the next one) |
| Replay (`POST /api/audit/replay`) | Read models that disagree with the events | Anything the events do not describe |

A checkpoint is integrity evidence for this system. **It is not a legal or digital signature** on any approval.

## Checkpoints (`backend/app/platform/audit.py`)

A checkpoint is a canonical JSON statement (ledger head seq, head entry hash, entry count, time, key id, ruleset
revisions in use) signed with Ed25519. The copy that counts goes to a **witness** outside the database.
`LocalFileWitness` (append-only JSON lines in `AUDIT_WITNESS_DIR`) is the demo witness. A real deployment would use
storage the database administrators cannot rewrite.

Verification trusts only:

- the witness copy (never `plat.checkpoint`, which is a convenience copy), and
- public keys from `AUDIT_TRUSTED_KEYS_FILE` (configuration, never the database).

| Status | Meaning |
|---|---|
| `VERIFIED` | Chain verifies and matches the latest trusted checkpoint |
| `NO_TRUSTED_CHECKPOINT` | Chain verifies, but a rebuilt chain or a cut-off tail cannot be ruled out (`assurance: CHAIN_ONLY`) |
| `WITNESS_UNAVAILABLE` | The witness cannot be read right now; nothing is claimed about the checkpoint |
| `WITNESS_CORRUPT` | The witness answered, but its latest entry is not a checkpoint copy |
| `CHAIN_BROKEN` | An event or link does not verify (`first_bad_seq` says where) |
| `TRUNCATED` | The newest entries recorded in the checkpoint are gone |
| `ENTRIES_DELETED` | Entries up to the checkpoint are missing |
| `HISTORY_REWRITTEN` | The chain was recomputed: its head no longer matches the checkpoint |
| `INVALID_SIGNATURE` / `UNTRUSTED_KEY` | The checkpoint itself cannot be trusted |

The ledger is never signed if it does not verify first. Every report carries `assurance`: `CHECKPOINTED` (anchored by a
trusted checkpoint through the latest entry), `CHECKPOINTED_WITH_NEWER_ENTRIES` (anchored up to the checkpoint; the
newest entries rely on the chain alone until the next checkpoint), `CHAIN_ONLY` (no checkpoint to compare with) or
`NONE` (a check failed).

### Publication (database and witness cannot commit together)

1. The statement is signed and the checkpoint row is committed as `PENDING`. If this commit fails, nothing was published.
2. Exactly that signed copy is handed to the witness, then the row becomes `PUBLISHED`. The witness accepts an
   identical retry, and refuses anything that would create a competing trusted history: a different copy under an
   existing id, a different head hash for an entry it already vouches for, or a head older than its latest.

A witness outage or a crash between the steps leaves a `PENDING` row. `POST /api/audit/checkpoints/publish` or
`python -m app.platform.audit publish` hands over the same copy again; it is never re-signed, so the trusted
history cannot fork. While a checkpoint is pending, no new one can be signed. Reports show the number of
unpublished checkpoints.

`LocalFileWitness` is **DEMO ONLY**: it sits on the same machine as the database. For independent storage,
`python -m app.platform.audit export checkpoints.jsonl` writes every published copy; each verifies on its own
signature, so it can go to a write-once bucket, another organisation, or print.

### Keys

```bash
python scripts/gen_audit_key.py demo-2026-10        # writes .secrets/ (git-ignored) and prints the settings
python -m app.platform.audit checkpoint             # from backend/ with PYTHONPATH=..;.
python -m app.platform.audit verify
```

Rotation: create a new key id and switch `AUDIT_SIGNING_KEY_*` to it. Keep the old public key in the trusted file so
older checkpoints still verify. Private keys are never committed; in a real deployment they live in a secret store.

### Redaction

Free text lives in `plat.case_note` and personal fields in `plat.personal_data`; events hold only references and
the note's hash. `redact_note` and `erase_personal` (`records.py`) remove the content and keep the hash, so the chain
and checkpoints still verify and the anchored note hash still proves what the note said.

## Replay (`backend/app/platform/replay.py`)

Owners register projectors for their events (`replay.register` in their `wiring.py`). Replay folds all events in
seq order inside a **READ ONLY** transaction, so it cannot write, queue notifications or call providers. It compares
the result with the live tables field by field and returns machine-readable differences.

| Projection | Events | Compared |
|---|---|---|
| `applications` (analytics) | `wf.application_created`, `wf.application_submitted` v1/v2, `wf.transition_applied`, `wf.stage_entered`, `wf.stage_exited` | institution, category, year, status, current stage, ruleset |
| `deadlines` (analytics) | `dl.deadline_opened`, `dl.deadline_paused`, `dl.deadline_resumed`, `dl.deadline_breached`, `dl.deadline_closed` | subject, rule, clock kind and owner, due date, due version, status |
| `deficiencies` (analytics) | `wf.deficiency_recorded`, `wf.deficiency_item_responded`, `wf.compliance_submitted`, `wf.deficiency_item_decided`, `wf.deficiency_closed`, `wf.deficiency_superseded` | case, round, status, the state of every item |
| `committees` (analytics) | `wf.committee_formed`, `wf.task_assigned`, `wf.observation_added`, `wf.report_version_added` | case, type, members; per task its committee, assignee, title and observation count; report versions |
| `evc` (analytics) | `evc.request_created`, `evc.assignment_proposed`, `evc.assignment_published`, `evc.schedule_discarded`, `evc.request_completed`, `evc.request_cancelled` | case, status, due by, deadline |
| `compliance` (analytics) | `cmp.letter_registered`, `cmp.obligation_created`, `cmp.evidence_submitted`, `cmp.evidence_verified` | letter type; obligation kind, status, deadline, due date; evidence status |
| `alerts` (deadlines) | `dl.alert_raised`, `dl.alert_escalated`, `dl.alert_acknowledged` | deadline, level, role, due version, status |

Some stored events are deliberately not folded by any projection: checklist item updates, the EVC expert pool,
availability, conflicts of interest and proposed runs, and the documents module's uploads, scans and OCR reviews
(`NOT_PROJECTED` in `backend/app/analytics/projections.py`). Replay lists them under `not_projected` with the reason
instead of as unhandled gaps; they are kept and verified by their own modules.

The report gives one `verdict`:

| Verdict | Meaning | `ok` |
|---|---|---|
| `VERIFIED_COMPLETE` | Every stored event was projected and every projection matched a live model | true |
| `CONSISTENT_SUBSET` | Nothing disagreed, but `gaps` lists what was not checked: event types with no projector, unknown versions, projections with no live model, fields that changed without an event | false |
| `MISMATCH` | A projection disagrees with its live model | false |

A projector's `live()` may mark a value as `replay.UNRECORDED` when the live record changed in a way no stored event
describes. That field is skipped for that record and reported as a `CHANGED_WITHOUT_EVENT` gap, so the verdict is at
most `CONSISTENT_SUBSET`. The deadlines projection uses it for clocks whose status, due date or version changed before
the deadline lifecycle events existed (no `dl.deadline_paused/resumed/breached/closed` event for that clock).

Checking nothing is never verification: no projectors selected (`NO_PROJECTORS`), a requested projector that is not
registered (`UNKNOWN_PROJECTOR`) and a projection that compares no fields (`NO_FIELDS_COMPARED`) are all gaps.

`schemas_without_projector` lists event schemas in `contracts/events` that no projector handles yet (read-only input);
they only become gaps once such events are stored. The audit screen shows each layer separately and is green
overall only when the history is anchored through the latest entry and replay is complete. Replay is a
consistency check, not a substitute for a checkpoint: it never lifts a chain-only or partly anchored result.

### Needed from the other modules

- **Person 1:** when stage transitions, deficiencies and decisions become events, extend `ApplicationsProjection`
  (or register your own projector in `workflow/wiring.py`). Same for EVC events.
- **Person 2:** add events for deadline closure, pause, resume and extension (for example `dl.deadline_closed`) so
  deadline status can be replayed and compared, plus projectors for obligations and letters.

## Tests

`backend/tests/test_audit.py`: valid chain, modified event, missing ledger row, reordered events, deleted newest
entries (caught only by the checkpoint), a fully rebuilt chain, a forged checkpoint, wrong and unknown public
keys, key rotation, refusing to sign a broken ledger, redaction and erasure keeping the chain valid, the witness
file format, replay match, a deliberate field-level mismatch, determinism, no side effects (and a projector that
tries to write fails), and reporting of unknown versions and unhandled event types.
