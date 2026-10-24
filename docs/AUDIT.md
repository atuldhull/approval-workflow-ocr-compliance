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
| `NO_TRUSTED_CHECKPOINT` | Chain verifies, but a rebuilt chain or a cut-off tail cannot be ruled out |
| `CHAIN_BROKEN` | An event or link does not verify (`first_bad_seq` says where) |
| `TRUNCATED` | The newest entries recorded in the checkpoint are gone |
| `ENTRIES_DELETED` | Entries up to the checkpoint are missing |
| `HISTORY_REWRITTEN` | The chain was recomputed: its head no longer matches the checkpoint |
| `INVALID_SIGNATURE` / `UNTRUSTED_KEY` | The checkpoint itself cannot be trusted |

The ledger is never signed if it does not verify first.

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

| Projection | Events | Compared | Not compared (no event yet) |
|---|---|---|---|
| `applications` (analytics) | `wf.application_created` v1, `wf.application_submitted` v1 | institution, category, year, status, current stage, ruleset | stage changes after submission, decisions |
| `deadlines` (analytics) | `dl.deadline_opened` v1 | subject, rule, clock kind and owner, due date | MET / BREACHED / paused / extended |

The report lists event types no projector handles and event versions a projector does not understand
(`INCOMPLETE`), instead of claiming full coverage.

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
