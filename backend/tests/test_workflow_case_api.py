"""Real HTTP/database/deadline/ledger integration; explicit guard/policy fixtures."""
import json
from pathlib import Path
from uuid import UUID, uuid5, NAMESPACE_URL

import pytest

from app.platform.auth import Authz
from app.platform.policy import POLICY
from app.platform.db import new_session
from app.platform.registry import port
from app.workflow import guards
from app.workflow.commands import GuardFacts
from app.workflow.models import CaseState
from app.workflow.registry import _read
from conftest import SUNRISE, NORTHFIELD, headers
from backend.tests.intake_test_helpers import provide_fixture_items
from contracts.enums import Role
from contracts.errors import Forbidden
from contracts.ports import AuthzPort, LedgerPort
from contracts.types import Principal, ResourceRef

ITEM = uuid5(NAMESPACE_URL, "case-api:fictional-item")
RESPONSE = uuid5(NAMESPACE_URL, "case-api:fictional-response")
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def api(client, monkeypatch):
    with client:
        assert isinstance(port(AuthzPort), Authz)
        facts = GuardFacts(open_item_count=0, checklist_complete=True, has_assignment=True,
                           reason_codes=frozenset({"DEMO_MISSING_EVIDENCE"}), item_refs=frozenset({ITEM}),
                           response_refs=frozenset({RESPONSE}), applicability={"SHC": False},
                           live_clock_rules=frozenset({"AICTE_PROCESSING"}), second_approval_required=False)
        monkeypatch.setattr(guards, "_fact_loader", lambda uow, case, cmd: facts)
        yield client


def create(api, institution=SUNRISE):
    response = api.post("/api/applications", headers=headers("INSTITUTION", institution), json={
        "institution_id": str(institution), "category": "NEW_INSTITUTION", "academic_year": "2027-28"})
    assert response.status_code == 201, response.text
    provide_fixture_items(response.json()["id"])
    return response.json()["id"]


def act(api, case_id, action, version, role="INSTITUTION", institution=SUNRISE, **extra):
    request_headers = headers(role, institution if role == "INSTITUTION" else None)
    request_headers["Idempotency-Key"] = f"DEMO-{case_id}-{version}-{action}"
    payload = {"dsc_present": True} if action == "submit" else {}
    return api.post(f"/api/cases/{case_id}/actions", headers=request_headers,
                    json={"action": action, "expected_version": version, "payload": payload, **extra})


def test_valid_http_sequence_real_deadlines_ledger_and_timeline(api):
    case_id = create(api)
    draft = api.get(f"/api/cases/{case_id}", headers=headers("INSTITUTION", SUNRISE))
    assert draft.status_code == 200 and draft.json()["ruleset_key"] is None
    with new_session() as session:
        assert session.get(CaseState, UUID(case_id)) is None  # GET is read-only
    submitted = act(api, case_id, "submit", 1)
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["stage"] == "SCRUTINY" and submitted.json()["version"] == 2
    assert [x["rule_id"] for x in submitted.json()["opened_deadlines"]] == ["AICTE_PROCESSING"]
    deficiency = act(api, case_id, "record_deficiency", 2, "SCRUTINY_COMMITTEE",
                     reason_code="DEMO_MISSING_EVIDENCE", note="Fictional DEMO private note",
                     payload={"item_keys": ["DEMO_CORE_REFERENCE"]})
    assert deficiency.status_code == 200, deficiency.text
    assert deficiency.json()["stage"] == "DEFICIENT"
    assert [x["rule_id"] for x in deficiency.json()["opened_deadlines"]] == ["INSTITUTION_RESPONSE"]
    rounds = api.get(f"/api/cases/{case_id}/deficiencies", headers=headers("INSTITUTION", SUNRISE)).json()
    item = rounds["rounds"][0]["items"][0]
    compliance = act(api, case_id, "submit_compliance", 3,
        payload={"responses": [{"item_id": item["id"], "response_ref": str(RESPONSE)}]})
    assert compliance.status_code == 200, compliance.text
    assert compliance.json()["stage"] == "RESCRUTINY"
    assert compliance.json()["closed_deadlines"] == [{"subject_id": case_id, "rule_id": "INSTITUTION_RESPONSE", "outcome": "MET"}]
    review = api.post(f"/api/cases/{case_id}/deficiencies/{rounds['rounds'][0]['id']}/review",
        headers=headers("SCRUTINY_COMMITTEE"), json={"expected_version": 4,
        "decisions": [{"item_id": item["id"], "state": "ACCEPTED", "reason_code": "DEMO_RESPONSE_ACCEPTED"}]})
    assert review.status_code == 200, review.text
    detail = api.get(f"/api/cases/{case_id}", headers=headers("INSTITUTION", SUNRISE)).json()
    assert detail["version"] == 5 and detail["ruleset_key"] == "aph-2024-27@r1"
    assert len(detail["stage_history"]) == 4
    assert sum(v["exited_at"] is None for v in detail["stage_history"]) == 1
    assert detail["assumption_status"] == "DEMO_ASSUMPTION"
    projection = api.get(f"/api/applications/{case_id}", headers=headers("INSTITUTION", SUNRISE)).json()
    assert projection["current_stage"] == "EVC" and projection["status"] == "IN_PROCESS"
    timeline = api.get(f"/api/cases/{case_id}/timeline", headers=headers("INSTITUTION", SUNRISE))
    assert timeline.status_code == 200
    rows = timeline.json()
    assert [r["seq"] for r in rows] == sorted(r["seq"] for r in rows)
    wf = [r["event_type"] for r in rows if r["event_type"].startswith("wf.")]
    assert wf == ["wf.application_created", "wf.application_submitted", "wf.stage_entered",
                  "wf.transition_applied", "wf.deficiency_recorded", "wf.stage_exited", "wf.stage_entered",
                  "wf.transition_applied", "wf.deficiency_item_responded", "wf.compliance_submitted", "wf.stage_exited", "wf.stage_entered",
                  "wf.deficiency_item_decided", "wf.deficiency_closed",
                  "wf.transition_applied", "wf.stage_exited", "wf.stage_entered"]
    assert [r["event_type"] for r in rows if r["event_type"].startswith("dl.")] == ["dl.deadline_opened"] * 3
    assert [r["event_type"] for r in rows] == [
        "wf.application_created", "dl.deadline_opened", "wf.application_submitted", "wf.stage_entered",
        "dl.deadline_opened", "wf.transition_applied", "wf.deficiency_recorded", "wf.stage_exited", "wf.stage_entered",
        "wf.transition_applied", "wf.deficiency_item_responded", "wf.compliance_submitted", "wf.stage_exited", "wf.stage_entered",
        "wf.deficiency_item_decided", "wf.deficiency_closed",
        "dl.deadline_opened", "evc.request_created",
        "wf.transition_applied", "wf.stage_exited", "wf.stage_entered"]
    assert "Fictional DEMO private note" not in json.dumps(rows)
    deadlines = api.get("/api/deadlines", params={"subject_id": case_id}, headers=headers("INSTITUTION", SUNRISE)).json()
    assert {d["rule_id"]: d["status"] for d in deadlines} == {
        "AICTE_PROCESSING": "RUNNING", "INSTITUTION_RESPONSE": "MET", "EVC_PROCESSING": "RUNNING"}
    verify = api.get("/api/ledger/verify", headers=headers("AUDITOR"))
    assert verify.status_code == 200 and verify.json()["ok"]


def test_requested_scrutinise_then_deficiency_order_is_invalid_in_pinned_yaml(api):
    case_id = create(api)
    assert act(api, case_id, "submit", 1).status_code == 200
    assert act(api, case_id, "scrutinise", 2, "SCRUTINY_COMMITTEE").json()["stage"] == "EVC"
    response = act(api, case_id, "record_deficiency", 3, "SCRUTINY_COMMITTEE",
                   reason_code="DEMO_MISSING_EVIDENCE", payload={"item_keys": ["DEMO_CORE_REFERENCE"]})
    assert response.status_code == 422 and response.json()["detail"] == "INVALID_TRANSITION"
    assert api.get(f"/api/cases/{case_id}", headers=headers("INSTITUTION", SUNRISE)).json()["version"] == 3


@pytest.mark.parametrize("method,suffix", [("get", ""), ("post", "/actions")])
def test_other_institution_cannot_read_or_act(api, method, suffix):
    case_id = create(api, NORTHFIELD)
    kwargs = {"headers": headers("INSTITUTION", SUNRISE)}
    if method == "post":
        kwargs["json"] = {"action": "submit", "expected_version": 1, "payload": {}}
    response = getattr(api, method)(f"/api/cases/{case_id}{suffix}", **kwargs)
    assert response.status_code == 403
    with new_session() as session:
        assert session.get(CaseState, UUID(case_id)) is None


def test_ro_region_scope_on_detail_action_and_collection(api):
    case_id = create(api)
    own = api.get(f"/api/cases/{case_id}", headers=headers("INSTITUTION", SUNRISE)).json()["region"]
    foreign = headers("RO_OFFICER") | {"X-Demo-Region": "DEMO-OTHER-REGION"}
    assert api.get(f"/api/cases/{case_id}", headers=foreign).status_code == 403
    assert api.get(f"/api/cases/{case_id}/timeline", headers=foreign).status_code == 403
    assert api.post(f"/api/cases/{case_id}/actions", headers=foreign,
                    json={"action": "submit", "expected_version": 1}).status_code == 403
    assert api.get("/api/cases", headers=foreign, params={"region": own}).status_code == 403
    assert api.get("/api/cases", headers=foreign).json()["total"] == 0
    matching = headers("RO_OFFICER") | {"X-Demo-Region": own}
    assert api.get(f"/api/cases/{case_id}", headers=matching).status_code == 200
    # a regional officer without a region is refused at sign-in, before any case query
    assert api.get("/api/cases", headers=headers("RO_OFFICER")).status_code == 401


def test_collection_scopes_filters_and_pages_before_counting(api):
    ids = [create(api), create(api), create(api, NORTHFIELD)]
    assert act(api, ids[0], "submit", 1).status_code == 200
    auth = headers("INSTITUTION", SUNRISE)
    first = api.get("/api/cases", headers=auth, params={"limit": 1}).json()
    second = api.get("/api/cases", headers=auth, params={"limit": 1, "offset": 1}).json()
    # Seed data also contains own cases; use the complete scoped page as authority.
    full = api.get("/api/cases", headers=auth, params={"limit": 100}).json()
    ordered = [x["case_id"] for x in full["items"]]
    assert ordered == sorted(ordered) and ids[2] not in ordered
    assert first["items"] == full["items"][:1] and second["items"] == full["items"][1:2]
    assert first["total"] == second["total"] == full["total"]
    filtered = api.get("/api/cases", headers=auth, params={"stage": "SCRUTINY", "status": "IN_PROCESS"}).json()
    assert ids[0] in [x["case_id"] for x in filtered["items"]]
    assert all(x["stage"] == "SCRUTINY" and x["status"] == "IN_PROCESS" for x in filtered["items"])
    assert api.get("/api/cases", headers=auth, params={"limit": 0}).status_code == 422
    assert api.get("/api/cases", headers=auth, params={"stage": "MADE_UP"}).status_code == 422


def test_http_errors_replay_and_payload_actor_are_safe(api):
    case_id = create(api)
    assert act(api, case_id, "submit", 1).status_code == 200
    before = api.get(f"/api/cases/{case_id}/timeline", headers=headers("INSTITUTION", SUNRISE)).json()
    replay = act(api, case_id, "submit", 1)
    assert replay.status_code == 409 and replay.json()["detail"] == "VERSION_CONFLICT"
    invalid = act(api, case_id, "not_an_action", 2)
    assert invalid.status_code in {403, 422}  # unknown policy fails closed before transition evaluation
    bad = api.post(f"/api/cases/{case_id}/actions", headers=headers("INSTITUTION", SUNRISE), json={
        "action": "submit_compliance", "expected_version": 2, "actor": {"role": "BUREAU_HEAD"}})
    assert bad.status_code == 422
    assert api.get(f"/api/cases/{case_id}/timeline", headers=headers("INSTITUTION", SUNRISE)).json() == before
    assert api.get(f"/api/cases/{uuid5(NAMESPACE_URL, 'missing-case')}", headers=headers("INSTITUTION", SUNRISE)).status_code == 404
    assert api.get(f"/api/cases/{case_id}").status_code == 401


def test_legacy_submit_is_adopted_without_duplicate_clocks_or_visits(api):
    case_id = create(api)
    legacy = api.post(f"/api/applications/{case_id}/submit", headers=headers("INSTITUTION", SUNRISE), json={"dsc_present": True})
    assert legacy.status_code == 200
    read = api.get(f"/api/cases/{case_id}", headers=headers("INSTITUTION", SUNRISE)).json()
    assert read["version"] == 1 and read["stage"] == "SCRUTINY" and len(read["stage_history"]) == 1
    advanced = act(api, case_id, "scrutinise", 1, "SCRUTINY_COMMITTEE")
    assert advanced.status_code == 200 and advanced.json()["version"] == 2, advanced.text
    events = api.get(f"/api/cases/{case_id}/timeline", headers=headers("INSTITUTION", SUNRISE)).json()
    assert sum(e["event_type"] == "wf.application_submitted" for e in events) == 1
    opened = [e for e in events if e["event_type"] == "dl.deadline_opened"]
    assert [e["payload"]["rule_id"] for e in opened] == ["AICTE_PROCESSING", "EVC_PROCESSING"]


def test_unknown_guard_facts_reject_without_leaving_partial_adoption(api, monkeypatch):
    case_id = create(api)
    assert act(api, case_id, "submit", 1).status_code == 200
    before = api.get(f"/api/cases/{case_id}/timeline", headers=headers("INSTITUTION", SUNRISE)).json()
    monkeypatch.setattr(guards, "_fact_loader", None)
    response = act(api, case_id, "scrutinise", 2, "SCRUTINY_COMMITTEE")
    assert response.status_code == 422 and response.json()["detail"] == "GUARD_CONTEXT_UNAVAILABLE"
    assert api.get(f"/api/cases/{case_id}/timeline", headers=headers("INSTITUTION", SUNRISE)).json() == before


def test_openapi_header_and_api_shapes(api):
    document = api.get("/openapi.json").json()
    operation = document["paths"]["/api/cases/{application_id}/actions"]["post"]
    header = next(p for p in operation["parameters"] if p["name"] == "Idempotency-Key")
    assert header["in"] == "header" and not header["required"]
    assert "not enforced" in header["description"]
    assert {"403", "404", "409", "422"} <= operation["responses"].keys()
    assert document == json.loads((ROOT / "contracts/openapi.json").read_text(encoding="utf-8"))


def test_case_action_policy_matches_current_yaml_roles_and_denies_unknown():
    templates = _read(ROOT / "rulesets/aph-2024-27/r1/routes.yaml")["templates"]
    expected = {}
    for template in templates.values():
        expected.setdefault(f"case.{template['action']}", set()).update(Role(role) for role in template["allowed_roles"])
    assert {key: POLICY[key] for key in expected} == expected
    principal = Principal(ITEM, Role.INSTITUTION, institution_id=SUNRISE)
    with pytest.raises(Forbidden):
        Authz().check(principal, "case.not_an_action", ResourceRef("application", RESPONSE, SUNRISE, "Southern"))


def test_institution_cannot_scrutinise_own_case(api):
    case_id = create(api)
    assert act(api, case_id, "submit", 1).status_code == 200
    response = act(api, case_id, "scrutinise", 2)
    assert response.status_code == 403
    assert api.get(f"/api/cases/{case_id}", headers=headers("INSTITUTION", SUNRISE)).json()["version"] == 2


def test_action_failure_rolls_back_bootstrap_projection_deadline_and_ledger(api, monkeypatch):
    case_id = create(api)
    original = port(LedgerPort).append

    def failed_append(uow, event):
        if event.event_type == "wf.stage_entered":
            raise RuntimeError("DEMO ledger failure")
        return original(uow, event)

    monkeypatch.setattr(port(LedgerPort), "append", failed_append)
    with pytest.raises(RuntimeError, match="DEMO ledger failure"):
        act(api, case_id, "submit", 1)
    with new_session() as session:
        assert session.get(CaseState, UUID(case_id)) is None
    detail = api.get(f"/api/cases/{case_id}", headers=headers("INSTITUTION", SUNRISE)).json()
    assert detail["status"] == "DRAFT" and detail["ruleset_key"] is None and detail["stage_history"] == []
    events = api.get(f"/api/cases/{case_id}/timeline", headers=headers("INSTITUTION", SUNRISE)).json()
    assert [e["event_type"] for e in events] == ["wf.application_created"]
    assert api.get("/api/deadlines", params={"subject_id": case_id}, headers=headers("INSTITUTION", SUNRISE)).json() == []
    assert api.get("/api/ledger/verify", headers=headers("AUDITOR")).json()["ok"]
