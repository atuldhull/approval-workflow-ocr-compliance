"""Real FastAPI/PostgreSQL pool commands, authorization and transactional auditing."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from threading import Barrier
from uuid import UUID, NAMESPACE_URL, uuid5

import pytest
from sqlalchemy import func, select, text

from app.evc.eligibility import eligible_experts
from app.evc.models import Assignment, Availability, Coi, EvcRequest, Expert, ScheduleRun, Slot
from app.evc.pool import eligibility_snapshot
from app.platform import registry as bindings
from app.platform.db import new_session
from app.platform.models import DomainEvent, LedgerEntry, PersonalData
from app.platform.registry import port, provide
from contracts.errors import Conflict
from contracts.ports import ClockPort, LedgerPort, PersonalDataPort, RulesetPort
from conftest import SUNRISE, headers

DAY = date(2026, 7, 1)
MANAGER = headers("BUREAU_OFFICER")


def ref(key):
    return uuid5(NAMESPACE_URL, f"DEMO:expert-pool:{key}")


@pytest.fixture
def pool_client(client):
    with client:
        try:
            yield client
        finally:
            # Keep pool master-data tests independent of later migration-only tests.
            with new_session() as session, session.begin():
                session.execute(text("TRUNCATE evc.assignment_expert, evc.assignment, evc.availability, evc.coi, "
                                     "evc.slot, evc.schedule_run_request, evc.schedule_run, evc.evc_request, evc.expert"))


def create(client, key="one", region="Southern", **extra):
    return client.post("/api/evc/experts", headers=MANAGER,
        json=dict(user_ref=str(ref(key)), region=region, expertise_tags=["DEMO_TECHNICAL", "DEMO"], **extra))


def registered(client, key="one", **extra):
    response = create(client, key, **extra)
    assert response.status_code == 201, response.text
    return response.json()


def availability(client, expert, *, day=DAY, part="AM", available=True, **kwargs):
    return client.post(f"/api/evc/experts/{expert}/availability", headers=kwargs.get("headers", MANAGER),
        json=dict(items=[dict(date=day.isoformat(), slot_part=part, available=available)]))


def coi(client, expert, source="RECUSAL", institution=SUNRISE, **kwargs):
    return client.post("/api/evc/coi", headers=kwargs.get("headers", MANAGER), json=dict(
        expert_id=expert, institution_ref=str(institution), source=source, reason_code=kwargs.get("reason_code", source)))


def events(expert):
    with new_session() as session:
        return session.scalars(select(DomainEvent).where(DomainEvent.aggregate_id == UUID(expert)).order_by(DomainEvent.seq)).all()


def counts():
    with new_session() as session:
        return tuple(session.scalar(select(func.count()).select_from(model)) for model in
                     (Expert, Availability, Coi, PersonalData, DomainEvent, LedgerEntry))


def test_registration_personal_isolation_audit_and_duplicate(pool_client):
    details = dict(name="DEMO Expert", email="demo@example.invalid", phone="DEMO_PHONE_001")
    row = registered(pool_client, personal_details=details)
    assert row["region"] == "SOUTHERN" and row["expertise_tags"] == ["DEMO", "DEMO_TECHNICAL"]
    assert row["identity_status"] == "P3_USER_REF_UNVERIFIED"
    assert not any(value in str(row) for value in details.values())
    with new_session() as session:
        expert = session.get(Expert, UUID(row["id"]))
        personal = session.get(PersonalData, expert.personal_ref)
        assert personal.data == details and personal.purpose == "EVC_EXPERT_CONTACT"
        assert set(expert.__table__.columns.keys()) == {"id", "user_ref", "region", "expertise_tags", "active", "personal_ref"}
    ev = events(row["id"])
    assert [e.event_type for e in ev] == ["evc.expert_registered"]
    assert ev[0].personal_ref == UUID(row["personal_ref"])
    assert ev[0].payload["personal_ref"] == row["personal_ref"]
    assert not any(value in str(ev[0].payload) for value in details.values())
    before = counts()
    assert create(pool_client, personal_details=details).status_code == 409
    assert counts() == before
    assert pool_client.get("/api/ledger/verify", headers=headers("AUDITOR")).json()["ok"]


def test_bulk_availability_is_sorted_idempotent_and_audited(pool_client):
    row = registered(pool_client)
    items = [dict(date=(DAY + timedelta(days=1)).isoformat(), slot_part="PM", available=False),
             dict(date=DAY.isoformat(), slot_part="AM", available=True)]
    path = f"/api/evc/experts/{row['id']}/availability"
    first = pool_client.post(path, headers=MANAGER, json=dict(items=items))
    assert first.status_code == 200 and first.json()["changed_count"] == 2
    assert first.json()["source_status"] == "DEMO_ASSUMPTION"
    assert first.json()["items"] == list(reversed(items))
    repeated = pool_client.post(path, headers=MANAGER, json=dict(items=list(reversed(items))))
    assert repeated.status_code == 200 and repeated.json()["changed_count"] == 0
    assert [e.event_type for e in events(row["id"])] == ["evc.expert_registered", "evc.availability_set"]
    assert events(row["id"])[1].payload["changes"] == list(reversed(items))
    assert availability(pool_client, row["id"], available=False).status_code == 200
    assert events(row["id"])[-1].payload["changes"][0]["available"] is False


@pytest.mark.parametrize("source", ["INSTITUTION_LINK", "PRIOR_ENGAGEMENT", "RECUSAL"])
def test_controlled_coi_sources_audit_and_noop(pool_client, source):
    row = registered(pool_client)
    first = coi(pool_client, row["id"], source)
    assert first.status_code == 200 and first.json()["created"] is True
    assert coi(pool_client, row["id"], source).json()["created"] is False
    assert [e.event_type for e in events(row["id"])] == ["evc.expert_registered", "evc.coi_recorded"]
    assert events(row["id"])[-1].payload["source"] == source


@pytest.mark.parametrize("operation", ["register", "availability", "coi", "read"])
def test_institution_cannot_manage_or_read_expert_pool(pool_client, operation):
    row = registered(pool_client)
    actor = headers("INSTITUTION", SUNRISE)
    before = counts()
    if operation == "register":
        response = pool_client.post("/api/evc/experts", headers=actor,
            json=dict(user_ref=str(ref("new")), region="SOUTHERN", expertise_tags=["DEMO"]))
    elif operation == "availability":
        response = availability(pool_client, row["id"], headers=actor)
    elif operation == "coi":
        response = coi(pool_client, row["id"], headers=actor)
    else:
        response = pool_client.get("/api/evc/experts", headers=actor)
    assert response.status_code == 403
    assert counts() == before


def test_ro_scope_on_every_command_and_before_pagination(pool_client):
    southern = registered(pool_client, "south")
    northern = registered(pool_client, "north", region="NORTHERN")
    actor = dict(headers("RO_OFFICER"), **{"X-Demo-Region": "Southern"})
    assert availability(pool_client, southern["id"], headers=actor).status_code == 200
    before = counts()
    assert availability(pool_client, northern["id"], headers=actor).status_code == 403
    assert coi(pool_client, northern["id"], headers=actor).status_code == 403
    assert pool_client.post("/api/evc/experts", headers=actor,
        json=dict(user_ref=str(ref("foreign")), region="NORTHERN", expertise_tags=["DEMO"])).status_code == 403
    assert counts() == before
    listing = pool_client.get("/api/evc/experts?limit=1", headers=actor).json()
    assert listing["total"] == 1 and listing["items"][0]["id"] == southern["id"]
    assert pool_client.get("/api/evc/experts?region=NORTHERN", headers=actor).status_code == 403
    assert pool_client.get("/api/evc/experts", headers=headers("RO_OFFICER")).status_code == 401  # platform: RO needs a region
    assert pool_client.get("/api/evc/experts", headers=headers("AUDITOR")).status_code == 200
    assert availability(pool_client, southern["id"], headers=headers("AUDITOR")).status_code == 403


def test_directory_region_available_date_order_and_pagination(pool_client):
    rows = [registered(pool_client, key) for key in ("c", "b", "a")]
    inactive = registered(pool_client, "inactive", active=False)
    for row in rows[:2] + [inactive]:
        assert availability(pool_client, row["id"]).status_code == 200
    assert availability(pool_client, rows[1]["id"], part="PM").status_code == 200
    query = f"/api/evc/experts?region=southern&available_on={DAY.isoformat()}"
    first = pool_client.get(query, headers=MANAGER).json()
    assert first["total"] == 2
    assert [r["id"] for r in first["items"]] == sorted(r["id"] for r in rows[:2])
    page = pool_client.get(query + "&offset=1&limit=1", headers=MANAGER).json()
    assert page["total"] == 2 and page["items"] == first["items"][1:]
    pm = pool_client.get(query + "&slot_part=PM", headers=MANAGER).json()
    assert [r["id"] for r in pm["items"]] == [rows[1]["id"]]
    assert pm["items"][0]["available_parts"] == ["PM"]
    assert pool_client.get("/api/evc/experts?slot_part=AM", headers=MANAGER).status_code == 422


@pytest.mark.parametrize("invalid", ["duplicate", "invalid_part", "free_text", "empty", "too_many"])
def test_invalid_bulk_is_rejected_without_partial_writes(pool_client, invalid):
    row = registered(pool_client)
    item = dict(date=DAY.isoformat(), slot_part="AM", available=True)
    items = [item]
    if invalid == "duplicate":
        items = [item, dict(item, available=False)]
    elif invalid == "invalid_part":
        items.append(dict(item, slot_part="EVENING"))
    elif invalid == "free_text":
        items.append(dict(item, note="DEMO remarks"))
    elif invalid == "empty":
        items = []
    else:
        items *= 733
    before = counts()
    response = pool_client.post(f"/api/evc/experts/{row['id']}/availability", headers=MANAGER, json=dict(items=items))
    assert response.status_code == 422
    assert counts() == before


def test_unknown_refs_bad_codes_and_raw_personal_fields_fail_cleanly(pool_client):
    assert availability(pool_client, str(ref("missing"))).status_code == 404
    row = registered(pool_client)
    assert coi(pool_client, row["id"], institution=ref("unknown-institution")).status_code == 404
    assert coi(pool_client, row["id"], source="UNKNOWN").status_code == 422
    assert coi(pool_client, row["id"], source="RECUSAL", reason_code="PRIOR_ENGAGEMENT").status_code == 422
    assert create(pool_client, "extra", email="demo@example.invalid").status_code == 422


@pytest.mark.parametrize("failure", ["personal", "register_ledger", "availability_ledger", "coi_ledger"])
def test_all_effects_rollback_when_a_port_fails_after_writing(pool_client, monkeypatch, failure):
    row = registered(pool_client)
    real_ledger, real_personal = port(LedgerPort), port(PersonalDataPort)
    monkeypatch.setattr(bindings, "_impls", bindings._impls.copy())
    class FailingLedger:
        def append(self, uow, event):
            real_ledger.append(uow, event)
            raise Conflict("DEMO_LEDGER_FAILURE")
        def verify(self, session):
            return real_ledger.verify(session)
    class FailingPersonal:
        def store(self, uow, data, purpose):
            real_personal.store(uow, data, purpose)
            raise Conflict("DEMO_PERSONAL_FAILURE")
    before = counts()
    if failure == "personal":
        provide(PersonalDataPort, FailingPersonal())
    else:
        provide(LedgerPort, FailingLedger())
    if failure.endswith("availability_ledger"):
        response = availability(pool_client, row["id"])
    elif failure == "coi_ledger":
        response = coi(pool_client, row["id"])
    else:
        response = create(pool_client, "rollback", personal_details=dict(name="DEMO rollback"))
    assert response.status_code == 409, response.text
    assert counts() == before


@pytest.mark.parametrize("attempt", range(3))
def test_concurrent_registration_and_bulk_retry_emit_once(pool_client, attempt):
    gate = Barrier(2)
    def register(_):
        gate.wait(timeout=10)
        return create(pool_client, f"concurrent-{attempt}").status_code
    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(register, range(2))) == [201, 409]
    row = pool_client.get("/api/evc/experts", headers=MANAGER).json()["items"][0]
    gate = Barrier(2)
    def set_once(_):
        gate.wait(timeout=10)
        response = availability(pool_client, row["id"])
        assert response.status_code == 200, response.text
        return response.json()["changed_count"]
    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(set_once, range(2))) == [0, 1]
    assert [e.event_type for e in events(row["id"])] == ["evc.expert_registered", "evc.availability_set"]


@pytest.mark.parametrize("published", [False, True])
def test_db_snapshot_excludes_proposed_and_published_bookings_and_coi(pool_client, monkeypatch, published):
    first, conflicted, free = [registered(pool_client, key) for key in ("booked", "coi", "free")]
    for row in (first, conflicted, free):
        assert availability(pool_client, row["id"]).status_code == 200
        assert availability(pool_client, row["id"], part="PM").status_code == 200
    assert coi(pool_client, conflicted["id"]).status_code == 200
    draft = pool_client.post("/api/applications", headers=headers("INSTITUTION", SUNRISE),
        json=dict(institution_id=str(SUNRISE), category="NEW_PROGRAMME", academic_year="2027-28"))
    assert draft.status_code == 201
    with new_session() as session, session.begin():
        session.add(EvcRequest(id=ref("request"), application_id=UUID(draft.json()["id"]), institution_ref=SUNRISE,
            region="Southern", category="NEW_PROGRAMME", requested_at=port(ClockPort).now(), earliest_date=DAY,
            due_by=DAY + timedelta(days=7), status="QUEUED", priority_key="DEMO", ruleset_key="aph-2024-27@r1"))
        session.add(Slot(id=ref("slot"), date=DAY, slot_part="AM", capacity=2))
        session.add(ScheduleRun(run_id=ref("run"), algorithm="EDF", parameters={}, metrics={}, created_at=port(ClockPort).now(), status="PROPOSED"))
        session.flush()
        session.add(Assignment(id=ref("assignment"), evc_request_id=ref("request"), slot_id=ref("slot"),
            expert_ids=[UUID(first["id"])], panel_role="DEMO_MEMBER", published=published, schedule_run_id=ref("run")))
    real_rules = port(RulesetPort)
    seen = []
    class ObservedRules:
        def get(self, key):
            seen.append(key)
            return real_rules.get(key)
        def default_key(self):
            return "aph-2024-27@r3-DEMO"
        def route_for(self, category, key):
            return real_rules.route_for(category, key)
    monkeypatch.setattr(bindings, "_impls", bindings._impls.copy())
    provide(RulesetPort, ObservedRules())
    with new_session() as session:
        snapshot = eligibility_snapshot(session, ref("request"))
    assert seen == ["aph-2024-27@r1"]
    assert [str(e.id) for e in eligible_experts(snapshot, DAY, "AM")] == [free["id"]]
    assert {str(e.id) for e in eligible_experts(snapshot, DAY, "PM")} == {first["id"], free["id"]}
    listing = pool_client.get(f"/api/evc/experts?available_on={DAY}&slot_part=AM", headers=MANAGER).json()
    assert first["id"] not in {e["id"] for e in listing["items"]}
    assert conflicted["id"] in {e["id"] for e in listing["items"]}  # Directory is not institution-specific eligibility.
    assert real_rules.get("aph-2024-27@r3-DEMO").expert_pool == real_rules.get("aph-2024-27@r1").expert_pool
