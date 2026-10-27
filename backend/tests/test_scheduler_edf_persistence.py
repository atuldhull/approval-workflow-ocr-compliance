"""Real PostgreSQL proposal state, shared metrics, audit and rollback/concurrency."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from threading import Barrier
from types import SimpleNamespace
from uuid import UUID, NAMESPACE_URL, uuid5

import pytest
from sqlalchemy import func, select, text

from app.evc.metrics import evaluate_schedule
from app.evc import scheduler_edf as scheduler_module
from app.evc.models import Assignment, AssignmentExpert, Availability, Coi, EvcRequest, Expert, ScheduleRun, Slot
from app.evc.scheduler_edf import ScheduleCommand, propose_edf
from app.evc.scheduling import Allocation, SchedulingProblem, SchedulingRequest, SchedulingSlot
from app.evc.selector_service import selector_request
from app.platform import registry as bindings
from app.platform.db import new_session
from app.platform.models import DomainEvent, LedgerEntry
from app.platform.registry import port, provide
from contracts.enums import Role
from contracts.errors import Conflict, Forbidden, ValidationFailed
from contracts.fakes import FakeClock
from contracts.ports import ClockPort, LedgerPort, RulesetPort
from contracts.types import Principal
from conftest import SUNRISE, NORTHFIELD, headers

AT = datetime(2026, 7, 20, 4, 30, tzinfo=timezone.utc)
DAY = AT.date()
END = DAY + timedelta(days=5)


def ref(token):
    return uuid5(NAMESPACE_URL, f"DEMO:edf:{token}")


ACTOR = Principal(ref("officer"), Role.BUREAU_OFFICER)
DAILY_CAP = 1  # pinned r1 expert_pool.scheduler.expert_daily_cap (DEMO ASSUMPTION)


def command(token="run", region=None):
    return ScheduleCommand(ref(token), DAY, END, region)


@pytest.fixture
def edf_env(client, monkeypatch):
    monkeypatch.setattr(bindings, "_impls", bindings._impls.copy())
    clock = FakeClock(AT)
    provide(ClockPort, clock)
    with client:
        try:
            experts = [ref(f"expert-{i}") for i in range(24)]
            slots = [ref(f"slot-{day}-{part}") for day in range(6) for part in ("AM", "PM")]
            with new_session() as session, session.begin():
                session.add_all(Expert(id=expert, user_ref=ref(f"user-{i}"), region="SOUTHERN", expertise_tags=["DEMO"], active=i != 23)
                                for i, expert in enumerate(experts))
                session.flush()
                session.add_all(Availability(expert_id=expert, date=DAY + timedelta(days=day), slot_part=part, available=(i + day) % 7 != 0)
                    for i, expert in enumerate(experts) for day in range(6) for part in ("AM", "PM"))
                session.add_all(Coi(expert_id=expert, institution_ref=SUNRISE, source="RECUSAL", reason_code="RECUSAL") for expert in experts[:2])
                session.add_all(Slot(id=ref(f"slot-{day}-{part}"), date=DAY + timedelta(days=day), slot_part=part, capacity=4)
                                for day in range(6) for part in ("AM", "PM"))
            created = []
            def add_cases(count, institution=SUNRISE):
                requests = []
                for index in range(count):
                    number = len(created)
                    response = client.post("/api/applications", headers=headers("INSTITUTION", institution),
                        json=dict(institution_id=str(institution), category="NEW_PROGRAMME", academic_year="2027-28"))
                    assert response.status_code == 201, response.text
                    app_id = UUID(response.json()["id"])
                    request_id = ref(f"request-{number}")
                    with new_session() as session, session.begin():
                        session.add(EvcRequest(id=request_id, application_id=app_id, institution_ref=institution,
                            region="Southern" if institution == SUNRISE else "Northern", category="NEW_PROGRAMME",
                            requested_at=AT - timedelta(days=index % 5 + 1), earliest_date=DAY,
                            due_by=DAY + timedelta(days=index % 4), status="QUEUED", priority_key=f"DEMO_{number}", ruleset_key="aph-2024-27@r1"))
                    created.append((request_id, app_id))
                    requests.append(request_id)
                return requests
            yield SimpleNamespace(client=client, add_cases=add_cases, experts=experts, slots=slots, clock=clock)
        finally:
            with new_session() as session, session.begin():
                session.execute(text("TRUNCATE evc.assignment_expert, evc.assignment, evc.availability, evc.coi, "
                                     "evc.slot, evc.schedule_run_request, evc.schedule_run, evc.evc_request, evc.expert"))


def snapshot():
    with new_session() as session:
        requests = tuple(SchedulingRequest(selector_request(session, row.id, planning_until=END), row.requested_at, True)
                         for row in session.scalars(select(EvcRequest).where(EvcRequest.status == "QUEUED")))
        slots = tuple(SchedulingSlot(s.id, s.date, s.slot_part, s.capacity) for s in session.scalars(select(Slot)))
        existing = tuple(Allocation(a.evc_request_id, a.slot_id, tuple(a.expert_ids)) for a in session.scalars(select(Assignment)))
    return SchedulingProblem(requests, slots, existing, DAY, END, AT, DAILY_CAP)


def state():
    with new_session() as session:
        counts = tuple(session.scalar(select(func.count()).select_from(model)) for model in
                       (ScheduleRun, Assignment, AssignmentExpert, DomainEvent, LedgerEntry))
        requests = tuple(session.execute(select(EvcRequest.id, EvcRequest.status, EvcRequest.due_by, EvcRequest.ruleset_key).order_by(EvcRequest.id)))
    return counts, requests


def test_forty_request_proposal_persists_exact_plan_metrics_and_audit(edf_env):
    request_ids = edf_env.add_cases(40)
    problem = snapshot()
    due_before = {row.id: row.selector.eligibility.due_by for row in problem.requests}
    result = propose_edf(ACTOR, command())
    # 21 eligible experts at one visit per day fit 36 three-expert panels in six days; the rest wait, explained.
    assert result.plan.metrics.scheduled == 36 and result.plan.metrics.hard_constraint_violations == 0
    assert result.expert_daily_cap == DAILY_CAP and len(result.unscheduled_reasons) == 4
    assert {code for _, code in result.unscheduled_reasons} == {"EXPERT_DAILY_CAP"}
    with new_session() as session:
        run = session.get(ScheduleRun, ref("run"))
        assert run.algorithm == "EDF" and run.status == "PROPOSED" and run.created_at == AT
        assignments = session.scalars(select(Assignment).where(Assignment.schedule_run_id == run.run_id)).all()
        actual = tuple(Allocation(a.evc_request_id, a.slot_id, tuple(a.expert_ids)) for a in assignments)
        assert len(actual) == len(result.assignment_ids) == 36 and not any(a.published for a in assignments)
        assert {a.panel_role for a in assignments} == {"DEMO_PANEL"}
        assert evaluate_schedule(problem, actual).metrics.numeric_json() == run.metrics == result.plan.metrics.numeric_json()
        assert bytes(run.parameters["input_fingerprint_bytes"]).hex() == problem.fingerprint == result.plan.input_fingerprint
        rows = session.scalars(select(EvcRequest).where(EvcRequest.id.in_(request_ids))).all()
        waiting = {request_id for request_id, _ in result.unscheduled_reasons}
        assert all(r.status == ("QUEUED" if r.id in waiting else "PROPOSED") and r.ruleset_key == "aph-2024-27@r1"
                   and r.due_by == due_before[r.id] for r in rows)
        assert run.parameters["expert_daily_cap"] == DAILY_CAP
        assert session.scalar(select(func.count()).select_from(AssignmentExpert)) == 108
        events = session.scalars(select(DomainEvent).where(DomainEvent.event_type.like("evc.%")).order_by(DomainEvent.seq)).all()
        assert [e.event_type for e in events] == ["evc.schedule_proposed"] + ["evc.assignment_proposed"] * 36
        assert events[0].payload["metrics"] == run.metrics
        assert [UUID(e.payload["request_id"]) for e in events[1:]] == [a.request_id for a in result.plan.allocations]
        app = next(r.application_id for r in rows if r.id not in waiting)
    timeline = edf_env.client.get(f"/api/cases/{app}/timeline", headers=headers("AUDITOR"))
    assert "evc.assignment_proposed" in [e["event_type"] for e in timeline.json()]
    assert edf_env.client.get("/api/ledger/verify", headers=headers("AUDITOR")).json()["ok"]


def test_proposals_remain_reservations_and_are_not_rescheduled(edf_env):
    edf_env.add_cases(4)
    first = propose_edf(ACTOR, command("first"))
    problem = snapshot()
    assert problem.requests == () and len(problem.existing) == 4
    second = propose_edf(ACTOR, command("second"))
    assert second.plan.metrics.scheduled == 0
    edf_env.add_cases(3)
    before = snapshot()
    third = propose_edf(ACTOR, command("third"))
    assert evaluate_schedule(before, third.plan.allocations).metrics.hard_constraint_violations == 0
    with pytest.raises(Conflict, match="SCHEDULE_RUN_ALREADY_EXISTS"):
        propose_edf(ACTOR, command("third"))


@pytest.mark.parametrize("failure_event", ["evc.schedule_proposed", "evc.assignment_proposed"])
def test_ledger_failure_after_append_rolls_back_run_assignments_and_request_state(edf_env, monkeypatch, failure_event):
    edf_env.add_cases(3)
    before = state()
    real = port(LedgerPort)
    class FailingLedger:
        def append(self, uow, event):
            value = real.append(uow, event)
            if event.event_type == failure_event:
                raise Conflict("DEMO_LEDGER_FAILURE")
            return value
        def verify(self, session):
            return real.verify(session)
    provide(LedgerPort, FailingLedger())
    with pytest.raises(Conflict, match="DEMO_LEDGER_FAILURE"):
        propose_edf(ACTOR, command())
    assert state() == before


@pytest.mark.parametrize("role", [Role.INSTITUTION, Role.AUDITOR, Role.SCRUTINY_COMMITTEE])
def test_only_scheduling_roles_can_mutate_and_auth_precedes_clock(edf_env, role):
    edf_env.add_cases(1)
    before = state()
    class ForbiddenClock:
        def now(self):
            raise AssertionError("clock read before authorization")
    provide(ClockPort, ForbiddenClock())
    with pytest.raises(Forbidden):
        propose_edf(Principal(ref("denied"), role, institution_id=SUNRISE), command())
    assert state() == before


def test_ro_region_filter_uses_authoritative_case_scope(edf_env):
    own = edf_env.add_cases(2)
    other = edf_env.add_cases(1, NORTHFIELD)
    actor = Principal(ref("ro"), Role.RO_OFFICER, region="Southern")
    with pytest.raises(Forbidden, match="SCHEDULE_REGION_FORBIDDEN"):
        propose_edf(actor, command("wrong", region="Northern"))
    result = propose_edf(actor, command())
    assert {a.request_id for a in result.plan.allocations} == set(own)
    with new_session() as session:
        assert session.get(EvcRequest, other[0]).status == "QUEUED"
    with pytest.raises(Forbidden):
        propose_edf(Principal(ref("ro"), Role.RO_OFFICER), command("no-region"))


def test_unschedulable_queue_and_invalid_horizon_are_safe(edf_env):
    requests = edf_env.add_cases(2)
    with new_session() as session, session.begin():
        session.execute(text("DELETE FROM evc.availability"))
    result = propose_edf(ACTOR, command())
    assert result.plan.metrics.unscheduled == 2 and result.plan.metrics.hard_constraint_violations == 0
    with new_session() as session:
        assert all(session.get(EvcRequest, request).status == "QUEUED" for request in requests)
    before = state()
    with pytest.raises(ValidationFailed, match="HORIZON"):
        propose_edf(ACTOR, ScheduleCommand(ref("bad"), END, DAY))
    assert state() == before


def test_concurrent_proposals_serialize_without_expert_or_capacity_conflicts(edf_env):
    edf_env.add_cases(8)
    problem = snapshot()
    gate = Barrier(2)
    def run(index):
        gate.wait(timeout=15)
        return propose_edf(ACTOR, command(f"concurrent-{index}"))
    with ThreadPoolExecutor(max_workers=2) as workers:
        plans = list(workers.map(run, range(2)))
    assert sorted(p.plan.metrics.scheduled for p in plans) == [0, 8]
    with new_session() as session:
        allocations = tuple(Allocation(a.evc_request_id, a.slot_id, tuple(a.expert_ids)) for a in session.scalars(select(Assignment)))
    assert len(allocations) == 8 and evaluate_schedule(problem, allocations).metrics.hard_constraint_violations == 0


def test_expert_registered_after_lock_snapshot_waits_for_next_run(edf_env, monkeypatch):
    edf_env.add_cases(1)
    real = scheduler_module.selector_request
    introduced = False
    new_id = UUID(int=1)  # Would win the stable tie-break if the unlocked expert entered this run.
    def concurrent_registration(session, request_id, **kwargs):
        nonlocal introduced
        if not introduced:
            with new_session() as other, other.begin():
                other.add(Expert(id=new_id, user_ref=ref("new-user"), region="SOUTHERN", expertise_tags=["DEMO"], active=True))
                other.flush()
                other.add(Availability(expert_id=new_id, date=DAY, slot_part="AM", available=True))
            introduced = True
        return real(session, request_id, **kwargs)
    monkeypatch.setattr(scheduler_module, "selector_request", concurrent_registration)
    result = propose_edf(ACTOR, command())
    assert introduced and result.plan.metrics.scheduled == 1
    assert new_id not in result.plan.allocations[0].expert_ids


def test_ro_cross_region_policy_cannot_bypass_pool_scope(edf_env):
    edf_env.add_cases(1)
    real = port(RulesetPort)
    class CrossRegionRules:
        def get(self, key):
            rules = real.get(key)
            return replace(rules, expert_pool={**rules.expert_pool, "region_rule": "ANY_REGION"})
        def default_key(self):
            return real.default_key()
        def route_for(self, category, key):
            return real.route_for(category, key)
    provide(RulesetPort, CrossRegionRules())
    before = state()
    with pytest.raises(Forbidden, match="SCHEDULE_CROSS_REGION_SCOPE_FORBIDDEN"):
        propose_edf(Principal(ref("ro"), Role.RO_OFFICER, region="Southern"), command())
    assert state() == before
