"""Signed checkpoints, tamper detection against them, redaction, and side-effect-free replay."""
import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import func, select, text

from app.platform import audit, replay
from app.platform.audit import MemoryWitness, Signer, create_checkpoint
from app.platform.db import get_engine, new_session, unit_of_work
from app.platform.ledger import Ledger, entry_hash, event_hash, GENESIS
from app.platform.models import CaseNote, DomainEvent, LedgerEntry, Outbox, PersonalData
from app.platform.records import Notes, PersonalStore, erase_personal, redact_note
from app.platform.replay import EventRecord
from conftest import SUNRISE, headers
from contracts.enums import Role
from contracts.types import EventIn, Principal

INST = headers("INSTITUTION", SUNRISE)
AUDITOR = headers("AUDITOR", user="00000000-0000-4000-9000-000000000003")
KEY_A, KEY_B = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
SIGNER_A, SIGNER_B = Signer("key-a", KEY_A), Signer("key-b", KEY_B)
TRUSTED = {"key-a": KEY_A.public_key(), "key-b": KEY_B.public_key()}


def submit_one(client):
    app_id = client.post("/api/applications", headers=INST, json={
        "institution_id": str(SUNRISE), "category": "NEW_PROGRAMME", "academic_year": "2027-28"}).json()["id"]
    client.post(f"/api/applications/{app_id}/submit", headers=INST)
    return app_id


def sql(statement):
    with get_engine().begin() as c:
        c.execute(text(statement))


def check(witness, trusted=TRUSTED):
    with new_session() as s:
        return audit.verify(s, trusted, witness)


def checkpoint(signer=SIGNER_A, witness=None):
    witness = witness or MemoryWitness()
    with new_session() as s:
        create_checkpoint(s, signer, witness)
    return witness


def rebuild_chain():
    """What an attacker with database access would do after editing history: recompute every hash."""
    with new_session() as s:
        prev = GENESIS
        for ev in s.scalars(select(DomainEvent).order_by(DomainEvent.seq)):
            entry = s.get(LedgerEntry, ev.seq)
            entry.event_hash = event_hash(ev)
            entry.prev_hash, entry.entry_hash = prev, entry_hash(prev, entry.event_hash)
            prev = entry.entry_hash
        s.commit()


# ---- checkpoints ----

def test_untouched_ledger_matches_its_checkpoint(client):
    submit_one(client)
    r = check(checkpoint())
    assert (r.ok, r.status, r.checkpoint_seq, r.entries_after_checkpoint) == (True, "VERIFIED", 3, 0)


def test_without_a_trusted_checkpoint_the_limitation_is_stated(client):
    submit_one(client)
    r = check(None)
    assert r.ok and r.status == "NO_TRUSTED_CHECKPOINT" and "cannot be ruled out" in r.detail


def test_modified_event_is_detected(client):
    submit_one(client)
    w = checkpoint()
    sql("UPDATE plat.domain_event SET payload = jsonb_set(payload, '{category}', '\"MERGER\"') WHERE seq = 1")
    r = check(w)
    assert (r.ok, r.status, r.first_bad_seq) == (False, "CHAIN_BROKEN", 1)


def test_missing_ledger_row_is_detected(client):
    submit_one(client)
    sql("DELETE FROM plat.ledger_entry WHERE seq = 2")
    r = check(MemoryWitness())
    assert (r.status, r.first_bad_seq) == ("CHAIN_BROKEN", 2) and "no ledger entry" in r.detail


def test_reordered_events_are_detected(client):
    submit_one(client)
    w = checkpoint()
    with new_session() as s:
        a, b = s.get(DomainEvent, 1), s.get(DomainEvent, 2)
        a.payload, b.payload = b.payload, a.payload
        a.event_type, b.event_type = b.event_type, a.event_type
        s.commit()
    r = check(w)
    assert (r.status, r.first_bad_seq) == ("CHAIN_BROKEN", 1)


def test_deleted_newest_entries_are_detected_only_with_a_checkpoint(client):
    submit_one(client)
    w = checkpoint()
    sql("DELETE FROM plat.ledger_entry WHERE seq = 3")
    sql("DELETE FROM plat.domain_event WHERE seq = 3")
    with new_session() as s:
        assert Ledger().verify(s).ok                     # the shortened chain is internally consistent...
    r = check(w)
    assert (r.ok, r.status, r.first_bad_seq) == (False, "TRUNCATED", 3)   # ...but the checkpoint says otherwise


def test_a_rebuilt_chain_is_detected(client):
    submit_one(client)
    w = checkpoint()
    sql("UPDATE plat.domain_event SET payload = jsonb_set(payload, '{category}', '\"MERGER\"') WHERE seq = 1")
    rebuild_chain()
    with new_session() as s:
        assert Ledger().verify(s).ok
    r = check(w)
    assert (r.ok, r.status) == (False, "HISTORY_REWRITTEN")


def test_a_forged_checkpoint_fails_its_signature(client):
    submit_one(client)
    w = checkpoint()
    forged = json.loads(w.items[-1]["statement"])
    forged["head_seq"] = 2
    w.items[-1]["statement"] = json.dumps(forged, sort_keys=True, separators=(",", ":"))
    assert check(w).status == "INVALID_SIGNATURE"


def test_wrong_or_unknown_public_key_is_refused(client):
    submit_one(client)
    w = checkpoint()
    assert check(w, {"key-a": Ed25519PrivateKey.generate().public_key()}).status == "INVALID_SIGNATURE"
    assert check(w, {"key-b": KEY_B.public_key()}).status == "UNTRUSTED_KEY"


def test_key_rotation_keeps_verifying(client):
    app_id = submit_one(client)
    w = checkpoint(SIGNER_A)
    client.post(f"/api/applications", headers=INST, json={
        "institution_id": str(SUNRISE), "category": "NEW_PROGRAMME", "academic_year": "2028-29"})
    checkpoint(SIGNER_B, w)                                    # new key from here on
    assert check(w).status == "VERIFIED" and check(w).checkpoint_key_id == "key-b"
    w_old = MemoryWitness()
    w_old.items = w.items[:1]
    assert check(w_old).status == "VERIFIED"                   # old checkpoints still verify with the old key
    assert app_id


def test_a_broken_ledger_is_never_signed(client):
    submit_one(client)
    sql("UPDATE plat.domain_event SET payload = '{}' WHERE seq = 2")
    with pytest.raises(ValueError, match="refusing to sign"):
        checkpoint()


def test_redacting_notes_and_erasing_personal_data_keeps_the_chain_valid(client):
    system = Principal(uuid4(), Role.BUREAU_HEAD)
    with unit_of_work(system) as uow:
        note_ref, note_hash = Notes().create(uow, "Observation text that will later be redacted")
        personal_ref = PersonalStore().store(uow, {"name": "Synthetic Person"}, "contact")
        Ledger().append(uow, EventIn("application", uuid4(), "wf.application_created",
                                     {"application_id": str(uuid4()), "institution_id": str(SUNRISE),
                                      "category": "NEW_PROGRAMME", "academic_year": "2027-28"},
                                     note_ref=note_ref, note_hash=note_hash, personal_ref=personal_ref))
    w = checkpoint()
    with new_session() as s:
        redact_note(s, note_ref)
        erase_personal(s, personal_ref)
        s.commit()
        note = s.get(CaseNote, note_ref)
        assert note.body is None and note.body_hash == note_hash      # the anchored hash survives redaction
        assert s.get(PersonalData, personal_ref).data is None
    assert check(w).status == "VERIFIED"


def test_witness_file_is_append_only_json_lines(tmp_path, client):
    submit_one(client)
    w = audit.LocalFileWitness(str(tmp_path))
    checkpoint(SIGNER_A, w)
    checkpoint(SIGNER_A, w)
    lines = (tmp_path / "checkpoints.jsonl").read_text().splitlines()
    assert len(lines) == 2 and json.loads(lines[-1]) == w.latest()


# ---- replay ----

def test_replay_matches_the_live_tables(client):
    submit_one(client)
    report = replay.replay()
    assert report["ok"], report
    by_name = {p["name"]: p for p in report["projections"]}
    assert by_name["applications"]["status"] == "MATCH" and by_name["applications"]["records"] == 1
    assert by_name["deadlines"]["status"] == "MATCH" and by_name["deadlines"]["events_applied"] == 1
    assert report["unhandled_event_types"] == {}


def test_replay_reports_a_deliberate_mismatch_field_by_field(client):
    app_id = submit_one(client)
    sql(f"UPDATE wf.application SET status = 'APPROVED' WHERE id = '{app_id}'")
    report = replay.replay(["applications"])
    p = report["projections"][0]
    assert not report["ok"] and p["status"] == "MISMATCH"
    assert p["differences"] == [{"key": app_id, "field": "status", "replayed": "IN_PROCESS", "live": "APPROVED"}]


def test_replay_is_deterministic(client):
    submit_one(client)
    assert replay.replay() == replay.replay()


def test_replay_has_no_side_effects_and_cannot_write(client):
    submit_one(client)
    with new_session() as s:
        before = (s.scalar(select(func.count()).select_from(Outbox)),
                  s.scalar(select(func.count()).select_from(DomainEvent)))
    replay.replay()
    with new_session() as s:
        after = (s.scalar(select(func.count()).select_from(Outbox)),
                 s.scalar(select(func.count()).select_from(DomainEvent)))
    assert before == after

    class Sneaky:
        name, owner, compared_fields = "sneaky", "test", ()
        handles = frozenset({("wf.application_created", 1)})

        def apply(self, state, ev):
            pass

        def live(self, session):
            session.execute(text("INSERT INTO plat.case_note (id, body_hash) VALUES (gen_random_uuid(), 'x')"))

    replay.register(Sneaky())
    try:
        with pytest.raises(Exception, match="read-only"):
            replay.replay(["sneaky"])
    finally:
        replay._projectors.pop("sneaky")


def test_unknown_versions_and_unhandled_events_are_reported_not_ignored(client):
    now = datetime.now(timezone.utc)
    aid = str(uuid4())
    events = [
        EventRecord(1, now, "application", uuid4(), "wf.application_created", 1,
                    {"application_id": aid, "institution_id": str(SUNRISE), "category": "X", "academic_year": "2027-28"}),
        EventRecord(2, now, "application", uuid4(), "wf.application_submitted", 2, {"application_id": aid}),
        EventRecord(3, now, "evc_request", uuid4(), "evc.slot_assigned", 1, {}),   # a future event type
    ]
    report = replay.replay(["applications"], events=events)
    p = report["projections"][0]
    assert p["skipped_versions"] == {"wf.application_submitted.v2": 1}
    assert report["unhandled_event_types"] == {"evc.slot_assigned": 1}


# ---- API access ----

def test_audit_endpoints_are_for_oversight_and_return_no_payloads(client):
    submit_one(client)
    assert client.get("/api/audit/verify", headers=INST).status_code == 403
    assert client.post("/api/audit/replay", headers=INST).status_code == 403
    r = client.get("/api/audit/verify", headers=AUDITOR).json()
    assert r["status"] == "NO_TRUSTED_CHECKPOINT" and "payload" not in r
    assert client.post("/api/audit/replay", headers=AUDITOR).json()["ok"] is True
    # signing is not configured in tests: a clear 503, not a fake success
    head = headers("BUREAU_HEAD", user="00000000-0000-4000-9000-000000000007")
    assert client.post("/api/audit/checkpoints", headers=head).status_code == 503
    assert client.post("/api/audit/checkpoints", headers=AUDITOR).status_code == 503
    assert client.post("/api/audit/checkpoints", headers=headers("BUREAU_OFFICER")).status_code == 403
