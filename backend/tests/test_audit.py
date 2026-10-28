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
from backend.tests.intake_test_helpers import ensure_intake_rules, provide_fixture_items
from conftest import SUNRISE, headers
from contracts.enums import Role
from contracts.types import EventIn, Principal

INST = headers("INSTITUTION", SUNRISE)
AUDITOR = headers("AUDITOR", user="00000000-0000-4000-9000-000000000003")
KEY_A, KEY_B = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
SIGNER_A, SIGNER_B = Signer("key-a", KEY_A), Signer("key-b", KEY_B)
TRUSTED = {"key-a": KEY_A.public_key(), "key-b": KEY_B.public_key()}


def submit_one(client):
    ensure_intake_rules(client)
    app_id = client.post("/api/applications", headers=INST, json={
        "institution_id": str(SUNRISE), "category": "NEW_PROGRAMME", "academic_year": "2027-28"}).json()["id"]
    provide_fixture_items(app_id)
    assert client.post(f"/api/applications/{app_id}/submit", headers=INST, json={"dsc_present": True}).status_code == 200
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


def test_a_clock_changed_without_lifecycle_events_is_a_gap_not_a_mismatch(client):
    app_id = submit_one(client)
    # a clock paused and resumed before dl.deadline_paused/resumed existed: date, version and status moved silently
    sql(f"UPDATE dl.deadline SET due_date = due_date + 1, due_version = 2, status = 'PAUSED' "
        f"WHERE subject_id = '{app_id}'")
    r = replay.replay()
    deadlines = {p["name"]: p for p in r["projections"]}["deadlines"]
    assert deadlines["status"] == "MATCH" and deadlines["differences"] == []
    assert deadlines["unrecorded"] == {"due_date": 1, "due_version": 1, "status": 1}
    assert (r["ok"], r["verdict"]) == (False, "CONSISTENT_SUBSET")
    assert {"kind": "CHANGED_WITHOUT_EVENT", "projection": "deadlines", "field": "due_date", "records": 1} in r["gaps"]
    # any other field still has to match
    sql(f"UPDATE dl.deadline SET clock_owner = 'SOMEONE_ELSE' WHERE subject_id = '{app_id}'")
    assert replay.replay(["deadlines"])["verdict"] == "MISMATCH"


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
        EventRecord(2, now, "application", uuid4(), "wf.application_submitted", 3, {"application_id": aid}),
        EventRecord(3, now, "evc_request", uuid4(), "evc.slot_assigned", 1, {}),   # a future event type
    ]
    report = replay.replay(["applications"], events=events)
    p = report["projections"][0]
    assert p["skipped_versions"] == {"wf.application_submitted.v3": 1}
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


# ---- publication is recoverable (P3-09) ----

def count_pending():
    from app.platform.models import Checkpoint
    with new_session() as s:
        return s.scalar(select(func.count()).select_from(Checkpoint).where(Checkpoint.status == "PENDING"))


def test_witness_outage_leaves_a_pending_checkpoint_that_recovery_publishes(client):
    submit_one(client)
    w = MemoryWitness()
    w.fail_next = True
    with pytest.raises(audit.WitnessError):
        checkpoint(witness=w)
    assert w.items == [] and count_pending() == 1
    r = check(w)
    assert (r.status, r.assurance, r.unpublished_checkpoints) == ("NO_TRUSTED_CHECKPOINT", "CHAIN_ONLY", 1)
    with new_session() as s:
        assert len(audit.publish_pending(s, w)) == 1
    assert count_pending() == 0 and len(w.items) == 1
    r = check(w)
    assert (r.status, r.assurance) == ("VERIFIED", "CHECKPOINTED")


def test_failed_database_commit_publishes_nothing(client, monkeypatch):
    submit_one(client)
    w = MemoryWitness()
    with new_session() as s:
        monkeypatch.setattr(s, "commit", lambda: (_ for _ in ()).throw(RuntimeError("database went away")))
        with pytest.raises(RuntimeError):
            create_checkpoint(s, SIGNER_A, w)
    assert w.items == [] and count_pending() == 0


def test_crash_after_publishing_but_before_marking_is_recovered_without_a_second_copy(client, monkeypatch):
    submit_one(client)
    w = MemoryWitness()
    with new_session() as s:
        row = audit.sign_checkpoint(s, SIGNER_A)
        w.publish(audit._copy(row))                      # handed over, then the process dies before marking it
    assert count_pending() == 1
    with new_session() as s:
        audit.publish_pending(s, w)                      # recovery republishes the SAME signed copy
    assert len(w.items) == 1 and count_pending() == 0
    assert check(w).status == "VERIFIED"


def test_no_new_checkpoint_while_one_is_pending(client):
    submit_one(client)
    w = MemoryWitness()
    w.fail_next = True
    with pytest.raises(audit.WitnessError):
        checkpoint(witness=w)
    with pytest.raises(audit.CheckpointPending):
        checkpoint(witness=w)


def test_witness_refuses_to_rewind_history(client):
    submit_one(client)
    w = checkpoint()
    older = json.loads(w.items[0]["statement"])
    older["head_seq"] = 1
    with pytest.raises(audit.WitnessConflict):
        w.publish({"id": str(uuid4()), "statement": json.dumps(older), "signature": "x"})


def test_corrupt_and_unavailable_witnesses_are_reported_as_such(client, tmp_path):
    submit_one(client)
    lw = audit.LocalFileWitness(str(tmp_path))
    checkpoint(witness=lw)
    with lw.path.open("a") as f:
        f.write("{not json\n")
    r = check(lw)
    assert (r.ok, r.status) == (False, "WITNESS_CORRUPT")

    class Down:
        kind = "test"

        def latest(self):
            raise audit.WitnessError("connection refused")

    r = check(Down())
    assert (r.ok, r.status, r.assurance) == (False, "WITNESS_UNAVAILABLE", "NONE")


def test_local_file_witness_is_labelled_demo_only(tmp_path):
    assert "DEMO ONLY" in audit.LocalFileWitness(str(tmp_path)).kind


def test_export_contains_only_published_copies_that_verify_on_their_own(client):
    submit_one(client)
    checkpoint()
    w = MemoryWitness()
    w.fail_next = True
    client.post("/api/applications", headers=INST, json={
        "institution_id": str(SUNRISE), "category": "NEW_PROGRAMME", "academic_year": "2028-29"})
    with pytest.raises(audit.WitnessError):
        checkpoint(witness=w)
    with new_session() as s:
        exported = audit.export_checkpoints(s)
    assert len(exported) == 1
    stmt = exported[0]["statement"].encode()
    KEY_A.public_key().verify(__import__("base64").b64decode(exported[0]["signature"]), stmt)


def test_checkpoint_api_reports_pending_and_recovers(client, monkeypatch):
    submit_one(client)
    w = MemoryWitness()
    monkeypatch.setattr(audit, "configured_witness", lambda: w)
    monkeypatch.setattr(audit, "configured_signer", lambda: SIGNER_A)
    head = headers("BUREAU_HEAD", user="00000000-0000-4000-9000-000000000007")
    w.fail_next = True
    r = client.post("/api/audit/checkpoints", headers=head)
    assert r.status_code == 503 and "PENDING" in r.text
    assert client.get("/api/audit/checkpoints", headers=head).json()[0]["status"] == "PENDING"
    assert client.post("/api/audit/checkpoints", headers=head).status_code == 409
    assert len(client.post("/api/audit/checkpoints/publish", headers=head).json()["published"]) == 1
    assert client.get("/api/audit/checkpoints", headers=head).json()[0]["status"] == "PUBLISHED"


# ---- replay completeness (P3-09) ----

def test_full_replay_of_todays_events_is_verified_complete(client):
    submit_one(client)
    r = replay.replay()
    assert (r["ok"], r["verdict"], r["gaps"]) == (True, "VERIFIED_COMPLETE", [])


def test_a_subset_of_projectors_is_never_called_complete(client):
    submit_one(client)
    r = replay.replay(["applications"])
    assert (r["ok"], r["verdict"]) == (False, "CONSISTENT_SUBSET")
    assert {"kind": "UNHANDLED_EVENT_TYPE", "event_type": "dl.deadline_opened", "events": 1} in r["gaps"]
    assert "dl.deadline_opened.v1" in r["schemas_without_projector"]


def test_a_projection_without_live_model_is_a_gap_not_a_pass(client):
    submit_one(client)

    class NoLive:
        name, owner, compared_fields = "nolive", "test", ()
        handles = frozenset({("wf.application_created", 1), ("wf.application_submitted", 1),
                             ("wf.application_submitted", 2), ("dl.deadline_opened", 1)})

        def apply(self, state, ev):
            pass

        def live(self, session):
            return None

    replay.register(NoLive())
    try:
        r = replay.replay(["nolive"])
    finally:
        replay._projectors.pop("nolive")
    assert (r["ok"], r["verdict"], r["gaps"]) == (False, "CONSISTENT_SUBSET", [{"kind": "NO_LIVE_MODEL", "projection": "nolive"}])


def test_unknown_versions_make_the_result_partial(client):
    now = datetime.now(timezone.utc)
    events = [EventRecord(1, now, "application", uuid4(), "wf.application_submitted", 3, {})]
    r = replay.replay(["applications"], events=events)
    assert r["verdict"] in ("CONSISTENT_SUBSET", "MISMATCH") and r["ok"] is False
    assert any(g["kind"] == "UNKNOWN_EVENT_VERSION" for g in r["gaps"])


# ---- witness conflicts and assurance (P3-14) ----

def _copy_of(seq, head_hash, cid=None, sig="sig"):
    return {"id": cid or str(uuid4()), "statement": json.dumps({"head_seq": seq, "head_hash": head_hash}), "signature": sig}


def test_witness_accepts_an_identical_retry():
    w = MemoryWitness()
    cp = _copy_of(5, "h")
    w.publish(cp)
    w.publish(dict(cp))
    assert len(w.items) == 1


def test_witness_accepts_a_new_checkpoint_of_the_same_unchanged_head():
    w = MemoryWitness()
    w.publish(_copy_of(5, "h"))
    w.publish(_copy_of(5, "h"))
    assert len(w.items) == 2


def test_witness_refuses_a_competing_hash_for_an_entry_it_vouches_for(tmp_path):
    for w in (MemoryWitness(), audit.LocalFileWitness(str(tmp_path))):
        w.publish(_copy_of(5, "h"))
        w.publish(_copy_of(8, "h8"))
        with pytest.raises(audit.WitnessConflict, match="competing"):
            w.publish(_copy_of(5, "evil"))
        with pytest.raises(audit.WitnessConflict, match="competing"):
            w.publish(_copy_of(8, "evil"))
        assert json.loads(w.latest()["statement"])["head_hash"] == "h8"


def test_witness_refuses_a_different_copy_under_an_existing_id():
    w = MemoryWitness()
    w.publish(_copy_of(5, "h", cid="cp-1"))
    with pytest.raises(audit.WitnessConflict, match="different checkpoint with id"):
        w.publish(_copy_of(9, "x", cid="cp-1"))
    with pytest.raises(audit.WitnessConflict):
        w.publish(_copy_of(5, "h", cid="cp-1", sig="other"))


def test_assurance_distinguishes_newer_unanchored_entries(client):
    submit_one(client)
    w = checkpoint()
    assert check(w).assurance == "CHECKPOINTED"
    client.post("/api/applications", headers=INST, json={
        "institution_id": str(SUNRISE), "category": "NEW_PROGRAMME", "academic_year": "2028-29"})
    r = check(w)
    assert (r.status, r.assurance, r.entries_after_checkpoint) == ("VERIFIED", "CHECKPOINTED_WITH_NEWER_ENTRIES", 1)
    checkpoint(witness=w)
    assert check(w).assurance == "CHECKPOINTED"


def test_rewritten_content_after_checkpoint_is_caught_by_the_chain(client):
    submit_one(client)
    w = checkpoint()
    sql("UPDATE plat.domain_event SET payload = jsonb_set(payload, '{category}', '\"MERGER\"') WHERE seq = 3")
    assert check(w).status == "CHAIN_BROKEN"


# ---- replay cannot be complete by checking nothing (P3-14) ----

def test_no_projectors_is_not_verification(client):
    r = replay.replay([], events=[])
    assert (r["ok"], r["verdict"]) == (False, "CONSISTENT_SUBSET")
    assert {"kind": "NO_PROJECTORS"} in r["gaps"]


def test_unregistered_projector_names_are_reported(client):
    r = replay.replay(["applications", "nope"], events=[])
    assert r["ok"] is False and {"kind": "UNKNOWN_PROJECTOR", "projection": "nope"} in r["gaps"]


def test_a_projector_that_compares_no_fields_is_a_gap(client):
    submit_one(client)

    class Empty:
        name, owner, compared_fields = "empty", "test", ()
        handles = frozenset({("wf.application_created", 1), ("wf.application_submitted", 1), ("dl.deadline_opened", 1)})

        def apply(self, state, ev):
            pass

        def live(self, session):
            return {}

    replay.register(Empty())
    try:
        r = replay.replay(["empty"])
    finally:
        replay._projectors.pop("empty")
    assert r["ok"] is False and {"kind": "NO_FIELDS_COMPARED", "projection": "empty"} in r["gaps"]
