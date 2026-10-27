"""EVC workflow/clock atomicity and role-scoped HTTP queue, with real P2/P3 ports."""
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from uuid import UUID, NAMESPACE_URL, uuid5

import pytest
from sqlalchemy import event, func, select, text

from app.evc.models import EvcRequest
from app.platform.db import new_session, unit_of_work
from app.platform.registry import port, provide
from contracts.enums import Role
from contracts.errors import ValidationFailed
from contracts.ports import CasePort, ClockPort, DeadlinePort, EvcPort, LedgerPort
from contracts.types import Anchor, Principal
from generator.cases.scale_generator import LogicalClock
from acceptance.route_support import DEMO_REF
from acceptance.runtime_support import SUNRISE, headers

NORTH = UUID("00000000-0000-4000-8000-000000000002")


@pytest.fixture
def env(acceptance_env):
    acceptance_env.clock = LogicalClock()
    provide(ClockPort, acceptance_env.clock)
    yield acceptance_env
    with new_session() as session, session.begin():
        session.execute(text("TRUNCATE evc.assignment_expert, evc.assignment, evc.availability, evc.coi, "
                             "evc.slot, evc.schedule_run_request, evc.schedule_run, evc.evc_request, evc.expert"))


def schedule(env, app):
    """complete_evc needs a published visit: register a fictional panel once, then propose and publish."""
    bureau = headers("BUREAU_OFFICER")
    if not getattr(env, "panel", None):
        env.panel = []
        for index in range(3):
            created = env.client.post("/api/evc/experts", headers=bureau, json=dict(
                user_ref=str(uuid5(NAMESPACE_URL, f"DEMO:queue-panel:{index}")), region="SOUTHERN", expertise_tags=["DEMO"]))
            assert created.status_code == 201, created.text
            items = [dict(date=(date(2026, 7, 1) + timedelta(days=d)).isoformat(), slot_part=p, available=True)
                     for d in range(8) for p in ("AM", "PM")]
            assert env.client.post(f"/api/evc/experts/{created.json()['id']}/availability", headers=bureau,
                                   json=dict(items=items)).status_code == 200
            env.panel.append(created.json()["id"])
    proposed = env.client.post("/api/evc/schedule:propose", headers=bureau, json=dict(
        run_id=str(uuid5(NAMESPACE_URL, "DEMO:queue-run")), algorithm="EDF", horizon_start=date(2026, 7, 1).isoformat(),
        horizon_end=(date(2026, 7, 1) + timedelta(days=7)).isoformat(), slot_capacity=4))
    assert proposed.status_code == 201 and proposed.json()["proposals"], proposed.text
    published = env.client.post("/api/evc/schedule:publish", headers=bureau, json=dict(run_id=proposed.json()["run_id"]))
    assert published.status_code == 200, published.text
    with new_session() as session:
        assert port(EvcPort).status(session, UUID(app)) == "PUBLISHED"


def start(env, institution=SUNRISE):
    auth = headers("INSTITUTION", institution)
    created = env.client.post("/api/applications", headers=auth, json=dict(institution_id=str(institution),
        category="NEW_PROGRAMME", academic_year="2027-28", items=[dict(item_key="DEMO_CORE_REFERENCE", document_ref=str(DEMO_REF))]))
    assert created.status_code == 201, created.text
    app = created.json()["id"]
    submitted = action(env, app, "submit", 1, institution=institution, payload=dict(dsc_present=True))
    assert submitted.status_code == 200, submitted.text
    return app


def action(env, app, name, version, institution=SUNRISE, **fields):
    role = "INSTITUTION" if name in {"submit", "withdraw"} else "BUREAU_OFFICER"
    return env.client.post(f"/api/cases/{app}/actions", headers=headers(role, institution),
        json=dict(action=name, expected_version=version, **fields))


def enter(env, institution=SUNRISE, name="advance_to_evc"):
    app = start(env, institution)
    result = action(env, app, name, 2, institution=institution)
    assert result.status_code == 200 and result.json()["stage"] == "EVC", result.text
    return app


def request_row(app):
    with new_session() as session:
        row = session.scalar(select(EvcRequest).where(EvcRequest.application_id == UUID(app)).order_by(EvcRequest.requested_at.desc(), EvcRequest.id.desc()))
        return SimpleNamespace(**{key: getattr(row, key) for key in ("id", "status", "closed_at", "stage_visit_ref", "requested_at", "rule_id", "ruleset_key", "deadline_ref")})


def events(env, app):
    response = env.client.get(f"/api/cases/{app}/timeline", headers=headers("AUDITOR"))
    assert response.status_code == 200
    return response.json()


def deadlines(env, app):
    response = env.client.get("/api/deadlines", params=dict(subject_id=app), headers=headers("AUDITOR"))
    assert response.status_code == 200
    return response.json()


@pytest.mark.parametrize("name", ["advance_to_evc", "advance", "scrutinise"])
def test_entry_once_retries_and_duplicate_port_dispatch(env, name):
    app = enter(env, name=name)
    row = request_row(app)
    assert row.status == "QUEUED" and row.rule_id == "EVC_PROCESSING" and row.ruleset_key == "aph-2024-27@r1"
    assert action(env, app, name, 2).status_code == 409
    before = len(events(env, app))
    actor = Principal(DEMO_REF, Role.BUREAU_OFFICER)
    with unit_of_work(actor) as uow:
        case = port(CasePort).lookup(uow.session, UUID(app))
        assert port(EvcPort).enter(uow, case, category="NEW_PROGRAMME", ruleset_key=row.ruleset_key,
            stage_visit_id=row.stage_visit_ref, rule_id=row.rule_id, action=name if name != "scrutinise" else "advance",
            anchor=Anchor(at=row.requested_at)) == row.id
    assert len(events(env, app)) == before
    assert len([d for d in deadlines(env, app) if d["rule_id"] == "EVC_PROCESSING"]) == 1
    assert [e["event_type"] for e in events(env, app)].count("evc.request_created") == 1


@pytest.mark.parametrize("shc", [True, False])
def test_completion_closes_clock_even_when_shc_is_skipped(env, shc):
    env.shc = shc
    app = enter(env)
    unscheduled = action(env, app, "complete_evc", 3)
    assert unscheduled.status_code == 422 and unscheduled.json()["detail"] == "EVC_SCHEDULE_NOT_PUBLISHED"
    schedule(env, app)
    response = action(env, app, "complete_evc", 3)
    assert response.status_code == 200, response.text
    assert response.json()["stage"] == ("SHC" if shc else "EVC")
    assert request_row(app).status == "DONE"
    clock = next(d for d in deadlines(env, app) if d["rule_id"] == "EVC_PROCESSING")
    assert clock["status"] == "MET"
    assert [e["event_type"] for e in events(env, app)].count("evc.request_completed") == 1
    if not shc:
        retry = action(env, app, "complete_evc", 4)
        assert retry.status_code == 422
        assert retry.json()["detail"] == "EVC_REQUEST_NOT_ACTIVE"
        assert not next(a for a in response.json()["available_actions"] if a["action"] == "complete_evc")["enabled"]


@pytest.mark.parametrize("name", ["reject", "withdraw", "revert"])
def test_unscheduled_cancellation_closes_waived_and_reentry_is_new_visit(env, name):
    app = enter(env)
    original = request_row(app).id
    payload = dict(target_stage="SCRUTINY") if name == "revert" else {}
    result = action(env, app, name, 3, reason_code="DEMO_REASON", payload=payload)
    assert result.status_code == 200, result.text
    assert request_row(app).status == "CANCELLED"
    assert next(d for d in deadlines(env, app) if d["rule_id"] == "EVC_PROCESSING")["status"] == "WAIVED"
    assert [e["event_type"] for e in events(env, app)].count("evc.request_cancelled") == 1
    if name == "revert":
        result = action(env, app, "advance_to_evc", 4)
        assert result.status_code == 200, result.text
        with new_session() as session:
            rows = session.scalars(select(EvcRequest).where(EvcRequest.application_id == UUID(app))).all()
            assert len(rows) == 2 and len({r.stage_visit_ref for r in rows}) == 2
            assert next(r for r in rows if r.status == "QUEUED").id != original


class FailingDeadline:
    def __init__(self, delegate, operation):
        self.delegate, self.operation = delegate, operation

    def open(self, uow, subject, rule_id, anchor, ruleset_key):
        result = self.delegate.open(uow, subject, rule_id, anchor, ruleset_key)
        if self.operation == "open" and rule_id == "EVC_PROCESSING":
            raise RuntimeError("EVC deadline failed")
        return result

    def close(self, uow, subject, rule_id, outcome):
        self.delegate.close(uow, subject, rule_id, outcome)
        if self.operation == "close" and rule_id == "EVC_PROCESSING":
            raise RuntimeError("EVC deadline failed")

    def pause_internal(self, *args):
        return self.delegate.pause_internal(*args)

    def resume_internal(self, *args):
        return self.delegate.resume_internal(*args)


@pytest.mark.parametrize("operation", ["open", "close"])
def test_deadline_failure_rolls_back_request_state_visits_deadlines_and_ledger(env, operation):
    app = start(env) if operation == "open" else enter(env)
    if operation == "close":
        schedule(env, app)
    before = events(env, app)
    case_before = env.client.get(f"/api/cases/{app}", headers=headers("BUREAU_OFFICER")).json()
    clocks_before = deadlines(env, app)
    provide(DeadlinePort, FailingDeadline(port(DeadlinePort), operation))
    with pytest.raises(RuntimeError, match="EVC deadline failed"):
        action(env, app, "advance_to_evc" if operation == "open" else "complete_evc", 2 if operation == "open" else 3)
    assert events(env, app) == before and deadlines(env, app) == clocks_before
    assert env.client.get(f"/api/cases/{app}", headers=headers("BUREAU_OFFICER")).json() == case_before
    with new_session() as session:
        assert session.scalar(select(func.count()).select_from(EvcRequest)) == (0 if operation == "open" else 1)
    if operation == "close":
        assert request_row(app).status == "PUBLISHED" and request_row(app).closed_at is None


def test_ledger_failure_after_evc_append_rolls_back_everything(env):
    app = start(env)
    before = events(env, app)
    real = port(LedgerPort)
    class FailingLedger:
        def append(self, uow, event):
            seq = real.append(uow, event)
            if event.event_type == "evc.request_created":
                raise RuntimeError("EVC ledger failed")
            return seq
        def verify(self, session):
            return real.verify(session)
    provide(LedgerPort, FailingLedger())
    with pytest.raises(RuntimeError, match="EVC ledger failed"):
        action(env, app, "advance_to_evc", 2)
    assert events(env, app) == before
    with new_session() as session:
        assert session.scalar(select(func.count()).select_from(EvcRequest)) == 0
    assert [d["rule_id"] for d in deadlines(env, app)] == ["AICTE_PROCESSING"]


def test_queue_filters_order_pagination_labels_waiting_and_scoping(env):
    first = enter(env)
    env.clock.tick(2 * 86400)
    second = enter(env)
    north = enter(env, NORTH)
    env.clock.tick(86400)
    response = env.client.get("/api/evc/queue", headers=headers("AUDITOR"))
    assert response.status_code == 200, response.text
    page = response.json()
    assert page["total"] == 3 and page["items"][0]["application_id"] == first
    assert page["items"][0]["days_waiting"] == 3
    assert all(r["duration_days"] == 7 and r["source_status"] == "DEMO_ASSUMPTION" for r in page["items"])
    ordered = sorted(page["items"], key=lambda r: (r["due_by"], r["priority_key"], r["requested_at"], r["id"]))
    assert page["items"] == ordered
    sub = env.client.get("/api/evc/queue?offset=1&limit=1", headers=headers("AUDITOR")).json()
    assert sub["total"] == 3 and sub["items"] == ordered[1:2]
    due = page["items"][0]["due_by"]
    filtered = env.client.get("/api/evc/queue", params={"from": due, "to": due, "status": "QUEUED"}, headers=headers("AUDITOR")).json()
    assert [r["application_id"] for r in filtered["items"]] == [first]
    inst = env.client.get("/api/evc/queue", headers=headers("INSTITUTION", SUNRISE)).json()
    assert inst["total"] == 2 and {r["application_id"] for r in inst["items"]} == {first, second}
    ro = dict(headers("RO_OFFICER"), **{"X-Demo-Region": "Northern"})
    region = env.client.get("/api/evc/queue", headers=ro).json()
    assert region["total"] == 1 and region["items"][0]["application_id"] == north
    assert env.client.get("/api/evc/queue?region=Southern", headers=ro).status_code == 403
    assert env.client.get("/api/evc/queue?region=Southern", headers=headers("AUDITOR")).json()["total"] == 2
    assert env.client.get("/api/evc/queue?from=2027-02-01&to=2026-01-01", headers=headers("AUDITOR")).status_code == 422
    assert env.client.get("/api/evc/queue?status=UNKNOWN", headers=headers("AUDITOR")).status_code == 422


def test_concurrent_entry_has_one_request_and_one_clock(env):
    app = start(env)
    barrier = Barrier(2)
    def apply(_):
        barrier.wait(timeout=20)
        return action(env, app, "advance_to_evc", 2).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(apply, [0, 1])) == [200, 409]
    with new_session() as session:
        assert session.scalar(select(func.count()).select_from(EvcRequest)) == 1
    assert [e["event_type"] for e in events(env, app)].count("evc.request_created") == 1
    assert len([r for r in deadlines(env, app) if r["rule_id"] == "EVC_PROCESSING"]) == 1


def test_completed_wait_stops_and_due_date_matches_real_clock(env):
    app = enter(env)
    schedule(env, app)
    env.clock.tick(2 * 86400)
    assert action(env, app, "complete_evc", 3).status_code == 200
    env.clock.tick(4 * 86400)
    response = env.client.get("/api/evc/queue?status=DONE", headers=headers("INSTITUTION", SUNRISE))
    assert response.status_code == 200
    row = response.json()["items"][0]
    assert row["days_waiting"] == 2
    real = next(d for d in deadlines(env, app) if d["rule_id"] == "EVC_PROCESSING")
    assert row["due_by"] == real["due_date"]


def test_read_permission_cannot_authorize_a_port_mutation(env):
    app = enter(env)
    row = request_row(app)
    actor = Principal(DEMO_REF, Role.INSTITUTION, institution_id=SUNRISE)
    with pytest.raises(ValidationFailed, match="EVC_ACTION_INVALID"):
        with unit_of_work(actor) as uow:
            case = port(CasePort).lookup(uow.session, UUID(app))
            port(EvcPort).enter(uow, case, category="NEW_PROGRAMME", ruleset_key=row.ruleset_key,
                stage_visit_id=row.stage_visit_ref, rule_id=row.rule_id, action="timeline", anchor=Anchor(at=row.requested_at))
    assert request_row(app).status == "QUEUED"


def test_same_instant_reentry_completion_uses_latest_visit_not_uuid_order(env):
    from app.intake.models import Application
    def request_id(app, version):
        visit = uuid5(NAMESPACE_URL, f"sih26262:wf:stage:{app}:{version}:EVC")
        return uuid5(NAMESPACE_URL, f"sih26262:evc:request:{visit}")
    # Force the adverse UUID ordering deterministically, without moving the clock.
    app_id = next(value for i in range(100) if (value := uuid5(NAMESPACE_URL, f"DEMO:EVC:logical-tie:{i}"))
                  and request_id(value, 3).int > request_id(value, 5).int)
    def fixed_id(mapper, connection, target):
        target.id = app_id
    event.listen(Application, "before_insert", fixed_id)
    try:
        env.shc = False
        app = enter(env)
    finally:
        event.remove(Application, "before_insert", fixed_id)
    assert action(env, app, "revert", 3, reason_code="DEMO_REASON", payload=dict(target_stage="SCRUTINY")).status_code == 200
    assert action(env, app, "advance_to_evc", 4).status_code == 200
    schedule(env, app)
    assert action(env, app, "complete_evc", 5).status_code == 200
    with new_session() as session:
        assert port(EvcPort).status(session, app_id) == "DONE"
    assert action(env, app, "reject", 6, reason_code="DEMO_REASON").status_code == 200
