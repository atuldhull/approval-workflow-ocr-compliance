"""Messages about recorded events: the ruleset map, idempotent queueing from the event log, and contextual wording."""
from datetime import timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text

from app.compliance.service import IST
from app.deadlines.wiring import clock
from app.deadlines.worker import TimerWorker
from app.platform import event_notices
from app.platform.db import new_session
from app.platform.demo_seed import sample_alerts, seed_directory
from app.platform.models import Notification, NotifyCursor, Outbox
from app.platform.notifier import Notifier
from app.platform.providers import FakeProvider, describe, render
from app.platform.recipients import group_ref
from backend.tests.intake_test_helpers import ensure_intake_rules, provide_fixture_items
from backend.tests.test_compliance import document_version
from conftest import NORTHFIELD, SUNRISE, headers
from contracts.enums import Role
from contracts.errors import ValidationFailed
from contracts.types import OutboundMessage

INST = headers("INSTITUTION", SUNRISE)
NORTH_INST = headers("INSTITUTION", NORTHFIELD, user="00000000-0000-4000-9000-000000000004")
SOUTH_RO = {**headers("RO_OFFICER", user="00000000-0000-4000-9000-000000000005"), "X-Demo-Region": "Southern"}
BUREAU = headers("BUREAU_OFFICER", user="00000000-0000-4000-9000-000000000006")
BUREAU_HEAD = headers("BUREAU_HEAD", user="00000000-0000-4000-9000-000000000007")
SUNRISE_GROUP = group_ref(Role.INSTITUTION, institution_id=SUNRISE)


@pytest.fixture
def env(client):
    seed_directory()
    return client


def submit(client, inst=SUNRISE, h=INST) -> str:
    ensure_intake_rules(client)
    app_id = client.post("/api/applications", headers=h, json={
        "institution_id": str(inst), "category": "NEW_PROGRAMME", "academic_year": "2027-28"}).json()["id"]
    provide_fixture_items(app_id)
    assert client.post(f"/api/applications/{app_id}/submit", headers=h, json={"dsc_present": True}).status_code == 200
    return app_id


def register_loa(client, app_id, inst=SUNRISE) -> dict:
    r = client.post("/api/compliance/letters", headers=BUREAU, json={
        "application_id": app_id, "institution_id": str(inst), "letter_type": "LOA", "academic_year": "2025-26",
        "issue_date": "2025-08-31", "issue_date_source": "PORTAL_EVENT", "lists_deficiencies": False,
        "f_no": "F.No. DEMO/SOUTH/2025/00042"})
    assert r.status_code == 201, r.text
    return r.json()


def notifier(provider=None):
    return Notifier({"email": provider or FakeProvider()}, worker_id="w1", now=clock.now, rng=lambda: 1.0)


def deliver(provider=None) -> FakeProvider:
    provider = provider or FakeProvider()
    w = notifier(provider)
    w.dispatch_events()
    while w.run_once(100):
        pass
    return provider


def outbox(template=None) -> list[Outbox]:
    with new_session() as s:
        q = select(Outbox).where(Outbox.source_event_id.is_not(None))
        return s.scalars(q.where(Outbox.template == template) if template else q).all()


def inbox(client, h=INST) -> list[dict]:
    r = client.get("/api/notifications/inbox", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def test_a_registered_letter_tells_the_institution_and_names_the_case(env):
    app_id = submit(env)
    register_loa(env, app_id)
    fake = deliver()
    rows = outbox("letter.registered")
    assert {(r.channel, r.recipient_ref) for r in rows} == {("in_app", SUNRISE_GROUP), ("email", SUNRISE_GROUP)}
    assert all(r.alert_id is None and r.status == "DELIVERED" for r in rows)
    [item] = [n for n in inbox(env) if n["template"] == "letter.registered"]
    assert item["subject"] == "Letter registered" and item["alert_id"] is None
    assert item["text"] == f"Case {app_id[:8]}: the Letter of Approval dated 31 Aug 2025 has been registered."
    assert item["case_ref"] == app_id[:8] and item["links"]["application_id"] == app_id
    assert "Compliance screen" in item["action"]
    [mail] = [m for m in fake.sent if m.template == "letter.registered"]
    _, body = render(mail.template, mail.reference, mail.context)
    assert app_id[:8] in body and str(mail.source_event_id) in body and "Sunrise" not in body
    assert inbox(env, NORTH_INST) == []


def test_reading_the_log_again_queues_nothing_twice(env):
    register_loa(env, submit(env))
    w = notifier()
    first = w.dispatch_events()
    assert first > 0
    with new_session() as s:            # even with the cursor rewound, each event reaches each recipient once
        s.get(NotifyCursor, event_notices.CURSOR).seq = 0
        s.commit()
    assert w.dispatch_events() == 0
    assert len(outbox()) == first


def test_rejected_evidence_names_the_obligation_and_its_due_date(env):
    app_id = submit(env)
    letter = register_loa(env, app_id)
    oid = letter["obligation_ids"][0]
    version = document_version(app_id)
    eid = env.post(f"/api/compliance/obligations/{oid}/evidence", headers=INST,
                   json={"document_version_id": version}).json()["id"]
    r = env.post(f"/api/compliance/evidence/{eid}/verify", headers=BUREAU,
                 json={"decision": "REJECTED", "reason_code": "AMOUNT_MISMATCH", "note": "synthetic"})
    assert r.status_code == 200, r.text
    deliver()
    [item] = [n for n in inbox(env) if n["template"] == "compliance.evidence_rejected"]
    obligation = env.get(f"/api/compliance/obligations/{oid}", headers=INST).json()
    assert item["subject"] == "Evidence rejected"
    assert item["text"].startswith(f"Case {app_id[:8]}: the evidence for the {obligation['kind'].replace('_', ' ').lower()} was "
                                   "rejected (amount mismatch).")
    assert "It is due on 15 Sep 2025 (IST)." in item["text"]
    assert item["links"]["obligation_id"] == oid


def test_a_breached_clock_tells_the_role_that_owns_it(env):
    app_id = submit(env)
    register_loa(env, app_id)
    clock.advance(31)
    TimerWorker(worker_id="t1", now=clock.now).run_once()
    deliver()
    # the LoA's deposit clock is the institution's; its ladder tells the regional office at the due time
    missed = [n for n in inbox(env) if n["template"] == "deadline.missed"]
    assert missed and all(n["text"].startswith(f"Case {app_id[:8]}: ") and n["text"].endswith("(IST) and has passed.")
                          for n in missed)
    assert any("the fifteen days to pay the security deposit was due on" in n["text"] for n in missed)
    assert all(n["links"]["application_id"] == app_id for n in missed)
    # AICTE's processing clock is the RO's, and its ladder already tells the RO at the due time: no second message
    assert not [n for n in inbox(env, SOUTH_RO) if n["template"] == "deadline.missed"]
    assert group_ref(Role.RO_OFFICER, "Southern") not in {r.recipient_ref for r in outbox("deadline.missed")}
    alerts = [n for n in inbox(env, SOUTH_RO) if n["alert_id"]]
    processing = [n for n in alerts if n["text"].startswith(f"Case {app_id[:8]}: AICTE's processing time")]
    assert sorted(n["template"] for n in processing) == ["deadline.breached", "deadline.reminder"]


def fire_certificate(app_id) -> str:
    """A version of the case's fire safety certificate, scanned clean."""
    document_id, version_id = uuid4(), uuid4()
    digest = sha256(version_id.bytes).hexdigest()
    with new_session() as s:
        s.execute(text("INSERT INTO doc.document (document_id, application_id, institution_id, doc_type, created_at, "
                       "updated_at) VALUES (:d, :a, :i, 'FIRE_NOC', now(), now())"),
                  {"d": document_id, "a": app_id, "i": SUNRISE})
        s.execute(text(
            "INSERT INTO doc.document_version (document_version_id, document_id, application_id, institution_id, "
            "version_no, original_filename, media_type, size_bytes, sha256, storage_ref, status, uploaded_by, "
            "created_at, updated_at) VALUES (:v, :d, :a, :i, 1, 'synthetic.pdf', 'application/pdf', 8, :h, :s, "
            "'QUARANTINED', :u, now(), now())"),
            {"v": version_id, "d": document_id, "a": app_id, "i": SUNRISE, "h": digest,
             "s": f"quarantine/{SUNRISE}/{app_id}/sha256/{digest}/{uuid4()}", "u": uuid4()})
        s.execute(text("UPDATE doc.document_version SET scan_status = 'clean', status = 'AVAILABLE', scanned_at = now() "
                       "WHERE document_version_id = :v"), {"v": version_id})
        s.commit()
    return str(version_id)


def test_a_document_expiry_reminder_and_breach_name_the_document_and_the_case(env):
    app_id = submit(env)
    version = fire_certificate(app_id)
    until = clock.now().astimezone(IST).date() + timedelta(days=100)
    r = env.post("/api/compliance/validity", headers=SOUTH_RO,
                 json={"document_version_id": version, "valid_until": until.isoformat()})
    assert r.status_code == 201, r.text
    clock.advance(11)                                                # 90 days before expiry
    TimerWorker(worker_id="t1", now=clock.now).run_once()
    deliver()
    [reminder] = [n for n in inbox(env) if n["template"] == "deadline.reminder"]
    assert reminder["text"] == (f"Case {app_id[:8]}: the renewal of an expiring document is due on "
                                f"{until.strftime('%d %b %Y')} (IST). Document: fire noc.")
    assert reminder["links"]["application_id"] == app_id
    clock.advance(91)                                                # past the expiry
    TimerWorker(worker_id="t1", now=clock.now).run_once()
    deliver()
    [missed] = [n for n in inbox(env) if n["template"] == "deadline.missed"]   # the institution owns the clock
    assert missed["text"].endswith("has passed. Document: fire noc.") and app_id[:8] in missed["text"]
    ro = [n["template"] for n in inbox(env, SOUTH_RO) if n["text"].endswith("Document: fire noc.")]
    assert ro == ["deadline.breached"]                               # the expiry ladder, not a second notice


def test_a_recorded_deficiency_names_the_round_and_the_answer_date(env, monkeypatch):
    from app.workflow import guards
    from app.workflow.commands import GuardFacts
    from backend.tests.test_workflow_case_api import ITEM, RESPONSE, act, create

    facts = GuardFacts(open_item_count=0, checklist_complete=True, has_assignment=True,
                       reason_codes=frozenset({"DEMO_MISSING_EVIDENCE"}), item_refs=frozenset({ITEM}),
                       response_refs=frozenset({RESPONSE}), applicability={"SHC": False},
                       live_clock_rules=frozenset({"AICTE_PROCESSING"}), second_approval_required=False)
    monkeypatch.setattr(guards, "_fact_loader", lambda uow, case, cmd: facts)
    ensure_intake_rules(env)
    case_id = create(env)
    assert act(env, case_id, "submit", 1).status_code == 200
    assert act(env, case_id, "record_deficiency", 2, "SCRUTINY_COMMITTEE", reason_code="DEMO_MISSING_EVIDENCE",
               payload={"item_keys": ["DEMO_CORE_REFERENCE"]}).status_code == 200
    deliver()
    [item] = [n for n in inbox(env) if n["template"] == "case.deficiency_recorded"]
    assert item["text"].startswith(f"Case {str(case_id)[:8]}: 1 deficiency item(s) recorded in round 1.")
    assert "set by the institution's time to answer the deficiencies." in item["text"]


def test_vacant_groups_and_unmapped_events_get_no_message(env):
    submit(env, NORTHFIELD, NORTH_INST)       # submission is not in the notification map
    assert deliver().sent == [] and outbox() == []
    with new_session() as s:
        assert s.scalar(select(func.count()).select_from(Notification)) == 0


def test_the_sample_option_only_queues_messages_about_recorded_events(env):
    assert sample_alerts() == 0                # an empty log: nothing is invented
    app_id = submit(env)
    queued = sample_alerts()
    assert queued == 6                         # institution and regional office, three channels each
    rows = outbox("case.update")
    assert all(r.alert_id is None and r.source_event_id is not None for r in rows)
    assert sample_alerts() == 0                # rerunning queues nothing twice
    deliver(FakeProvider())
    [item] = [n for n in inbox(env) if n["template"] == "case.update"]
    assert item["text"] == f"Case {app_id[:8]}: the application was submitted."
    assert item["links"]["application_id"] == app_id


def test_delivery_operations_list_event_messages(env):
    register_loa(env, submit(env))
    notifier().dispatch_events()
    listed = env.get("/api/notifications/outbox", headers=BUREAU_HEAD).json()
    assert listed and all(o["alert_id"] is None and o["source_event_id"] for o in listed)


def test_a_message_is_about_an_alert_or_an_event_never_both():
    with pytest.raises(ValueError):
        OutboundMessage(uuid4(), "in_app", "case.update", uuid4(), source_event_id=uuid4())
    with pytest.raises(ValueError):
        OutboundMessage(None, "in_app", "case.update", uuid4())


def test_templates_fall_back_to_generic_wording_without_context():
    assert describe("deadline.reminder")[1] == "A deadline on a case you handle is approaching."
    assert describe("deadline.reminder", {"case": "ab12cd34"})[1] == "A deadline on a case you handle is approaching."
    full = {"case": "ab12cd34", "rule": "the seven days to appeal a decision", "due": "04 Nov 2026"}
    assert describe("deadline.reminder", full)[1] == (
        "Case ab12cd34: the seven days to appeal a decision is due on 04 Nov 2026 (IST).")
    assert describe("deadline.reminder", {**full, "document": "lease deed"})[1].endswith(" Document: lease deed.")


@pytest.mark.parametrize("raw, problem", [
    ({"channels": []}, "channels"),
    ({"channels": ["in_app"], "events": {"x.y": {"template": "nope", "to": ["INSTITUTION"]}}}, "template"),
    ({"channels": ["in_app"], "events": {"x.y": {"template": "case.update", "to": ["AUDITOR"]}}}, "'to'"),
    ({"channels": ["in_app"], "events": {"x.y": {"template": {"field": "d", "A": "nope"}, "to": ["owner"]}}},
     "template"),
    ({"channels": ["fax"]}, "channels"),
])
def test_the_notification_map_is_validated(raw, problem):
    with pytest.raises(ValidationFailed) as e:
        event_notices.parse(raw)
    assert problem in str(e.value)


def test_the_shipped_map_is_valid_and_names_every_deadline_rule():
    config = event_notices.config_for(None)
    assert config is not None and config.source_status == "demo_assumption"
    assert set(config.events) == {"wf.deficiency_recorded", "evc.assignment_published", "cmp.evidence_verified",
                                  "cmp.letter_registered", "dl.deadline_breached"}
    assert config.events["evc.assignment_published"].to == ("INSTITUTION", "SCRUTINY_COMMITTEE")
    assert config.events["cmp.evidence_verified"].template_for({"decision": "ACCEPTED"}) == \
        "compliance.evidence_accepted"
    from app.platform.registry import port
    from contracts.ports import RulesetPort
    rules = port(RulesetPort).get(port(RulesetPort).default_key()).deadline_rules
    assert all(rule_id in config.rule_names for rule_id in rules)
    assert config.rule_name("SOMETHING_NEW") == "something new"


def test_the_notification_map_is_part_of_the_ruleset_checksum():
    from app.platform.settings import settings
    from app.workflow.loader import _sources
    files, _, _ = _sources(settings.rulesets_dir, settings.default_ruleset)
    assert "notifications.yaml" in {f.name for f in files}
