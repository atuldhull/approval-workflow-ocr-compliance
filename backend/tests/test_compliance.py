"""Approval letters, obligations and evidence verification against PostgreSQL (the shared destructive fixture).

Evidence versions are inserted the way the documents module stores them: quarantined and scan-pending, then
marked clean (AVAILABLE) by a scanner verdict unless a test needs one still in quarantine.
"""
from datetime import date, datetime, timezone
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text

from app.compliance import service
from app.compliance.models import ApprovalLetter, Evidence, Obligation
from app.deadlines.models import Deadline
from app.platform.db import get_engine, new_session, unit_of_work
from app.platform.models import CaseNote, DomainEvent
from app.platform.registry import port
from conftest import NORTHFIELD, SUNRISE, headers
from contracts.enums import LetterType, Role
from contracts.errors import Forbidden
from contracts.ports import CompliancePort
from contracts.types import LetterIn, Principal

U = lambda n: f"00000000-0000-4000-9000-{n:012d}"  # noqa: E731
ROLES = {
    "inst_sunrise": headers("INSTITUTION", SUNRISE, user=U(1)),
    "inst_north": headers("INSTITUTION", NORTHFIELD, user=U(4)),
    "committee": headers("SCRUTINY_COMMITTEE", user=U(2)),
    "ro_south": {**headers("RO_OFFICER", user=U(5)), "X-Demo-Region": "Southern"},
    "ro_north": {**headers("RO_OFFICER", user=U(8)), "X-Demo-Region": "Northern"},
    "bureau_officer": headers("BUREAU_OFFICER", user=U(6)),
    "bureau_head": headers("BUREAU_HEAD", user=U(7)),
    "auditor": headers("AUDITOR", user=U(3)),
}
BUREAU = ROLES["bureau_officer"]
SUNRISE_INST = ROLES["inst_sunrise"]
F_NO = "F.No. DEMO/SOUTH/2025/00042"


def application(client, inst=SUNRISE, h=SUNRISE_INST) -> str:
    r = client.post("/api/applications", headers=h,
                    json={"institution_id": str(inst), "category": "NEW_PROGRAMME", "academic_year": "2025-26"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def letter_body(app_id, inst=SUNRISE, **over):
    body = {"application_id": app_id, "institution_id": str(inst), "letter_type": "LOA",
            "academic_year": "2025-26", "issue_date": "2025-08-31", "issue_date_source": "PORTAL_EVENT",
            "lists_deficiencies": False, "f_no": F_NO}
    body.update(over)
    return body


def register(client, app_id, h=BUREAU, **over):
    return client.post("/api/compliance/letters", headers=h, json=letter_body(app_id, **over))


def document_version(app_id, inst=SUNRISE, clean=True) -> str:
    """Inserts a synthetic version of one document belonging to the application; scanned clean unless clean=False."""
    now = datetime(2025, 9, 1, tzinfo=timezone.utc)
    document_id, version_id = uuid4(), uuid4()
    digest = sha256(version_id.bytes).hexdigest()
    with get_engine().begin() as c:
        c.execute(text("INSERT INTO doc.document (document_id, application_id, institution_id, created_at, updated_at) "
                       "VALUES (:d, :a, :i, :t, :t)"), {"d": document_id, "a": app_id, "i": inst, "t": now})
        c.execute(text(
            "INSERT INTO doc.document_version (document_version_id, document_id, application_id, institution_id, "
            "version_no, original_filename, media_type, size_bytes, sha256, storage_ref, status, uploaded_by, "
            "created_at, updated_at) VALUES (:v, :d, :a, :i, 1, 'synthetic.pdf', 'application/pdf', 8, :h, :s, "
            "'QUARANTINED', :u, :t, :t)"),
            {"v": version_id, "d": document_id, "a": app_id, "i": inst, "h": digest,
             "s": f"quarantine/{inst}/{app_id}/sha256/{digest}/{uuid4()}", "u": uuid4(), "t": now})
        if clean:
            c.execute(text("UPDATE doc.document_version SET scan_status = 'clean', status = 'AVAILABLE', "
                           "scanned_at = :t WHERE document_version_id = :v"), {"v": version_id, "t": now})
    return str(version_id)


def events(prefix="cmp."):
    with new_session() as s:
        return s.scalars(select(DomainEvent).where(DomainEvent.event_type.startswith(prefix))
                         .order_by(DomainEvent.seq)).all()


def count(model):
    with new_session() as s:
        return s.scalar(select(func.count()).select_from(model))


@pytest.fixture
def loa(client):
    """Sunrise's application with a registered LoA; returns (app_id, letter json)."""
    app_id = application(client)
    r = register(client, app_id)
    assert r.status_code == 201, r.text
    return app_id, r.json()


def obligation_of(client, letter, kind, h=BUREAU):
    for oid in letter["obligation_ids"]:
        o = client.get(f"/api/compliance/obligations/{oid}", headers=h).json()
        if o["kind"] == kind:
            return o
    raise AssertionError(f"no {kind} obligation")


# ---- registration ----

def test_loa_creates_deposit_and_affidavit_obligations_with_due_dates(client, loa):
    app_id, letter = loa
    assert letter["letter_type"] == "LOA" and letter["region"] == "Southern"
    assert letter["valid_until"] == "2027-08-31"  # 24 months, demo assumption
    assert len(letter["obligation_ids"]) == 2
    for kind in ("DEPOSIT", "AFFIDAVIT"):
        o = obligation_of(client, letter, kind)
        assert o["due_date"] == "2025-09-15"  # issue date + 15 calendar days
        assert o["rule_id"] == "LOA_DEPOSIT_AFFIDAVIT_15D"
        assert o["source_status"] == "demo_assumption" and o["source_clause"] == "1.12"
        assert o["state_origin"] == "RULE_DEFAULT" and o["status"] == "OPEN"
        assert o["source_letter_id"] == letter["id"]
    with new_session() as s:
        clocks = s.scalars(select(Deadline).order_by(Deadline.rule_id)).all()
    assert sorted((d.subject_type, d.rule_id) for d in clocks) == [
        ("approval_letter", "LOA_VALIDITY_2Y"), ("obligation", "LOA_DEPOSIT_AFFIDAVIT_15D"),
        ("obligation", "LOA_DEPOSIT_AFFIDAVIT_15D")]
    assert [e.event_type for e in events()] == [
        "cmp.letter_registered", "cmp.obligation_created", "cmp.obligation_created"]


def test_eoa_listing_deficiencies_creates_the_six_month_condition(client):
    app_id = application(client)
    r = register(client, app_id, letter_type="EOA", lists_deficiencies=True)
    assert r.status_code == 201, r.text
    letter = r.json()
    assert len(letter["obligation_ids"]) == 1 and letter["valid_until"] is None
    o = obligation_of(client, letter, "LETTER_CONDITION")
    assert o["rule_id"] == "EOA_DEFICIENCY_6M" and o["state_origin"] == "OFFICER_CONFIRMED"
    assert o["source_status"] == "verified_letter_text"
    assert o["due_date"] == "2026-02-28"  # 31 Aug + 6 months, clamped to month end
    with new_session() as s:
        row = s.get(ApprovalLetter, UUID(letter["id"]))
        assert row.deficiencies_confirmed_by == UUID(BUREAU["X-Demo-User"])


def test_eoa_without_deficiencies_creates_no_obligation(client):
    app_id = application(client)
    r = register(client, app_id, letter_type="EOA", lists_deficiencies=False)
    assert r.status_code == 201, r.text
    assert r.json()["obligation_ids"] == []
    assert count(Obligation) == 0
    assert [e.event_type for e in events()] == ["cmp.letter_registered"]


@pytest.mark.parametrize("over", [
    {"f_no": None},                                      # portal letter without its number
    {"f_no": "   "},
    {"issue_date_source": "CONFIRMED_FACT", "f_no": None},  # confirmed date that names no fact
    {"issue_date_source": "CONFIRMED_FACT", "issue_date_fact_id": str(uuid4())},  # unknown fact
    {"issue_date_fact_id": str(uuid4())},                # a portal date must not cite a fact
    {"document_version_id": str(uuid4())},               # letter document that is not this application's
    {"issue_date": "2099-01-01"},                        # issued in the future
])
def test_missing_or_invalid_provenance_blocks_registration(client, over):
    app_id = application(client)
    r = register(client, app_id, **over)
    assert r.status_code == 422, r.text
    assert count(ApprovalLetter) == 0 and count(Obligation) == 0 and events() == []


def test_letter_for_another_institution_or_duplicate_is_refused(client, loa):
    app_id, _ = loa
    assert register(client, app_id, inst=NORTHFIELD).status_code == 422
    assert register(client, app_id).status_code == 409
    assert register(client, str(uuid4())).status_code == 404
    assert count(ApprovalLetter) == 1


@pytest.mark.parametrize("role,code", [
    ("bureau_officer", 201), ("bureau_head", 201), ("inst_sunrise", 403), ("inst_north", 403),
    ("committee", 403), ("ro_south", 403), ("ro_north", 403), ("auditor", 403),
])
def test_only_the_bureau_registers_letters(client, role, code):
    app_id = application(client)
    assert register(client, app_id, h=ROLES[role]).status_code == code


def test_registration_is_idempotent_with_a_key(client):
    app_id = application(client)
    h = {**BUREAU, "Idempotency-Key": "letter-key-0001"}
    first = client.post("/api/compliance/letters", headers=h, json=letter_body(app_id))
    again = client.post("/api/compliance/letters", headers=h, json=letter_body(app_id))
    assert first.status_code == again.status_code == 201
    assert again.json() == first.json() and again.headers.get("Idempotent-Replayed") == "true"
    assert count(ApprovalLetter) == 1 and len(events("cmp.letter_registered")) == 1


# ---- read scope ----

READERS = {"inst_sunrise": 200, "inst_north": 403, "committee": 200, "ro_south": 200, "ro_north": 403,
           "bureau_officer": 200, "bureau_head": 200, "auditor": 200}


@pytest.mark.parametrize("role", list(ROLES))
def test_read_scope_for_one_case(client, loa, role):
    app_id, letter = loa
    h, code = ROLES[role], READERS[role]
    assert client.get(f"/api/compliance/letters/{letter['id']}", headers=h).status_code == code
    assert client.get(f"/api/compliance/obligations/{letter['obligation_ids'][0]}", headers=h).status_code == code
    assert client.get(f"/api/compliance/obligations?application_id={app_id}", headers=h).status_code == code
    assert client.get(f"/api/compliance/letters?application_id={app_id}", headers=h).status_code == code


def test_lists_stay_inside_the_callers_institution_and_region(client, loa):
    north_app = application(client, NORTHFIELD, ROLES["inst_north"])
    assert register(client, north_app, inst=NORTHFIELD).status_code == 201

    def letters(role, query=""):
        r = client.get(f"/api/compliance/letters{query}", headers=ROLES[role])
        return r.status_code, sorted(x["region"] for x in r.json()) if r.status_code == 200 else None

    assert letters("inst_sunrise") == (200, ["Southern"])
    assert letters("inst_north") == (200, ["Northern"])
    assert letters("ro_south") == (200, ["Southern"])
    assert letters("ro_south", "?region=Northern")[0] == 403
    assert letters("bureau_head") == (200, ["Northern", "Southern"])
    r = client.get("/api/compliance/obligations", headers=ROLES["inst_north"])
    assert r.status_code == 200 and {o["institution_id"] for o in r.json()} == {str(NORTHFIELD)}


# ---- evidence ----

def submit(client, oid, version, h=SUNRISE_INST):
    return client.post(f"/api/compliance/obligations/{oid}/evidence", headers=h,
                       json={"document_version_id": version})


def verify(client, eid, h=BUREAU, **body):
    return client.post(f"/api/compliance/evidence/{eid}/verify", headers=h, json=body)


def test_quarantined_version_is_refused(client, loa):
    app_id, letter = loa
    r = submit(client, letter["obligation_ids"][0], document_version(app_id, clean=False))
    assert r.status_code == 422 and "scanner-approved" in r.json()["detail"]
    assert count(Evidence) == 0


@pytest.mark.parametrize("role,code", [
    ("inst_north", 403), ("committee", 403), ("ro_south", 403), ("bureau_officer", 403), ("auditor", 403),
])
def test_only_the_owning_institution_submits_evidence(client, loa, role, code):
    app_id, letter = loa
    assert submit(client, letter["obligation_ids"][0], document_version(app_id), h=ROLES[role]).status_code == code
    assert count(Evidence) == 0


def test_evidence_must_be_an_existing_version_of_the_same_application(client, loa):
    app_id, letter = loa
    oid = letter["obligation_ids"][0]
    other_app = application(client)
    assert submit(client, oid, document_version(other_app)).status_code == 422
    assert submit(client, oid, str(uuid4())).status_code == 422
    assert submit(client, str(uuid4()), document_version(app_id)).status_code == 404
    assert count(Evidence) == 0 and events("cmp.evidence") == []


def test_reject_then_accept_meets_the_obligation_and_closes_its_clock(client, loa):
    app_id, letter = loa
    oid = obligation_of(client, letter, "DEPOSIT")["id"]
    first = submit(client, oid, document_version(app_id))
    assert first.status_code == 201, first.text
    eid = first.json()["id"]
    assert submit(client, oid, document_version(app_id)).status_code == 409  # one pending submission at a time
    assert client.get(f"/api/compliance/obligations/{oid}", headers=BUREAU).json()["status"] == "EVIDENCE_SUBMITTED"

    assert verify(client, eid, decision="REJECTED").status_code == 422
    assert verify(client, eid, decision="REJECTED", reason_code="NOT_A_CODE").status_code == 422
    assert verify(client, eid, decision="REJECTED", reason_code="OTHER_SEE_NOTE").status_code == 422
    assert verify(client, eid, decision="ACCEPTED", reason_code="DOCUMENT_ILLEGIBLE").status_code == 422
    note = "Synthetic note: the receipt amount is not readable."
    r = verify(client, eid, decision="REJECTED", reason_code="AMOUNT_MISMATCH", note=note)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "REJECTED" and r.json()["has_note"] is True
    assert verify(client, eid, decision="ACCEPTED").status_code == 409
    assert client.get(f"/api/compliance/obligations/{oid}", headers=BUREAU).json()["status"] == "OPEN"

    second = submit(client, oid, document_version(app_id)).json()["id"]
    r = verify(client, second, h=ROLES["ro_south"], decision="ACCEPTED")
    assert r.status_code == 200, r.text
    o = client.get(f"/api/compliance/obligations/{oid}", headers=SUNRISE_INST).json()
    assert o["status"] == "MET" and [e["status"] for e in o["evidence"]] == ["REJECTED", "ACCEPTED"]
    with new_session() as s:
        assert s.get(Deadline, UUID(o["deadline_id"])).status == "MET"
        assert s.scalar(select(CaseNote.body).where(CaseNote.body_hash == sha256(note.encode()).hexdigest())) == note

    rejected = events("cmp.evidence_verified")[0]
    assert rejected.reason_code == "AMOUNT_MISMATCH"
    assert rejected.note_hash == sha256(note.encode()).hexdigest() and rejected.note_ref is not None
    assert note not in str(rejected.payload)
    assert submit(client, oid, document_version(app_id)).status_code == 409  # already met


@pytest.mark.parametrize("role,code", [
    ("inst_sunrise", 403), ("inst_north", 403), ("auditor", 403), ("ro_north", 403),
    ("committee", 200), ("ro_south", 200), ("bureau_head", 200),
])
def test_verification_role_and_region_matrix(client, loa, role, code):
    app_id, letter = loa
    eid = submit(client, letter["obligation_ids"][0], document_version(app_id)).json()["id"]
    assert verify(client, eid, h=ROLES[role], decision="ACCEPTED").status_code == code


def test_a_non_human_actor_cannot_verify(client, loa):
    app_id, letter = loa
    eid = UUID(submit(client, letter["obligation_ids"][0], document_version(app_id)).json()["id"])
    system = Principal(uuid4(), Role.SYSTEM)
    with pytest.raises(Forbidden):
        with unit_of_work(system) as uow:
            service.verify_evidence(uow, eid, "ACCEPTED")
    with new_session() as s:
        assert s.get(Evidence, eid).status == "SUBMITTED"


# ---- transactions and events ----

def test_caller_rollback_removes_letter_obligations_clocks_and_events_together(client):
    app_id = UUID(application(client))
    officer = Principal(UUID(BUREAU["X-Demo-User"]), Role.BUREAU_OFFICER)
    before = len(events(""))
    letter = LetterIn(application_id=app_id, institution_id=SUNRISE, letter_type=LetterType.LOA,
                      academic_year="2025-26", issue_date=date(2025, 8, 31), issue_date_source="PORTAL_EVENT",
                      lists_deficiencies=False, f_no=F_NO)
    with pytest.raises(RuntimeError):
        with unit_of_work(officer) as uow:
            port(CompliancePort).register_letter(uow, letter)
            assert uow.session.scalar(select(func.count()).select_from(Obligation)) == 2
            raise RuntimeError("caller fails after registering")
    assert count(ApprovalLetter) == 0 and count(Obligation) == 0 and count(Deadline) == 0
    assert len(events("")) == before

    with unit_of_work(officer) as uow:
        letter_id = port(CompliancePort).register_letter(uow, letter)
    with new_session() as s:
        assert s.get(ApprovalLetter, letter_id) is not None


def test_events_carry_no_names_notes_or_raw_letter_numbers(client, loa):
    app_id, letter = loa
    eid = submit(client, letter["obligation_ids"][0], document_version(app_id)).json()["id"]
    verify(client, eid, decision="REJECTED", reason_code="OTHER_SEE_NOTE", note="Synthetic explanation text.")
    found = events()
    assert {e.event_type for e in found} == {"cmp.letter_registered", "cmp.obligation_created",
                                              "cmp.evidence_submitted", "cmp.evidence_verified"}
    for e in found:
        blob = str(e.payload)
        assert F_NO not in blob and "Synthetic" not in blob and "Sunrise" not in blob
        assert not {"name", "note", "body", "f_no", "original_filename", "storage_ref"} & set(e.payload)
    registered = next(e for e in found if e.event_type == "cmp.letter_registered")
    assert registered.payload["f_no_sha256"] == sha256(F_NO.encode()).hexdigest()


def test_migration_down_and_up_again(database):
    from alembic import command
    from alembic.config import Config

    from conftest import ROOT

    cfg = Config(str(ROOT / "backend" / "alembic.ini"))
    cfg.attributes["configure_logger"] = False

    def cmp_tables():
        with get_engine().connect() as c:
            return set(c.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname = 'cmp'")))

    assert cmp_tables() == {"approval_letter", "obligation", "evidence"}
    command.downgrade(cfg, "compliance@base")
    assert cmp_tables() == set()
    command.upgrade(cfg, "heads")
    assert cmp_tables() == {"approval_letter", "obligation", "evidence"}
