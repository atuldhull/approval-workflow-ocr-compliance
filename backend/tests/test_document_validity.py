"""Document validity (APH cl. 6.17) and officer-recorded obligations, end to end against PostgreSQL.

Documents go through the real upload, scan (fake scanner), extraction (fake text engine), blind entry and
second-officer confirmation; the confirmed date opens the DOCUMENT_VALIDITY obligation. Time moves with the demo
clock, and the timer worker raises the reminders and the expiry ladder.
"""
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select

from app.compliance.models import Obligation
from app.compliance.service import IST
from app.deadlines.models import Alert, Deadline
from app.deadlines.rules import AcademicYearStart, add_months, lease_eoa_stop_year
from app.deadlines.wiring import clock
from app.deadlines.worker import TimerWorker
from app.documents import service as documents
from app.documents.config import DocumentLimits
from app.documents.extraction import PageText
from app.documents.ocr import OcrToken, Script
from app.documents.storage import LocalQuarantineStorage
from app.platform.db import new_session
from app.platform.demo_seed import seed_directory
from app.platform.models import DomainEvent
from backend.tests.document_fakes import CleanScanner, pdf
from conftest import NORTHFIELD, SUNRISE, headers

U = lambda n: f"00000000-0000-4000-9000-{n:012d}"  # noqa: E731
INST = headers("INSTITUTION", SUNRISE, user=U(1))
NORTH_INST = headers("INSTITUTION", NORTHFIELD, user=U(4))
COMMITTEE = headers("SCRUTINY_COMMITTEE", user=U(2))
RO_SOUTH = {**headers("RO_OFFICER", user=U(5)), "X-Demo-Region": "Southern"}
RO_NORTH = {**headers("RO_OFFICER", user=U(8)), "X-Demo-Region": "Northern"}
BUREAU = headers("BUREAU_OFFICER", user=U(6))
BUREAU_HEAD = headers("BUREAU_HEAD", user=U(7))
AUDITOR = headers("AUDITOR", user=U(3))
ROLES = {"inst_sunrise": INST, "inst_north": NORTH_INST, "committee": COMMITTEE, "ro_south": RO_SOUTH,
         "ro_north": RO_NORTH, "bureau_officer": BUREAU, "bureau_head": BUREAU_HEAD, "auditor": AUDITOR}


class TextEngine:
    """Reads every file as `text`; tests set the text before extracting each version."""
    adapter_key = "test.validity"
    model_version = "validity-1"

    def __init__(self):
        self.text = ""

    def read(self, content, *, media_type):
        tokens, offset = [], 0
        for word in self.text.replace("\n", " ").split(" "):
            start = self.text.index(word, offset)
            tokens.append(OcrToken(word, 1, start, start + len(word), Decimal("0.9"), Script.LATIN))
            offset = start + len(word)
        return [PageText(1, self.text, tuple(tokens))]


@pytest.fixture
def env(client, tmp_path):
    engine = TextEngine()
    documents.configure(storage=LocalQuarantineStorage(tmp_path / "store", limits=DocumentLimits(
        10 * 1024 * 1024, 20, 4_000_000)), scanner=CleanScanner(), engine=engine)
    seed_directory()
    yield type("Env", (), {"client": client, "engine": engine})
    documents.configure(storage=None, scanner=None, engine=None)


def today():
    return clock.now().astimezone(IST).date()


def application(client, h=INST, inst=SUNRISE) -> str:
    r = client.post("/api/applications", headers=h, json={
        "institution_id": str(inst), "category": "NEW_PROGRAMME", "academic_year": "2027-28"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def upload(env, app_id, doc_type, marker, h=INST) -> str:
    r = env.client.post(f"/api/applications/{app_id}/documents", headers={**h, "Idempotency-Key": f"upload-{marker}"},
                        data={"doc_type": doc_type}, files={"file": (f"{marker}.pdf", pdf(marker), "application/pdf")})
    assert r.status_code == 201, r.text
    return r.json()["version"]["version_id"]


def confirm(env, version_id, field, text, value=None):
    """Extract the version reading `text`, then blind entry and review by the committee, confirmation by the RO."""
    env.engine.text = text
    r = env.client.post(f"/api/document-versions/{version_id}/extract", headers=COMMITTEE)
    assert r.status_code == 201, r.text
    facts = env.client.get(f"/api/document-versions/{version_id}/facts", headers=COMMITTEE).json()["facts"]
    fact_id = next(f["fact_id"] for f in facts if f["field_key"] == field)
    c = env.client
    assert c.post(f"/api/document-facts/{fact_id}/entry", headers=COMMITTEE,
                  json={"value": value or "typed"}).status_code == 200
    assert c.post(f"/api/document-facts/{fact_id}/review", headers=COMMITTEE,
                  json={"decision": "ACCEPTED"}).status_code == 200
    r = c.post(f"/api/document-facts/{fact_id}/confirm", headers=RO_SOUTH)
    assert r.status_code == 200, r.text
    return fact_id


def records(client, app_id, h=BUREAU):
    r = client.get(f"/api/compliance/obligations?application_id={app_id}&kind=DOCUMENT_VALIDITY", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def record(client, version_id, h=RO_SOUTH, **body):
    return client.post("/api/compliance/validity", headers=h, json={"document_version_id": version_id, **body})


def events(event_type):
    with new_session() as s:
        return s.scalars(select(DomainEvent).where(DomainEvent.event_type == event_type)
                         .order_by(DomainEvent.seq)).all()


def alerts_of(deadline_id):
    with new_session() as s:
        return s.scalars(select(Alert).where(Alert.deadline_id == UUID(deadline_id))
                         .order_by(Alert.due_version, Alert.level)).all()


def run_timers(days):
    clock.advance(days)
    TimerWorker(worker_id="validity-test").run_once()


# ---- a confirmed date opens the record ----

def test_a_confirmed_lease_end_opens_a_validity_record_with_the_eoa_stop_year(env):
    app_id = application(env.client)
    version = upload(env, app_id, "LEASE_DEED", "lease-1")
    end = today().replace(year=today().year + 20)
    fact_id = confirm(env, version, "lease_end_date", f"lease_end_date: {end.isoformat()}")

    [o] = records(env.client, app_id)
    assert (o["kind"], o["doc_type"], o["document_version_id"], o["document_version_no"]) == (
        "DOCUMENT_VALIDITY", "LEASE_DEED", version, 1)
    assert (o["valid_until"], o["due_date"], o["validity_basis"], o["validity_state"]) == (
        end.isoformat(), end.isoformat(), "DOCUMENT_FACT", "VALID")
    assert o["days_left"] == (end - today()).days
    assert (o["rule_id"], o["source_clause"], o["source_status"], o["state_origin"]) == (
        "DOCUMENT_EXPIRY", "6.17(a)", "verified", "OFFICER_CONFIRMED")
    # APH 2.1(e): the stop year is computed from the lease end and the longest course (four years by default)
    assert o["eoa_stop_year"] == lease_eoa_stop_year(end, 4, AcademicYearStart(7, 1))
    assert o["live_lease_ok"] is True
    with new_session() as s:
        row = s.get(Obligation, UUID(o["id"]))
        assert row.validity_fact_id == UUID(fact_id)
        clock_row = s.get(Deadline, row.deadline_id)
        assert (clock_row.rule_id, clock_row.due_date, clock_row.duration_unit) == ("DOCUMENT_EXPIRY", end, None)
        assert "due on document.valid_until" in clock_row.explanation
    [created] = events("cmp.obligation_created")
    assert created.event_version == 2
    assert {k: created.payload[k] for k in ("doc_type", "valid_until", "validity_basis", "eoa_stop_year")} == {
        "doc_type": "LEASE_DEED", "valid_until": end.isoformat(), "validity_basis": "DOCUMENT_FACT",
        "eoa_stop_year": o["eoa_stop_year"]}


def test_a_lease_shorter_than_the_longest_course_is_flagged(env):
    app_id = application(env.client)
    version = upload(env, app_id, "LAND_DEED", "short-lease")
    end = today() + timedelta(days=3 * 365)
    confirm(env, version, "lease_end_date", f"lease_end_date: {end.isoformat()}")
    [o] = records(env.client, app_id)
    assert o["live_lease_ok"] is False and o["eoa_stop_year"] is not None


def test_a_fire_certificate_reads_its_printed_valid_until(env):
    app_id = application(env.client)
    version = upload(env, app_id, "FIRE_NOC", "fire-1")
    until = today() + timedelta(days=200)
    confirm(env, version, "valid_until", f"Fire safety certificate Valid Until: {until.isoformat()}")
    [o] = records(env.client, app_id)
    assert (o["doc_type"], o["source_clause"], o["valid_until"], o["eoa_stop_year"], o["live_lease_ok"]) == (
        "FIRE_NOC", "6.17(i)", until.isoformat(), None, None)


def test_a_structural_stability_certificate_is_valid_five_years_from_issue(env):
    app_id = application(env.client)
    version = upload(env, app_id, "STRUCTURAL_STABILITY", "ssc-1")
    issued = today() - timedelta(days=400)
    confirm(env, version, "certificate_issue_date", f"Date of Issue: {issued.isoformat()}")
    [o] = records(env.client, app_id)
    assert (o["valid_until"], o["validity_basis"], o["source_clause"]) == (
        add_months(issued, 60).isoformat(), "APH_PERIOD", "6.17(h)")


def test_untracked_documents_and_fields_open_nothing(env):
    app_id = application(env.client)
    other = upload(env, app_id, "AFFIDAVIT", "affidavit-1")
    confirm(env, other, "valid_until", f"valid_until: {(today() + timedelta(days=50)).isoformat()}")
    completion = upload(env, app_id, "BUILDING_COMPLETION", "oc-1")
    # a lease end date means nothing on a completion certificate
    confirm(env, completion, "lease_end_date", f"lease_end_date: {(today() + timedelta(days=50)).isoformat()}")
    assert records(env.client, app_id) == []
    assert events("cmp.obligation_created") == []


# ---- an officer records the date ----

@pytest.mark.parametrize("role,code", [
    ("ro_south", 201), ("bureau_officer", 201), ("bureau_head", 201), ("ro_north", 403), ("committee", 403),
    ("inst_sunrise", 403), ("inst_north", 403), ("auditor", 403),
])
def test_who_may_record_a_validity_date(env, role, code):
    app_id = application(env.client)
    version = upload(env, app_id, "BUILDING_COMPLETION", f"oc-{role}")
    until = today() + timedelta(days=365)
    r = record(env.client, version, h=ROLES[role], valid_until=until.isoformat())
    assert r.status_code == code, r.text
    if code == 201:
        o = r.json()
        assert (o["validity_basis"], o["source_clause"], o["valid_until"], o["validity_state"]) == (
            "OFFICER_RECORDED", "6.17(g)", until.isoformat(), "VALID")


def test_recording_a_validity_date_is_checked(env):
    app_id = application(env.client)
    fire = upload(env, app_id, "FIRE_NOC", "fire-check")
    other = upload(env, app_id, "AFFIDAVIT", "affidavit-check")
    ssc = upload(env, app_id, "STRUCTURAL_STABILITY", "ssc-check")
    until = (today() + timedelta(days=30)).isoformat()
    assert record(env.client, other, valid_until=until).status_code == 422                 # not a tracked document
    assert record(env.client, fire).status_code == 422                                     # no date at all
    assert record(env.client, fire, valid_until=until, issue_date=until).status_code == 422
    assert record(env.client, fire, issue_date=today().isoformat()).status_code == 422     # fire has no APH period
    assert record(env.client, fire, valid_until=until, max_course_duration_years=4).status_code == 422
    assert record(env.client, fire, valid_until=until).status_code == 201
    assert record(env.client, fire, valid_until=until).status_code == 409                  # once per version
    r = record(env.client, ssc, issue_date=(today() - timedelta(days=10)).isoformat())
    assert r.status_code == 201 and r.json()["validity_basis"] == "APH_PERIOD"
    lease = upload(env, app_id, "LEASE_DEED", "lease-check")
    r = record(env.client, lease, valid_until=(today() + timedelta(days=3650)).isoformat(),
               max_course_duration_years=5)
    assert r.status_code == 201 and r.json()["live_lease_ok"] is True


def test_validity_records_stay_inside_the_callers_scope(env):
    south_app = application(env.client)
    north_app = application(env.client, NORTH_INST, NORTHFIELD)
    until = (today() + timedelta(days=90)).isoformat()
    assert record(env.client, upload(env, south_app, "FIRE_NOC", "fire-s"), valid_until=until).status_code == 201
    north_version = upload(env, north_app, "FIRE_NOC", "fire-n", h=NORTH_INST)
    assert record(env.client, north_version, h=BUREAU, valid_until=until).status_code == 201

    def seen(h):
        r = env.client.get("/api/compliance/obligations?kind=DOCUMENT_VALIDITY", headers=h)
        return r.status_code, sorted(o["application_id"] for o in r.json()) if r.status_code == 200 else None

    assert seen(INST) == (200, [south_app])
    assert seen(NORTH_INST) == (200, [north_app])
    assert seen(RO_SOUTH) == (200, [south_app])
    assert seen(RO_NORTH) == (200, [north_app])
    assert seen(BUREAU)[1] == sorted([south_app, north_app])
    assert env.client.get(f"/api/compliance/obligations?application_id={south_app}",
                          headers=NORTH_INST).status_code == 403


# ---- reminders, expiry and escalation ----

def test_reminders_at_each_offset_then_breach_and_the_expiry_ladder(env):
    app_id = application(env.client)
    version = upload(env, app_id, "FIRE_NOC", "fire-ladder")
    o = record(env.client, version, valid_until=(today() + timedelta(days=100)).isoformat()).json()

    expected = []
    for days, level, role, template in [(11, 0, "INSTITUTION", "deadline.reminder"),      # 90 days before
                                        (60, 1, "INSTITUTION", "deadline.reminder"),      # 30 days before
                                        (23, 2, "INSTITUTION", "deadline.reminder"),      # 7 days before
                                        (7, 3, "RO_OFFICER", "deadline.breached"),        # at expiry
                                        (7, 4, "BUREAU_OFFICER", "deadline.escalated"),   # 7 days after
                                        (23, 5, "BUREAU_HEAD", "deadline.escalated")]:    # 30 days after
        if level == 1:
            # acknowledging an advance reminder does not stop what follows the expiry
            first = alerts_of(o["deadline_id"])[0]
            assert env.client.post(f"/api/alerts/{first.id}/ack", headers=INST).status_code == 200
        run_timers(days)
        expected.append((level, role, template))
        assert [(a.level, a.role, a.template) for a in alerts_of(o["deadline_id"])] == expected
        if level == 2:
            assert env.client.get(f"/api/compliance/obligations/{o['id']}", headers=INST).json()[
                "validity_state"] == "EXPIRING_SOON"

    now = env.client.get(f"/api/compliance/obligations/{o['id']}", headers=INST).json()
    assert (now["validity_state"], now["deadline_status"], now["overdue"], now["status"]) == (
        "EXPIRED", "BREACHED", True, "OPEN")
    assert now["days_left"] < 0
    [breached] = events("dl.deadline_breached")
    assert breached.payload["deadline_id"] == o["deadline_id"]


def test_a_deposit_gets_one_reminder_per_configured_offset(env):
    app_id = application(env.client)
    r = env.client.post("/api/compliance/letters", headers=BUREAU, json={
        "application_id": app_id, "institution_id": str(SUNRISE), "letter_type": "LOA", "academic_year": "2026-27",
        "issue_date": today().isoformat(), "issue_date_source": "PORTAL_EVENT", "lists_deficiencies": False,
        "f_no": "F.No. DEMO/VALIDITY/1"})
    assert r.status_code == 201, r.text
    deposit = next(o for o in env.client.get(f"/api/compliance/obligations?application_id={app_id}",
                                             headers=BUREAU).json() if o["kind"] == "DEPOSIT")
    seen = []
    for days, level, role in [(9, 0, "INSTITUTION"), (5, 1, "INSTITUTION"), (1, 2, "INSTITUTION"),
                              (2, 3, "RO_OFFICER")]:   # 7, 2 and 1 days before the 15th day, then at the due time
        run_timers(days)
        seen.append((level, role))
        assert [(a.level, a.role) for a in alerts_of(deposit["deadline_id"])] == seen


# ---- renewal ----

def test_a_renewal_meets_the_record_closes_its_clock_and_opens_the_next_one(env):
    app_id = application(env.client)
    first = upload(env, app_id, "FIRE_NOC", "fire-v1")
    old_until = today() + timedelta(days=20)
    confirm(env, first, "valid_until", f"valid_until: {old_until.isoformat()}")
    [old] = records(env.client, app_id)

    second = upload(env, app_id, "FIRE_NOC", "fire-v2")
    other = upload(env, app_id, "AFFIDAVIT", "not-a-renewal")
    submit = lambda v: env.client.post(f"/api/compliance/obligations/{old['id']}/evidence",  # noqa: E731
                                       headers=INST, json={"document_version_id": v})
    assert submit(other).status_code == 422     # not the same document
    assert submit(first).status_code == 422     # not a new version
    evidence = submit(second)
    assert evidence.status_code == 201, evidence.text
    assert records(env.client, app_id)[0]["validity_state"] == "RENEWAL_UNDER_REVIEW"

    new_until = today() + timedelta(days=400)
    confirm(env, second, "valid_until", f"valid_until: {new_until.isoformat()}")
    assert len(records(env.client, app_id)) == 1   # the new date waits for the renewal to be accepted
    assert record(env.client, second, valid_until=new_until.isoformat()).status_code == 409

    r = env.client.post(f"/api/compliance/evidence/{evidence.json()['id']}/verify", headers=RO_SOUTH,
                        json={"decision": "ACCEPTED"})
    assert r.status_code == 200, r.text
    after = {o["document_version_id"]: o for o in records(env.client, app_id)}
    assert (after[first]["status"], after[first]["validity_state"], after[first]["deadline_status"]) == (
        "MET", "RENEWED", "MET")
    assert (after[second]["valid_until"], after[second]["document_version_no"], after[second]["validity_state"]) == (
        new_until.isoformat(), 2, "VALID")
    [closed] = events("dl.deadline_closed")
    assert (closed.payload["deadline_id"], closed.payload["outcome"]) == (old["deadline_id"], "MET")
    # both versions stay on file
    docs = env.client.get(f"/api/applications/{app_id}/documents", headers=INST).json()
    assert sorted(v["version_no"] for d in docs if d["doc_type"] == "FIRE_NOC" for v in d["versions"]) == [1, 2]


def test_an_accepted_renewal_without_a_confirmed_date_opens_the_next_record_once_it_is_recorded(env):
    app_id = application(env.client)
    first = upload(env, app_id, "BUILDING_COMPLETION", "oc-v1")
    old = record(env.client, first, valid_until=(today() + timedelta(days=10)).isoformat()).json()
    second = upload(env, app_id, "BUILDING_COMPLETION", "oc-v2")
    eid = env.client.post(f"/api/compliance/obligations/{old['id']}/evidence", headers=INST,
                          json={"document_version_id": second}).json()["id"]
    assert record(env.client, second, valid_until=(today() + timedelta(days=500)).isoformat()).status_code == 409
    assert env.client.post(f"/api/compliance/evidence/{eid}/verify", headers=BUREAU,
                           json={"decision": "ACCEPTED"}).status_code == 200
    assert [o["status"] for o in records(env.client, app_id)] == ["MET"]
    r = record(env.client, second, valid_until=(today() + timedelta(days=500)).isoformat())
    assert r.status_code == 201 and r.json()["document_version_no"] == 2


def test_an_expired_record_renewed_late_closes_late(env):
    app_id = application(env.client)
    first = upload(env, app_id, "FIRE_NOC", "fire-late-1")
    old = record(env.client, first, valid_until=(today() + timedelta(days=2)).isoformat()).json()
    run_timers(5)
    assert env.client.get(f"/api/compliance/obligations/{old['id']}", headers=INST).json()["overdue"] is True
    second = upload(env, app_id, "FIRE_NOC", "fire-late-2")
    confirm(env, second, "valid_until", f"valid_until: {(today() + timedelta(days=365)).isoformat()}")
    eid = env.client.post(f"/api/compliance/obligations/{old['id']}/evidence", headers=INST,
                          json={"document_version_id": second}).json()["id"]
    assert env.client.post(f"/api/compliance/evidence/{eid}/verify", headers=RO_SOUTH,
                           json={"decision": "ACCEPTED"}).status_code == 200
    [closed] = events("dl.deadline_closed")
    assert (closed.payload["from_status"], closed.payload["late"]) == ("BREACHED", True)
    states = sorted(o["validity_state"] for o in records(env.client, app_id))
    assert states == ["RENEWED", "VALID"]


# ---- obligations an officer records (undertakings) ----

def recorded(client, app_id, h=RO_SOUTH, **body):
    payload = {"application_id": app_id, "kind": "UNDERTAKING", "title": "Synthetic: complete the library",
               "evidence_required": "Completion certificate for the library block", "source_clause": "2.25(f)"}
    payload.update(body)
    return client.post("/api/compliance/obligations", headers=h, json=payload)


@pytest.mark.parametrize("role,code", [
    ("ro_south", 201), ("bureau_officer", 201), ("bureau_head", 201), ("ro_north", 403), ("committee", 403),
    ("inst_sunrise", 403), ("auditor", 403),
])
def test_who_may_record_an_undertaking(env, role, code):
    app_id = application(env.client)
    due = (today() + timedelta(days=30)).isoformat()
    assert recorded(env.client, app_id, h=ROLES[role], due_date=due).status_code == code


def test_an_undertaking_with_its_stated_due_date(env):
    app_id = application(env.client)
    due = today() + timedelta(days=10)
    r = recorded(env.client, app_id, due_date=due.isoformat())
    assert r.status_code == 201, r.text
    o = r.json()
    assert (o["kind"], o["due_date"], o["rule_id"], o["source_clause"], o["source_status"], o["state_origin"]) == (
        "UNDERTAKING", due.isoformat(), "UNDERTAKING_DUE_DATE", "2.25(f)", "verified_letter_text",
        "OFFICER_CONFIRMED")
    assert (o["title"], o["evidence_required"], o["source_letter_id"]) == (
        "Synthetic: complete the library", "Completion certificate for the library block", None)
    [created] = events("cmp.obligation_created")
    assert created.event_version == 2 and "Synthetic" not in str(created.payload)
    with new_session() as s:
        assert s.get(Obligation, UUID(o["id"])).recorded_by == UUID(RO_SOUTH["X-Demo-User"])
    # its own advance reminders reach the institution
    run_timers(4)
    assert [(a.level, a.role) for a in alerts_of(o["deadline_id"])] == [(0, "INSTITUTION")]
    listed = env.client.get(f"/api/compliance/obligations?application_id={app_id}", headers=INST).json()
    assert [x["title"] for x in listed] == ["Synthetic: complete the library"]


def test_a_no_admission_affidavit_is_timed_by_its_official_rule(env):
    app_id = application(env.client)
    r = recorded(env.client, app_id, kind="AFFIDAVIT", source_clause=None, rule_id="NO_ADMISSION_AFFIDAVIT_7D")
    assert r.status_code == 201, r.text
    o = r.json()
    assert (o["due_date"], o["source_clause"], o["source_status"]) == (
        (today() + timedelta(days=7)).isoformat(), "1.10(b)(i)", "verified")


@pytest.mark.parametrize("body", [
    {},                                                                    # neither a date nor a rule
    {"due_date": "DUE", "rule_id": "NO_ADMISSION_AFFIDAVIT_7D"},           # both
    {"rule_id": "DEPOSIT_15D"},                                            # not a recordable rule
    {"rule_id": "NO_ADMISSION_AFFIDAVIT_7D", "anchor_date": "FUTURE"},
    {"due_date": "PAST"},
    {"due_date": "DUE", "anchor_date": "TODAY"},
    {"due_date": "DUE", "kind": "DOCUMENT_VALIDITY"},
    {"due_date": "DUE", "source_clause": "clause; drop"},
    {"due_date": "DUE", "title": "   "},
])
def test_recording_an_undertaking_is_checked(env, body):
    app_id = application(env.client)
    dates = {"DUE": today() + timedelta(days=5), "PAST": today() - timedelta(days=1),
             "FUTURE": today() + timedelta(days=1), "TODAY": today()}
    body = {k: dates[v].isoformat() if v in dates else v for k, v in body.items()}
    assert recorded(env.client, app_id, **body).status_code == 422
    assert events("cmp.obligation_created") == []
