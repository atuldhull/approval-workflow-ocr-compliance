"""Persisted, API-driven deficiency rounds with real ledger and P2 boundary fakes."""
import json
from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.platform.db import new_session, unit_of_work
from app.platform.registry import port, provide
from app.workflow import guards, deficiency
from app.workflow.commands import GuardFacts, WorkflowValidationFailed
from app.workflow.models import CaseState, Deficiency, DeficiencyItem
from app.workflow.storage import visits
from conftest import SUNRISE, NORTHFIELD, headers
from contracts.errors import Conflict
from contracts.fakes import FakeDeadlines
from contracts.ports import DeadlinePort, LedgerPort
from contracts.types import Principal
from contracts.enums import Role

INST = headers("INSTITUTION", SUNRISE)
OFFICER = headers("SCRUTINY_COMMITTEE")
KEYS = ["DEMO_CORE_REFERENCE", "DEMO_ADDITIONAL_REFERENCE"]
REF = "b870b346-498b-55b1-945e-c0e24d268980"  # DEMO fixture document reference (UUID5), accepted only in DEMO_MODE


@pytest.fixture
def api(client, monkeypatch):
    with client:
        monkeypatch.setattr(guards, "_fact_loader", lambda *args: GuardFacts(has_assignment=True))
        yield client


def create(api):
    result = api.post("/api/applications", headers=INST, json={"institution_id": str(SUNRISE),
        "category": "NEW_PROGRAMME", "academic_year": "2027-28", "submit": True, "dsc_present": True,
        "items": [{"item_key": "DEMO_CORE_REFERENCE", "state": "PROVIDED", "document_ref": REF}]})
    assert result.status_code == 201, result.text
    return result.json()["id"]


def act(api, case_id, action, version, payload=None, actor=OFFICER):
    return api.post(f"/api/cases/{case_id}/actions", headers=actor,
        json={"action": action, "expected_version": version, "reason_code": "DEMO_REASON", "payload": payload or {}})


def read(api, case_id):
    response = api.get(f"/api/cases/{case_id}/deficiencies", headers=INST)
    assert response.status_code == 200, response.text
    return response.json()


def record(api, case_id, version=1):
    result = act(api, case_id, "record_deficiency", version, {"item_keys": KEYS})
    assert result.status_code == 200, result.text
    return read(api, case_id)


def respond(api, case_id, data):
    current = data["rounds"][-1]
    result = act(api, case_id, "submit_compliance", data["version"],
        {"responses": [{"item_id": item["id"], "response_ref": REF} for item in current["items"]]}, INST)
    assert result.status_code == 200, result.text
    return read(api, case_id)


def review(api, case_id, data, state="ACCEPTED", note=None):
    current = data["rounds"][-1]
    return api.post(f"/api/cases/{case_id}/deficiencies/{current['id']}/review", headers=OFFICER,
        json={"expected_version": data["version"], "decisions": [{"item_id": item["id"], "state": state,
            "reason_code": "DEMO_RESPONSE_ACCEPTED" if state == "ACCEPTED" else "DEMO_RESPONSE_REJECTED"}
            for item in current["items"]], "note": note})


def test_two_rounds_trace_responses_close_and_advance(api):
    case_id = create(api)
    data = respond(api, case_id, record(api, case_id))
    result = review(api, case_id, data, "REJECTED", note="Fictional officer remark")
    assert result.status_code == 200, result.text
    data = result.json()
    assert [r["closure_kind"] for r in data["rounds"]] == ["SUPERSEDED", None]
    assert all(i["previous_item_id"] for i in data["rounds"][1]["items"])
    data = respond(api, case_id, data)
    result = review(api, case_id, data, note="Fictional officer remark")
    assert result.status_code == 200, result.text
    data = result.json()
    assert [r["closure_kind"] for r in data["rounds"]] == ["SUPERSEDED", "ACCEPTED"]
    assert all(i["state"] == "ACCEPTED" and i["response_ref"] == REF for i in data["rounds"][1]["items"])
    assert data["response_window"] == {"rule_id": "INSTITUTION_RESPONSE", "value": 15, "unit": "calendar_days",
        "source_status": "DEMO_ASSUMPTION", "assumption_code": "DEFICIENCY_RESPONSE_WINDOW_UNCONFIRMED"}
    assert api.get(f"/api/cases/{case_id}", headers=INST).json()["stage"] == "EVC"
    timeline = api.get(f"/api/cases/{case_id}/timeline", headers=INST).json()
    names = [event["event_type"] for event in timeline]
    assert names.count("wf.deficiency_recorded") == names.count("wf.compliance_submitted") == 2
    assert names.count("wf.deficiency_closed") == names.count("wf.deficiency_superseded") == 1
    assert names.count("wf.deficiency_item_responded") == names.count("wf.deficiency_item_decided") == 4
    assert "Fictional officer remark" not in json.dumps(timeline)
    assert api.get("/api/ledger/verify", headers=headers("AUDITOR")).json()["ok"]


def test_deadline_fake_exact_pairing_and_order(api):
    case_id = create(api)
    fake = FakeDeadlines()
    provide(DeadlinePort, fake)
    data = respond(api, case_id, record(api, case_id))
    result = review(api, case_id, data, "REJECTED")
    assert result.status_code == 200, result.text
    data = respond(api, case_id, result.json())
    assert review(api, case_id, data).status_code == 200
    assert [(op, rule) for op, subject, rule in fake.calls] == [
        ("pause", "AICTE_PROCESSING"), ("open", "INSTITUTION_RESPONSE"),
        ("close", "INSTITUTION_RESPONSE"), ("resume", "AICTE_PROCESSING")] * 2 + [("open", "EVC_PROCESSING")]
    assert all(subject.id == UUID(case_id) for _, subject, _ in fake.calls)


@pytest.mark.parametrize("keys", [[], ["UNKNOWN_KEY"], [KEYS[0], KEYS[0]]])
def test_record_requires_known_unique_nonempty_keys(api, keys):
    case_id = create(api)
    result = act(api, case_id, "record_deficiency", 1, {"item_keys": keys})
    assert result.status_code == 422
    assert read(api, case_id)["rounds"] == []


def test_no_open_round_and_incomplete_or_foreign_mappings_refused(api):
    case_id = create(api)
    with new_session() as session, session.begin():
        from app.workflow.case_service import projection, state_for
        state = state_for(session, projection(session, UUID(case_id)))
        state.current_stage = "DEFICIENT"
        session.add(state)
    response = act(api, case_id, "submit_compliance", 1, {"responses": [{"item_id": REF, "response_ref": REF}]}, INST)
    assert response.status_code == 422 and response.json()["detail"] == "NO_OPEN_DEFICIENCY"
    # Separate real case exercises exact mapping without forged stage setup.
    case_id = create(api)
    data = record(api, case_id)
    item = data["rounds"][0]["items"][0]
    for responses in ([], [{"item_id": item["id"], "response_ref": REF}], [{"item_id": REF, "response_ref": REF}]):
        result = act(api, case_id, "submit_compliance", data["version"], {"responses": responses}, INST)
        assert result.status_code == 422 and result.json()["detail"] == "DEFICIENCY_RESPONSES_INCOMPLETE"
    assert all(i["state"] == "OPEN" for i in read(api, case_id)["rounds"][0]["items"])


def test_open_or_rejected_items_cannot_close_and_fake_counts_cannot_bypass(api):
    case_id = create(api)
    data = record(api, case_id)
    actor = Principal(UUID(INST["X-Demo-User"]), Role.INSTITUTION, institution_id=SUNRISE)
    with pytest.raises(WorkflowValidationFailed, match="OPEN_DEFICIENCY_ITEMS"):
        with unit_of_work(actor) as uow:
            row = uow.session.get(Deficiency, UUID(data["rounds"][0]["id"]))
            deficiency.close(uow, row, {}, row.opened_at)
    data = respond(api, case_id, data)
    rejected = review(api, case_id, data, "REJECTED")
    assert rejected.status_code == 200 and rejected.json()["rounds"][0]["closure_kind"] == "SUPERSEDED"
    assert act(api, case_id, "advance", rejected.json()["version"]).status_code == 422
    assert act(api, case_id, "record_deficiency", rejected.json()["version"], {"item_keys": KEYS}).status_code == 422


def test_legal_pause_failure_rolls_back_round_items_notes_state_visits_and_ledger(api):
    case_id = create(api)
    before_events = api.get(f"/api/cases/{case_id}/timeline", headers=INST).json()
    class RefusingDeadlines(FakeDeadlines):
        def pause_internal(self, uow, subject, rule_id):
            self.calls.append(("pause_refused", subject, rule_id))
            raise Conflict("LEGAL_CLOCK_REFUSED")
    fake = RefusingDeadlines()
    provide(DeadlinePort, fake)
    result = api.post(f"/api/cases/{case_id}/actions", headers=OFFICER, json={"action": "record_deficiency",
        "expected_version": 1, "reason_code": "DEMO_REASON", "note": "must roll back", "payload": {"item_keys": KEYS}})
    assert result.status_code == 409 and result.json()["detail"] == "LEGAL_CLOCK_REFUSED"
    with new_session() as session:
        from app.platform.models import CaseNote
        assert session.scalar(select(func.count()).select_from(CaseNote)) == 0
        assert session.scalar(select(func.count()).select_from(Deficiency)) == 0
        assert session.scalar(select(func.count()).select_from(DeficiencyItem)) == 0
        assert session.get(CaseState, UUID(case_id)) is None  # adoption rolled back too
        assert len(session.execute(select(visits).where(visits.c.application_id == UUID(case_id))).all()) == 1
    assert api.get(f"/api/cases/{case_id}/timeline", headers=INST).json() == before_events
    assert [op for op, *_ in fake.calls] == ["pause_refused"]


def test_review_scope_version_and_partial_review(api):
    case_id = create(api)
    data = respond(api, case_id, record(api, case_id))
    current = data["rounds"][0]
    url = f"/api/cases/{case_id}/deficiencies/{current['id']}/review"
    body = {"expected_version": data["version"], "decisions": [{"item_id": current["items"][0]["id"],
        "state": "ACCEPTED", "reason_code": "DEMO_RESPONSE_ACCEPTED"}]}
    assert api.post(url, headers=INST, json=body).status_code == 403
    assert api.get(f"/api/cases/{case_id}/deficiencies", headers=headers("INSTITUTION", NORTHFIELD)).status_code == 403
    partial = api.post(url, headers=OFFICER, json=body)
    assert partial.status_code == 200 and partial.json()["rounds"][0]["status"] == "RESPONDED"
    assert api.post(url, headers=OFFICER, json=body).status_code == 409


def test_review_ledger_failure_rolls_back_decisions_notes_and_version(api, monkeypatch):
    case_id = create(api)
    data = respond(api, case_id, record(api, case_id))
    before = api.get(f"/api/cases/{case_id}/timeline", headers=INST).json()
    ledger = port(LedgerPort)
    append = ledger.append
    def failing(uow, event):
        append(uow, event)
        raise RuntimeError("DEMO_LEDGER_FAILURE")
    monkeypatch.setattr(ledger, "append", failing)
    with pytest.raises(RuntimeError, match="DEMO_LEDGER_FAILURE"):
        review(api, case_id, data, note="rollback review note")
    assert read(api, case_id) == data
    assert api.get(f"/api/cases/{case_id}/timeline", headers=INST).json() == before
    with new_session() as session:
        from app.platform.models import CaseNote
        assert session.scalar(select(func.count()).select_from(CaseNote)) == 0
