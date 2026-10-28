# Scanner value for the demo seed's own files — three-way approval request

Date: 28 October 2026. P2. Status: **approved by Person 1, Person 2 and Person 3 on 2026-10-28**. The schema change is committed on its own so it can be reviewed, approved or reverted independently of the seed.

## Why this is needed

The demo seed now records document validity (lease deed, fire safety and structural stability certificates) on the approved demo cases. A validity record needs a document version that passed the malware scan, and the default demo stack runs without ClamAV (it is the optional `scanning` profile and takes minutes to load its signatures). The seed therefore checks the synthetic PDFs it builds itself, and the scan event must say so honestly rather than claim `clamav`.

## Event schema (`contracts/events/doc/document_scanned.v1.json`)

```text
scanner: enum ["clamav"]  ->  enum ["clamav", "demo_seed"]
```

Additive: every stored event stays valid. `demo_seed` is written only by `app.compliance.demo_seed`, which runs only with `DEMO_MODE=true` and passes only files whose SHA-256 matches a PDF it generated in the same run; any other file stays `scan_pending` for the real scanner. Uploads made through the UI are unaffected.

## Impact if refused

Reverting the enum means the seed cannot create validity records without ClamAV; the document validity panel would start empty on a fresh demo stack.
