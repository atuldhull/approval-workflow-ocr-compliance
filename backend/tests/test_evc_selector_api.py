"""Actual API label/scores, pinned input facts, case scope and read-only preview."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, NAMESPACE_URL, uuid5

import pytest
from sqlalchemy import func, select, text

from app.evc.models import Assignment, AssignmentExpert, EvcRequest, Expert, ScheduleRun, Slot
from app.evc.selector import SELECTOR_LABEL
from app.platform import registry as bindings
from app.platform.db import new_session
from app.platform.models import DomainEvent, LedgerEntry, PersonalData
from app.platform.registry import port, provide
from contracts.fakes import FakeClock
from contracts.ports import ClockPort, RulesetPort
from conftest import SUNRISE, headers

DAY = datetime(2026, 7, 20, 4, 30, tzinfo=timezone.utc).date()
MANAGER = headers("BUREAU_OFFICER")


def ref(token):
    return uuid5(NAMESPACE_URL, f"DEMO:selector:{token}")


@pytest.fixture
def selector_env(client, monkeypatch):
    monkeypatch.setattr(bindings, "_impls", bindings._impls.copy())
    provide(ClockPort, FakeClock(datetime(2026, 7, 20, 4, 30, tzinfo=timezone.utc)))
    with client:
        try:
            draft = client.post("/api/applications", headers=headers("INSTITUTION", SUNRISE),
                json=dict(institution_id=str(SUNRISE), category="NEW_PROGRAMME", academic_year="2027-28"))
            assert draft.status_code == 201, draft.text
            experts = []
            for index in range(4):
                created = client.post("/api/evc/experts", headers=MANAGER,
                    json=dict(user_ref=str(ref(index)), region="SOUTHERN", expertise_tags=["DEMO", f"DEMO_DOMAIN_{index % 2 + 1:02d}"]))
                assert created.status_code == 201, created.text
                expert = UUID(created.json()["id"])
                experts.append(expert)
                declared = client.post(f"/api/evc/experts/{expert}/availability", headers=MANAGER,
                    json=dict(items=[dict(date=DAY.isoformat(), slot_part=part, available=True) for part in ("AM", "PM")]))
                assert declared.status_code == 200, declared.text
            conflict = client.post("/api/evc/coi", headers=MANAGER,
                json=dict(expert_id=str(experts[0]), institution_ref=str(SUNRISE), source="RECUSAL", reason_code="RECUSAL"))
            assert conflict.status_code == 200, conflict.text
            with new_session() as session, session.begin():
                session.add(EvcRequest(id=ref("request"), application_id=UUID(draft.json()["id"]), institution_ref=SUNRISE,
                    region="Southern", category="NEW_PROGRAMME", requested_at=port(ClockPort).now(), earliest_date=DAY,
                    due_by=DAY + timedelta(days=7), status="QUEUED", priority_key="DEMO", ruleset_key="aph-2024-27@r1"))
            yield SimpleNamespace(client=client, experts=experts, application_id=UUID(draft.json()["id"]))
        finally:
            with new_session() as session, session.begin():
                session.execute(text("TRUNCATE evc.assignment_expert, evc.assignment, evc.availability, evc.coi, "
                                     "evc.slot, evc.schedule_run, evc.evc_request, evc.expert"))


def preview(env, actor=MANAGER, request_id=None, **params):
    return env.client.get(f"/api/evc/requests/{request_id or ref('request')}/panel-preview", headers=actor,
                          params=dict(date=DAY.isoformat(), slot_part="AM", **params))


def fingerprint():
    with new_session() as session:
        return tuple(session.scalar(select(func.count()).select_from(model)) for model in
                     (EvcRequest, Expert, Assignment, AssignmentExpert, ScheduleRun, DomainEvent, LedgerEntry, PersonalData))


def override_rules(monkeypatch, transform, *, default="aph-2024-27@r1"):
    real = port(RulesetPort)
    seen = []
    class ObservedRules:
        def get(self, key):
            seen.append(key)
            return transform(real.get(key))
        def default_key(self):
            return default
        def route_for(self, category, key):
            return real.route_for(category, key)
    monkeypatch.setattr(bindings, "_impls", bindings._impls.copy())
    provide(RulesetPort, ObservedRules())
    return seen


def test_label_ranked_explanations_determinism_and_zero_writes(selector_env):
    before = fingerprint()
    first = preview(selector_env)
    assert first.status_code == 200, first.text
    data = first.json()
    assert data == preview(selector_env).json()
    assert data["selector_label"] == SELECTOR_LABEL == "SIMULATED authorised selector (stand-in)"
    assert data["simulation_status"] == "SIMULATED" and data["source_status"] == "DEMO_ASSUMPTION"
    assert data["identity_status"] == "P3_USER_REF_UNVERIFIED"
    assert data["criteria_order"] == ["ELIGIBILITY", "EXPERTISE_MATCH", "WORKLOAD", "ROTATION", "EXPERT_ID"]
    assert data["status"] == "SELECTED" and len(data["panel"]) == data["requested_size"] == 3
    assert str(selector_env.experts[0]) not in data["panel"]  # The COI cannot re-enter through ranking.
    assert data["panel"] == sorted(str(expert) for expert in selector_env.experts[1:])
    assert [row["expert_id"] for row in data["ranked_experts"] if row["selected"]] == data["panel"]
    for index, row in enumerate(data["ranked_experts"], 1):
        assert row["rank"] == index and row["matched_expertise_tags"] == ["DEMO"]
        assert row["criterion_scores"] == dict(eligibility_passed=True, expertise_matches=1, workload_assignments=0,
            last_assignment_date=None, rotation_days=None, rotation_ordinal=0)
        assert "user_ref" not in row and "personal_ref" not in row
    assert fingerprint() == before


def test_shortage_stays_labelled_and_does_not_create_a_partial_panel(selector_env):
    with new_session() as session, session.begin():
        session.get(Expert, selector_env.experts[1]).active = False
    before = fingerprint()
    response = preview(selector_env)
    assert response.status_code == 200
    assert response.json()["status"] == "INSUFFICIENT_CANDIDATES" and response.json()["panel"] == []
    assert response.json()["eligible_count"] == 2 and response.json()["selector_label"] == SELECTOR_LABEL
    assert not any(row["selected"] for row in response.json()["ranked_experts"])
    assert fingerprint() == before


@pytest.mark.parametrize("published", [False, True])
def test_history_before_window_and_future_commitments_explain_workload_and_rotation(selector_env, published):
    with new_session() as session, session.begin():
        session.add(ScheduleRun(run_id=ref("run"), algorithm="EDF", parameters={}, metrics={},
                                created_at=port(ClockPort).now(), status="PROPOSED"))
        session.add_all([Slot(id=ref("past"), date=DAY - timedelta(days=10), slot_part="AM", capacity=3),
                         Slot(id=ref("future"), date=DAY + timedelta(days=2), slot_part="AM", capacity=3)])
        session.flush()
        for index, token in enumerate(("past", "future"), 1):
            session.add(Assignment(id=ref(f"assignment-{token}"), evc_request_id=ref("request"), slot_id=ref(token),
                expert_ids=[selector_env.experts[index]], panel_role="DEMO_MEMBER", published=published, schedule_run_id=ref("run")))
    before = fingerprint()
    result = preview(selector_env).json()
    assert result["panel"] == [str(selector_env.experts[3]), str(selector_env.experts[2]), str(selector_env.experts[1])]
    scores = {row["expert_id"]: row["criterion_scores"] for row in result["ranked_experts"]}
    assert scores[str(selector_env.experts[1])]["workload_assignments"] == 1
    assert scores[str(selector_env.experts[1])]["last_assignment_date"] == (DAY - timedelta(days=10)).isoformat()
    assert scores[str(selector_env.experts[2])]["workload_assignments"] == 1
    assert scores[str(selector_env.experts[2])]["last_assignment_date"] is None
    assert fingerprint() == before


def test_preview_uses_pinned_policy_instead_of_current_default(selector_env, monkeypatch):
    def changed(rules):
        return replace(rules, expert_pool={**rules.expert_pool, "selector": {**rules.expert_pool["selector"], "panel_size": 2}})
    seen = override_rules(monkeypatch, changed, default="aph-2024-27@r3-DEMO")
    result = preview(selector_env)
    assert result.status_code == 200 and result.json()["requested_size"] == 2
    assert result.json()["ruleset_key"] == "aph-2024-27@r1" and set(seen) == {"aph-2024-27@r1"}


def test_missing_selector_policy_is_coded_and_existing_overlay_inherits_policy(selector_env, monkeypatch):
    real = port(RulesetPort)
    assert real.get("aph-2024-27@r3-DEMO").expert_pool["selector"] == real.get("aph-2024-27@r1").expert_pool["selector"]
    override_rules(monkeypatch, lambda rules: replace(rules, expert_pool={key: value for key, value in rules.expert_pool.items() if key != "selector"}))
    response = preview(selector_env)
    assert response.status_code == 422 and response.json()["detail"] == "SELECTOR_POLICY_UNAVAILABLE"


def test_institution_and_foreign_ro_cannot_read_preview(selector_env):
    before = fingerprint()
    assert preview(selector_env, headers("INSTITUTION", SUNRISE)).status_code == 403
    assert preview(selector_env, dict(headers("RO_OFFICER"), **{"X-Demo-Region": "Northern"})).status_code == 403
    assert preview(selector_env, headers("RO_OFFICER")).status_code == 403
    assert preview(selector_env, dict(headers("RO_OFFICER"), **{"X-Demo-Region": "Southern"})).status_code == 200
    assert preview(selector_env, headers("AUDITOR")).status_code == 200
    assert fingerprint() == before


def test_cross_region_preview_requires_global_pool_scope(selector_env, monkeypatch):
    created = selector_env.client.post("/api/evc/experts", headers=MANAGER,
        json=dict(user_ref=str(ref("foreign")), region="NORTHERN", expertise_tags=["DEMO"]))
    assert created.status_code == 201
    expert = created.json()["id"]
    declared = selector_env.client.post(f"/api/evc/experts/{expert}/availability", headers=MANAGER,
        json=dict(items=[dict(date=DAY.isoformat(), slot_part="AM", available=True)]))
    assert declared.status_code == 200
    override_rules(monkeypatch, lambda rules: replace(rules, expert_pool={**rules.expert_pool, "region_rule": "ANY_REGION"}))
    denied = preview(selector_env, dict(headers("RO_OFFICER"), **{"X-Demo-Region": "Southern"}))
    assert denied.status_code == 403 and denied.json()["detail"] == "SELECTOR_CROSS_REGION_SCOPE_FORBIDDEN"
    permitted = preview(selector_env)
    assert permitted.status_code == 200 and expert in {row["expert_id"] for row in permitted.json()["ranked_experts"]}


@pytest.mark.parametrize("status", ["PUBLISHED", "DONE", "CANCELLED"])
def test_nonschedulable_requests_are_clean_errors(selector_env, status):
    with new_session() as session, session.begin():
        session.get(EvcRequest, ref("request")).status = status
    response = preview(selector_env)
    assert response.status_code == 422 and response.json()["detail"] == "SELECTOR_REQUEST_NOT_SCHEDULABLE"


def test_missing_query_unknown_request_and_stale_case_reference(selector_env):
    path = f"/api/evc/requests/{ref('request')}/panel-preview"
    assert selector_env.client.get(path, headers=MANAGER).status_code == 422
    assert selector_env.client.get(path, headers=MANAGER, params=dict(date="INVALID", slot_part="AM")).status_code == 422
    assert preview(selector_env, request_id=ref("missing")).status_code == 404
    with new_session() as session, session.begin():
        session.get(EvcRequest, ref("request")).region = "Northern"
    response = preview(selector_env)
    assert response.status_code == 409 and response.json()["detail"] == "SELECTOR_CASE_REFERENCE_CHANGED"
