"""Open-only Re-Scrutiny, rejected-only rollover and preserved response lineage."""
import json
from pathlib import Path
from uuid import UUID, NAMESPACE_URL, uuid5

from alembic import command as migration
from alembic.config import Config
import pytest
from sqlalchemy import func, select

from app.platform.db import new_session
from app.platform.registry import port
from app.platform.models import CaseNote, DomainEvent
from app.workflow.models import Deficiency, DeficiencyItem
from app.workflow import guards
from app.workflow.commands import GuardFacts
from contracts.ports import LedgerPort
from conftest import NORTHFIELD, SUNRISE, headers
from test_deficiency_loop import api, act, create, read, INST, OFFICER, REF

FIVE = ["DEMO_CORE_REFERENCE", "DEMO_ADDITIONAL_REFERENCE", "DEMO_FACILITY_REFERENCE",
        "DEMO_STAFF_REFERENCE", "DEMO_SAFETY_REFERENCE"]


def scope(api, case_id, actor=INST):
    response = api.get(f"/api/cases/{case_id}/rescrutiny", headers=actor)
    assert response.status_code == 200, response.text
    return response.json()


def record_five(api, case_id):
    response = act(api, case_id, "record_deficiency", 1, {"item_keys": FIVE})
    assert response.status_code == 200, response.text
    return scope(api, case_id)


def comply(api, case_id, data):
    responses = [{"item_id": item["id"], "response_ref": str(uuid5(NAMESPACE_URL,
        f"rescrutiny:response:{data['round_no']}:{item['item_key']}"))} for item in data["items"]]
    result = act(api, case_id, "submit_compliance", data["version"], {"responses": responses}, INST)
    assert result.status_code == 200, result.text
    return scope(api, case_id)


def decide(api, case_id, data, accepted, *, note=None):
    return api.post(f"/api/cases/{case_id}/deficiencies/{data['deficiency_id']}/review", headers=OFFICER,
        json={"expected_version": data["version"], "decisions": [{"item_id": item["id"],
            "state": "ACCEPTED" if item["item_key"] in accepted else "REJECTED",
            "reason_code": "DEMO_RESPONSE_ACCEPTED" if item["item_key"] in accepted else "DEMO_RESPONSE_REJECTED",
            "note": note} for item in data["items"]]})


def timeline(api, case_id):
    result = api.get(f"/api/cases/{case_id}/timeline", headers=INST)
    assert result.status_code == 200
    return result.json()


def test_five_items_three_accepted_two_carried_and_response_lineage(api):
    case_id = create(api)
    data = record_five(api, case_id)
    assert len(data["items"]) == 5 and all(item["state"] == "OPEN" for item in data["items"])
    data = comply(api, case_id, data)
    first = {item["item_key"]: item for item in data["items"]}
    actions = api.get(f"/api/cases/{case_id}", headers=OFFICER).json()["available_actions"]
    assert next(action for action in actions if action["action"] == "start_rescrutiny")["enabled"]
    before_start = timeline(api, case_id)
    started = act(api, case_id, "start_rescrutiny", data["version"])
    assert started.status_code == 200, started.text
    assert started.json()["stage"] == "RESCRUTINY"
    assert started.json()["opened_deadlines"] == started.json()["closed_deadlines"] == []
    after_start = timeline(api, case_id)
    assert [e["event_type"] for e in after_start[len(before_start):]] == [
        "wf.transition_applied", "wf.stage_exited", "wf.stage_entered"]
    data = scope(api, case_id)
    assert {item["item_key"]: item["response_ref"] for item in data["items"]} == {
        key: item["response_ref"] for key, item in first.items()}
    accepted = set(sorted(FIVE)[:3])
    partial = {**data, "items": [item for item in data["items"] if item["item_key"] in accepted]}
    response = decide(api, case_id, partial, accepted, note="Fictional per-item acceptance note")
    assert response.status_code == 200, response.text
    remaining = scope(api, case_id)
    assert len(remaining["items"]) == 2
    assert not accepted & {item["item_key"] for item in remaining["items"]}
    before_reject = timeline(api, case_id)
    result = decide(api, case_id, remaining, set(), note="Fictional per-item rejection note")
    assert result.status_code == 200, result.text
    second = scope(api, case_id)
    assert second["round_no"] == 2 and len(second["items"]) == 2
    assert {item["item_key"] for item in second["items"]} == set(FIVE) - accepted
    for item in second["items"]:
        assert item["state"] == "OPEN" and item["response_ref"] is None
        assert item["previous_item_id"] == first[item["item_key"]]["id"]
        assert [h["round_no"] for h in item["response_history"]] == [1, 2]
        assert item["response_history"][0]["response_ref"] == first[item["item_key"]]["response_ref"]
        assert item["response_history"][0]["state"] == "REJECTED"
    suffix = timeline(api, case_id)[len(before_reject):]
    assert [e["event_type"] for e in suffix] == ["wf.deficiency_item_decided"] * 2 + [
        "wf.deficiency_superseded", "dl.deadline_paused", "dl.deadline_opened", "wf.transition_applied",
        "wf.deficiency_recorded", "wf.stage_exited", "wf.stage_entered"]
    assert suffix[2]["payload"]["next_deficiency_id"] == second["deficiency_id"]
    second = comply(api, case_id, second)
    for item in second["items"]:
        assert item["response_ref"] != first[item["item_key"]]["response_ref"]
        assert [h["response_ref"] for h in item["response_history"]] == [
            first[item["item_key"]]["response_ref"], item["response_ref"]]
    before_accept = timeline(api, case_id)
    result = decide(api, case_id, second, set(FIVE))
    assert result.status_code == 200, result.text
    assert scope(api, case_id)["items"] == []
    assert api.get(f"/api/cases/{case_id}", headers=INST).json()["stage"] == "EVC"
    assert [e["event_type"] for e in timeline(api, case_id)[len(before_accept):]] == [
        "wf.deficiency_item_decided", "wf.deficiency_item_decided", "wf.deficiency_closed",
        "dl.deadline_opened", "evc.request_created",
        "wf.transition_applied", "wf.stage_exited", "wf.stage_entered"]
    rounds = read(api, case_id)["rounds"]
    assert [(r["status"], r["closure_kind"], len(r["items"])) for r in rounds] == [
        ("CLOSED", "SUPERSEDED", 5), ("CLOSED", "ACCEPTED", 2)]
    assert sum(item["state"] == "ACCEPTED" for item in rounds[0]["items"]) == 3
    assert "Fictional per-item" not in json.dumps(timeline(api, case_id))
    with new_session() as session:
        assert session.scalar(select(func.count()).select_from(CaseNote)) == 5
        notes = session.scalars(select(DomainEvent.note_ref).where(DomainEvent.event_type == "wf.deficiency_item_decided")).all()
        assert sum(ref is not None for ref in notes) == 5
    assert api.get("/api/ledger/verify", headers=headers("AUDITOR")).json()["ok"]


def test_rescrutiny_empty_scoped_and_read_only(api):
    case_id = create(api)
    first = scope(api, case_id)
    assert first["items"] == [] and first["deficiency_id"] is None
    assert scope(api, case_id) == first
    foreign = headers("INSTITUTION", NORTHFIELD)
    assert api.get(f"/api/cases/{case_id}/rescrutiny", headers=foreign).status_code == 403
    ro = headers("RO_OFFICER") | {"X-Demo-Region": "DEMO_OTHER_REGION"}
    assert api.get(f"/api/cases/{case_id}/rescrutiny", headers=ro).status_code == 403
    assert api.get(f"/api/cases/{uuid5(NAMESPACE_URL, 'rescrutiny:missing')}/rescrutiny", headers=INST).status_code == 404


def test_start_review_uses_stored_responses_and_does_not_accept_rewrites(api):
    case_id = create(api)
    data = comply(api, case_id, record_five(api, case_id))
    result = act(api, case_id, "start_rescrutiny", data["version"], {"response_ref": REF})
    assert result.status_code == 422 and result.json()["detail"] == "RESCRUTINY_USES_STORED_RESPONSES"
    assert scope(api, case_id) == data
    result = act(api, case_id, "start_rescrutiny", data["version"])
    assert result.status_code == 200, result.text
    assert act(api, case_id, "start_rescrutiny", data["version"]).status_code == 409


def test_accepted_items_cannot_be_reviewed_or_submitted_in_the_new_round(api):
    case_id = create(api)
    data = comply(api, case_id, record_five(api, case_id))
    accepted = set(sorted(FIVE)[:3])
    result = decide(api, case_id, data, accepted)
    assert result.status_code == 200, result.text
    current = scope(api, case_id)
    old = next(item for item in data["items"] if item["item_key"] in accepted)
    result = act(api, case_id, "submit_compliance", current["version"], {
        "responses": [{"item_id": old["id"], "response_ref": REF}]}, INST)
    assert result.status_code == 422 and result.json()["detail"] == "DEFICIENCY_RESPONSES_INCOMPLETE"
    current = comply(api, case_id, current)
    request = {"expected_version": current["version"], "decisions": [
        {"item_id": old["id"], "state": "ACCEPTED", "reason_code": "DEMO_RESPONSE_ACCEPTED"}]}
    before = timeline(api, case_id)
    url = f"/api/cases/{case_id}/deficiencies/{current['deficiency_id']}/review"
    assert api.post(url, headers=OFFICER, json=request).status_code == 422
    assert timeline(api, case_id) == before


def test_rollover_failure_rolls_back_decisions_new_round_clocks_and_notes(api, monkeypatch):
    case_id = create(api)
    data = comply(api, case_id, record_five(api, case_id))
    before_rounds = read(api, case_id)
    before_events = timeline(api, case_id)
    before_clocks = api.get("/api/deadlines", params={"subject_id": case_id}, headers=INST).json()
    ledger = port(LedgerPort)
    append = ledger.append
    def failing(uow, event):
        result = append(uow, event)
        if event.event_type == "wf.deficiency_recorded":
            raise RuntimeError("DEMO_ROLLOVER_FAILURE")
        return result
    monkeypatch.setattr(ledger, "append", failing)
    with pytest.raises(RuntimeError, match="DEMO_ROLLOVER_FAILURE"):
        decide(api, case_id, data, set(), note="Fictional rollback remark")
    assert read(api, case_id) == before_rounds
    assert timeline(api, case_id) == before_events
    assert api.get("/api/deadlines", params={"subject_id": case_id}, headers=INST).json() == before_clocks
    with new_session() as session:
        assert session.scalar(select(func.count()).select_from(Deficiency)) == 1
        assert session.scalar(select(func.count()).select_from(DeficiencyItem)) == 5
        assert session.scalar(select(func.count()).select_from(CaseNote)) == 0


def test_last_stage_closes_without_inventing_letter_or_terminal_outcome(api):
    response = api.post("/api/applications", headers=INST, json={"institution_id": str(SUNRISE),
        "category": "CHANGE_OF_NAME", "academic_year": "2027-28", "submit": True, "dsc_present": True,
        "items": [{"item_key": "DEMO_CORE_REFERENCE", "state": "PROVIDED", "document_ref": REF}]})
    assert response.status_code == 201, response.text
    case_id = response.json()["id"]
    data = comply(api, case_id, record_five(api, case_id))
    result = decide(api, case_id, data, set(FIVE))
    assert result.status_code == 200, result.text
    case = api.get(f"/api/cases/{case_id}", headers=INST).json()
    assert case["status"] == "IN_PROCESS" and case["stage"] == "RESCRUTINY"
    assert scope(api, case_id)["items"] == []
    repeat = act(api, case_id, "record_deficiency", case["version"], {"item_keys": [FIVE[0]]})
    assert repeat.status_code == 422 and repeat.json()["detail"] == "DEFICIENCY_ITEM_ALREADY_ACCEPTED"


def test_auto_advance_guard_failure_rolls_back_acceptance_and_closure(api, monkeypatch):
    case_id = create(api)
    data = comply(api, case_id, record_five(api, case_id))
    before = timeline(api, case_id)
    monkeypatch.setattr(guards, "_fact_loader", lambda *args: GuardFacts(has_assignment=False))
    result = decide(api, case_id, data, set(FIVE), note="Fictional guarded remark")
    assert result.status_code == 422 and result.json()["detail"] == "ASSIGNMENT_REQUIRED"
    assert scope(api, case_id) == data
    assert timeline(api, case_id) == before
    assert read(api, case_id)["rounds"][0]["status"] == "RESPONDED"
    with new_session() as session:
        assert session.scalar(select(func.count()).select_from(CaseNote)) == 0


def test_migration_preserves_accepted_rounds_and_responses(api):
    case_id = create(api)
    data = comply(api, case_id, record_five(api, case_id))
    assert decide(api, case_id, data, set(FIVE)).status_code == 200
    before = read(api, case_id)
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    cfg.attributes["configure_logger"] = False
    migration.downgrade(cfg, "wf_0004")
    migration.upgrade(cfg, "heads")
    assert read(api, case_id) == before
