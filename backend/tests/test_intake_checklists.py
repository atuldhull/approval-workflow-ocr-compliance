"""Fictional Annexure-2 inputs: real API, database, ledger and deadline ports."""
from copy import deepcopy
import json
from pathlib import Path
from uuid import UUID, NAMESPACE_URL, uuid5

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from sqlalchemy import func, select

from app.intake.models import Application, ApplicationItem, StageVisit
from app.intake.rules import SubmissionBlocked, ensure_complete
from app.intake.shapes import ItemIn, SubmissionIn
from app.platform.db import new_session
from app.platform.models import DomainEvent
from app.platform.registry import port, provide as provide_port
from app.workflow import guards
from app.workflow.checklists import validate_checklists
from app.workflow.commands import GuardFacts
from app.workflow.loader import sync_rulesets
from app.workflow.models import Ruleset
from app.workflow.registry import RulesetRegistry, _read
from conftest import SUNRISE, NORTHFIELD, headers
from contracts.errors import Conflict, ValidationFailed
from contracts.ports import DeadlinePort, DeadlineRuleParserPort
from contracts.fakes import FakeDeadlineRuleParser

ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / "rulesets/aph-2024-27/r1"
DOCUMENT = uuid5(NAMESPACE_URL, "DEMO:intake-document-reference")
AUTH = headers("INSTITUTION", SUNRISE)


@pytest.fixture
def api(client):
    with client:
        yield client


def draft(api, category="NEW_INSTITUTION"):
    response = api.post("/api/applications", headers=AUTH, json={"institution_id": str(SUNRISE),
        "category": category, "academic_year": "2027-28"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def provide(api, key):
    response = api.post(f"/api/applications/{key}/items", headers=AUTH,
        json={"items": [{"item_key": "DEMO_CORE_REFERENCE", "document_ref": str(DOCUMENT)}]})
    assert response.status_code == 200, response.text
    return response.json()


def count_events():
    with new_session() as session:
        return session.scalar(select(func.count()).select_from(DomainEvent))


def test_each_category_blocked_and_allowed_and_all_route_plans_match_yaml(api):
    raw = _read(FOLDER / "routes.yaml")["routes"]
    assert len(raw) == 24
    for category, route in raw.items():
        key = draft(api, category)
        missing = api.post(f"/api/applications/{key}/submit", headers=AUTH, json={"dsc_present": True})
        assert missing.status_code == 422, (category, missing.text)
        assert missing.json()["reason_code"] == "MANDATORY_ITEMS_MISSING"
        assert missing.json()["missing_item_keys"] == ["DEMO_CORE_REFERENCE"]
        both = api.post(f"/api/applications/{key}/submit", headers=AUTH)
        assert both.status_code == 422 and both.json()["missing_item_keys"] == ["DEMO_CORE_REFERENCE", "DSC"]
        items = provide(api, key)
        assert any(i["state"] == "MISSING" and not i["mandatory"] for i in items["items"])
        no_dsc = api.post(f"/api/applications/{key}/submit", headers=AUTH, json={"dsc_present": False})
        assert no_dsc.status_code == 422 and no_dsc.json()["missing_item_keys"] == ["DSC"]
        response = api.post(f"/api/applications/{key}/submit", headers=AUTH, json={"dsc_present": True})
        assert response.status_code == 200, (category, response.text)
        body = response.json()
        expected = [{"stage": s, "when": "always"} if isinstance(s, str) else s for s in route["stages"]]
        assert body["stages"] == expected and body["route_id"] == category
        assert body["ruleset_key"] == "aph-2024-27@r1"
        assert body["clause_citation"] == route["clause_citation"]
        # verified routes cite their handbook page and add no assumption; the demo checklist still does
        citation = body["clause_citation"]
        assert citation["status"] in {"VERIFIED", "DEMO_ASSUMPTION"}
        assert (citation["status"] == "VERIFIED") == (citation.get("assumption_ref") is None) and citation["page"] >= 1
        if citation.get("assumption_ref"):
            assert citation["assumption_ref"] in body["assumptions"]
        assert body["assumptions"] == sorted(body["assumptions"])
        assert "INTAKE_ANNEXURE_2_UNKNOWN" in body["assumptions"]
        assert body["dsc_present"] is True
    assert api.get("/api/ledger/verify", headers=headers("AUDITOR")).json()["ok"]


@pytest.mark.parametrize("provided,dsc,required", [(a, b, c) for a in (False, True) for b in (False, True) for c in (False, True)])
def test_pure_required_optional_and_dsc_matrix(provided, dsc, required):
    config = {"dsc_required": required, "items": [{"item_key": "DEMO_REQUIRED", "mandatory": True},
                                                {"item_key": "DEMO_OPTIONAL", "mandatory": False}]}
    expected = ([] if provided else ["DEMO_REQUIRED"]) + (["DSC"] if required and not dsc else [])
    if expected:
        with pytest.raises(SubmissionBlocked) as error:
            ensure_complete(config, {"DEMO_REQUIRED"} if provided else set(), dsc)
        assert error.value.missing_item_keys == tuple(sorted(expected))
    else:
        ensure_complete(config, {"DEMO_REQUIRED"}, dsc)


@pytest.mark.parametrize("invalid", ["category_missing", "category_extra", "duplicate", "bad_key", "mandatory_string", "dsc_string", "unlabelled", "reserved_dsc"])
def test_checklist_validator_rejects_bad_definitions(invalid):
    raw = deepcopy(_read(FOLDER / "checklists.yaml"))
    category = next(iter(raw["checklists"]))
    entry = raw["checklists"][category]
    if invalid == "category_missing":
        del raw["checklists"][category]
    elif invalid == "category_extra":
        raw["checklists"]["NOT_A_ROUTE"] = deepcopy(entry)
    elif invalid == "duplicate":
        entry["items"].append(deepcopy(entry["items"][0]))
    elif invalid == "bad_key":
        entry["items"][0]["item_key"] = "unstructured text"
    elif invalid == "mandatory_string":
        entry["items"][0]["mandatory"] = "yes"
    elif invalid == "dsc_string":
        entry["dsc_required"] = "yes"
    elif invalid == "unlabelled":
        entry["status"] = "OFFICIAL"
    else:
        entry["items"][0]["item_key"] = "DSC"
    with pytest.raises(ValidationFailed):
        validate_checklists(raw, set(_read(FOLDER / "routes.yaml")["routes"]))


def test_atomic_create_submit_success_and_guard_rollback(api):
    body = {"institution_id": str(SUNRISE), "category": "NEW_INSTITUTION", "academic_year": "2027-28",
            "submit": True, "dsc_present": True}
    before = count_events()
    failed = api.post("/api/applications", headers=AUTH, json=body)
    assert failed.status_code == 422 and count_events() == before
    with new_session() as session:
        assert session.scalar(select(func.count()).select_from(Application)) == 0
        assert session.scalar(select(func.count()).select_from(ApplicationItem)) == 0
    body["items"] = [{"item_key": "DEMO_CORE_REFERENCE", "document_ref": str(DOCUMENT)}]
    response = api.post("/api/applications", headers=AUTH, json=body)
    assert response.status_code == 201 and response.json()["status"] == "IN_PROCESS", response.text
    key = UUID(response.json()["id"])
    with new_session() as session:
        events = session.scalars(select(DomainEvent).order_by(DomainEvent.seq)).all()
        assert [e.event_type for e in events] == ["wf.application_created", "wf.application_item_updated",
                                                "wf.application_submitted", "dl.deadline_opened"]
        submitted = events[2]
        assert submitted.event_version == 2 and submitted.payload["dsc_present"] is True
        assert submitted.payload["provided_item_keys"] == ["DEMO_CORE_REFERENCE"]
        assert session.get(Application, key).dsc_present is True
        assert session.scalar(select(func.count()).select_from(StageVisit)) == 1
    assert api.get("/api/ledger/verify", headers=headers("AUDITOR")).json()["ok"]


def test_atomic_create_submit_rolls_back_on_deadline_failure(api, monkeypatch):
    def fail(*args, **kwargs):
        raise Conflict("DEMO_TIMER_FAILURE")
    monkeypatch.setattr(port(DeadlinePort), "open", fail)
    response = api.post("/api/applications", headers=AUTH, json={"institution_id": str(SUNRISE), "category": "NEW_INSTITUTION",
        "academic_year": "2027-28", "submit": True, "dsc_present": True,
        "items": [{"item_key": "DEMO_CORE_REFERENCE", "document_ref": str(DOCUMENT)}]})
    assert response.status_code == 409
    with new_session() as session:
        assert session.scalar(select(func.count()).select_from(Application)) == 0
        assert session.scalar(select(func.count()).select_from(ApplicationItem)) == 0
        assert session.scalar(select(func.count()).select_from(StageVisit)) == 0
    assert count_events() == 0


def test_items_scope_validation_noop_and_missing_transition(api):
    key = draft(api)
    foreign = headers("INSTITUTION", NORTHFIELD)
    payload = {"items": [{"item_key": "DEMO_CORE_REFERENCE", "document_ref": str(DOCUMENT)}]}
    assert api.post(f"/api/applications/{key}/items", headers=foreign, json=payload).status_code == 403
    provide(api, key)
    before = count_events()
    provide(api, key)
    assert count_events() == before
    assert api.post(f"/api/applications/{key}/items", headers=AUTH, json={"items": [payload["items"][0]] * 2}).status_code == 422
    assert api.post(f"/api/applications/{key}/items", headers=AUTH,
                    json={"items": [{"item_key": "UNKNOWN", "document_ref": str(DOCUMENT)}]}).status_code == 422
    removed = api.post(f"/api/applications/{key}/items", headers=AUTH,
                       json={"items": [{"item_key": "DEMO_CORE_REFERENCE", "state": "MISSING"}]})
    assert removed.status_code == 200 and count_events() == before + 1
    assert api.post(f"/api/applications/{key}/submit", headers=AUTH, json={"dsc_present": True}).status_code == 422
    provide(api, key)
    assert api.post(f"/api/applications/{key}/submit", headers=AUTH, json={"dsc_present": True}).status_code == 200
    assert api.post(f"/api/applications/{key}/items", headers=AUTH, json=payload).status_code == 409


def test_workflow_submit_cannot_bypass_real_items_or_dsc(api, monkeypatch):
    key = draft(api)
    # Deliberately permissive upstream facts must not override stored intake facts.
    monkeypatch.setattr(guards, "_fact_loader", lambda *args: GuardFacts(checklist_complete=True, dsc_required=False, dsc_present=True))
    endpoint = f"/api/cases/{key}/actions"
    body = {"action": "submit", "expected_version": 1, "payload": {"dsc_present": True}}
    missing = api.post(endpoint, headers=AUTH, json=body)
    assert missing.status_code == 422 and missing.json()["missing_item_keys"] == ["DEMO_CORE_REFERENCE"]
    provide(api, key)
    body["payload"]["dsc_present"] = False
    missing = api.post(endpoint, headers=AUTH, json=body)
    assert missing.status_code == 422 and missing.json()["missing_item_keys"] == ["DSC"]
    body["payload"]["dsc_present"] = True
    accepted = api.post(endpoint, headers=AUTH, json=body)
    assert accepted.status_code == 200, accepted.text
    with new_session() as session:
        assert session.get(Application, UUID(key)).dsc_present is True
        event = session.scalar(select(DomainEvent).where(DomainEvent.event_type == "wf.application_submitted"))
        assert event.event_version == 2


def test_checklist_source_changes_keep_cached_revision_immutable(api, tmp_path):
    import shutil
    copied = tmp_path / "rulesets"
    shutil.copytree(ROOT / "rulesets", copied)
    path = copied / "aph-2024-27/r1/checklists.yaml"
    path.write_text(path.read_text() + "\n# DEMO source change\n")
    registry = RulesetRegistry(copied, "aph-2024-27@r1", demo_mode=True)
    with new_session() as session:
        before = session.scalar(select(Ruleset.checksum).where(Ruleset.key == "aph-2024-27@r1"))
    with pytest.raises(Conflict, match="different source checksum"):
        with new_session() as session, session.begin():
            sync_rulesets(session, registry)
    with new_session() as session:
        assert session.scalar(select(Ruleset.checksum).where(Ruleset.key == "aph-2024-27@r1")) == before


@pytest.mark.parametrize("kind", ["missing_file", "missing_guard", "missing_citation"])
def test_registry_rejects_incomplete_intake_definitions(tmp_path, kind):
    import shutil
    copied = tmp_path / "rulesets"
    destination = copied / "aph-2024-27/r1"
    shutil.copytree(FOLDER, destination)
    if kind == "missing_file":
        (destination / "checklists.yaml").unlink()
    else:
        path = destination / "routes.yaml"
        source = path.read_text()
        if kind == "missing_guard":
            source = source.replace("    - dsc_required\n", "", 1)
        else:
            source = "\n".join(line for line in source.splitlines() if "clause_citation:" not in line) + "\n"
        path.write_text(source)
    provide_port(DeadlineRuleParserPort, FakeDeadlineRuleParser())
    with pytest.raises(ValidationFailed):
        RulesetRegistry(copied, "aph-2024-27@r1", demo_mode=True).get("aph-2024-27@r1")


def test_input_types_and_both_event_schema_versions():
    for value in ("true", 1, [], {}):
        with pytest.raises(ValidationError):
            SubmissionIn(dsc_present=value)
    for row in ({"item_key": "DEMO_CORE_REFERENCE"},
                {"item_key": "DEMO_CORE_REFERENCE", "document_ref": "document contents"},
                {"item_key": "DEMO_CORE_REFERENCE", "state": "MISSING", "document_ref": str(DOCUMENT)}):
        with pytest.raises(ValidationError):
            ItemIn.model_validate(row)
    payload = {"application_id": str(DOCUMENT), "institution_id": str(SUNRISE), "category": "NEW_INSTITUTION",
               "ruleset_rev": "aph-2024-27@r1", "first_stage": "SCRUTINY", "route": ["SCRUTINY", "EVC", "SHC", "EC", "COUNCIL"]}
    schemas = ROOT / "contracts/events/wf"
    v1 = Draft202012Validator(json.loads((schemas / "application_submitted.v1.json").read_text()))
    v2 = Draft202012Validator(json.loads((schemas / "application_submitted.v2.json").read_text()))
    assert v1.is_valid(payload) and not v2.is_valid(payload)
    assert v2.is_valid({**payload, "dsc_present": True, "provided_item_keys": ["DEMO_CORE_REFERENCE"]})
