"""Guard facts in the running app: no injected loader, only persisted records and ports (fictional DEMO data)."""
from datetime import date, timedelta
from uuid import UUID, NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, update

from app.platform.db import new_session
from app.platform.registry import port
from app.workflow import facts, guards
from app.workflow.models import Ruleset
from conftest import SUNRISE, headers
from contracts.ports import ClockPort, EvcPort

INST = headers("INSTITUTION", SUNRISE)
SCRUTINY_USER = "00000000-0000-4000-9000-0000000000a1"
BUREAU_USER = "00000000-0000-4000-9000-0000000000b1"
SCRUTINY = headers("SCRUTINY_COMMITTEE", user=SCRUTINY_USER)
BUREAU = headers("BUREAU_OFFICER", user=BUREAU_USER)
OTHER_BUREAU = headers("BUREAU_OFFICER", user="00000000-0000-4000-9000-0000000000b2")
REF = "00000000-0000-4000-8000-000000000099"


@pytest.fixture
def api(client, monkeypatch):
    monkeypatch.setenv("WF_ENABLE_LETTER_ISSUANCE", "true")
    with client:
        # The point of these tests: the trusted wiring loader is the only source of guard facts.
        assert guards._fact_loader is None and guards._default_fact_loader is facts.load
        yield client
    # Experts and EVC rows are not part of the per-test cleanup set.
    from sqlalchemy import text
    with new_session() as session, session.begin():
        session.execute(text("TRUNCATE evc.assignment_expert, evc.assignment, evc.availability, evc.coi, "
                             "evc.slot, evc.schedule_run, evc.evc_request, evc.expert"))


def create(api):
    result = api.post("/api/applications", headers=INST, json={"institution_id": str(SUNRISE),
        "category": "NEW_PROGRAMME", "academic_year": "2027-28", "submit": True, "dsc_present": True,
        "items": [{"item_key": "DEMO_CORE_REFERENCE", "state": "PROVIDED", "document_ref": REF}]})
    assert result.status_code == 201, result.text
    return result.json()["id"]


def act(api, case_id, action, version, actor, payload=None, **extra):
    return api.post(f"/api/cases/{case_id}/actions", headers=actor,
                    json={"action": action, "expected_version": version, "payload": payload or {}, **extra})


def ok(response):
    assert response.status_code in {200, 201}, response.text
    return response.json()


def refused(response, code):
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == code
    return response


def version(api, case_id):
    return ok(api.get(f"/api/cases/{case_id}", headers=BUREAU))["version"]


def committee(api, case_id, kind, actor, user):
    return ok(api.post(f"/api/cases/{case_id}/committees", headers=actor,
                       json={"type": kind, "members": [{"user_ref": user, "role": "CHAIR"}]}))["id"]


def report(api, committee_id, actor, content):
    return ok(api.post(f"/api/committees/{committee_id}/reports", headers=actor, json={"content": content}))["id"]


def today():
    return port(ClockPort).now().astimezone(ZoneInfo("Asia/Kolkata")).date()


def letter(**overrides):
    value = {"type": "LOA", "academic_year": "2027-28", "issue_date": today().isoformat(),
             "issue_date_source": "PORTAL_EVENT", "lists_deficiencies": False, "f_no": "F.No. DEMO-RUNTIME/LOA/2027-28"}
    return {**value, **overrides}


def schedule(api, case_id):
    start = today()
    for index in range(3):
        expert = ok(api.post("/api/evc/experts", headers=BUREAU, json={
            "user_ref": str(uuid5(NAMESPACE_URL, f"DEMO:runtime-panel:{index}")), "region": "SOUTHERN",
            "expertise_tags": ["DEMO"]}))["id"]
        items = [{"date": (start + timedelta(days=d)).isoformat(), "slot_part": part, "available": True}
                 for d in range(8) for part in ("AM", "PM")]
        ok(api.post(f"/api/evc/experts/{expert}/availability", headers=BUREAU, json={"items": items}))
    run = ok(api.post("/api/evc/schedule:propose", headers=BUREAU, json={"algorithm": "EDF"}))
    assert len(run["proposals"]) == 1, run
    assert ok(api.post("/api/evc/schedule:publish", headers=BUREAU, json={"run_id": run["run_id"]}))["published_count"] == 1
    with new_session() as session:
        assert port(EvcPort).status(session, UUID(case_id)) == "PUBLISHED"


def through_rescrutiny(api, case_id):
    """Scrutiny with one deficiency round, compliance and re-scrutiny; acceptance advances to EVC."""
    refused(act(api, case_id, "scrutinise", 1, SCRUTINY), "ASSIGNMENT_REQUIRED")
    scrutiny = committee(api, case_id, "SCRUTINY", SCRUTINY, SCRUTINY_USER)
    ok(act(api, case_id, "record_deficiency", 1, SCRUTINY, {"item_keys": ["DEMO_CORE_REFERENCE"]},
           reason_code="DEMO_MISSING_EVIDENCE"))
    rounds = ok(api.get(f"/api/cases/{case_id}/deficiencies", headers=INST))
    items = rounds["rounds"][-1]["items"]
    ok(act(api, case_id, "submit_compliance", rounds["version"], INST,
           {"responses": [{"item_id": item["id"], "response_ref": REF} for item in items]}))
    started = ok(act(api, case_id, "start_rescrutiny", version(api, case_id), SCRUTINY))
    assert started["stage"] == "RESCRUTINY"
    current = ok(api.get(f"/api/cases/{case_id}/deficiencies", headers=INST))
    ok(api.post(f"/api/cases/{case_id}/deficiencies/{current['rounds'][-1]['id']}/review", headers=SCRUTINY,
                json={"expected_version": current["version"], "decisions": [{"item_id": item["id"], "state": "ACCEPTED",
                      "reason_code": "DEMO_RESPONSE_ACCEPTED"} for item in current["rounds"][-1]["items"]]}))
    case = ok(api.get(f"/api/cases/{case_id}", headers=BUREAU))
    assert case["stage"] == "EVC", case
    return scrutiny


def deadlines(api, case_id):
    return {row["rule_id"]: row["status"] for row in
            ok(api.get("/api/deadlines", params={"subject_id": case_id}, headers=headers("AUDITOR")))}


@pytest.mark.parametrize("shc", [False, True], ids=["evc-last", "with-shc"])
def test_new_programme_end_to_end_on_trusted_facts(api, shc):
    case_id = create(api)
    through_rescrutiny(api, case_id)
    assert deadlines(api, case_id)["INSTITUTION_RESPONSE"] == "MET"

    # EVC: membership of an EVC workspace, then a published schedule, are both required.
    refused(act(api, case_id, "complete_evc", version(api, case_id), BUREAU), "ASSIGNMENT_REQUIRED")
    evc = committee(api, case_id, "EVC", BUREAU, BUREAU_USER)
    if shc:
        shc_committee = committee(api, case_id, "SHC", BUREAU, BUREAU_USER)
    refused(act(api, case_id, "complete_evc", version(api, case_id), BUREAU), "EVC_SCHEDULE_NOT_PUBLISHED")
    schedule(api, case_id)
    completed = ok(act(api, case_id, "complete_evc", version(api, case_id), BUREAU))
    assert completed["stage"] == ("SHC" if shc else "EVC")
    with new_session() as session:
        assert port(EvcPort).status(session, UUID(case_id)) == "DONE"

    # Decision: only the head report of the committee staffing the current stage can be cited.
    deciding = shc_committee if shc else evc
    first = report(api, deciding, BUREAU, "Fictional DEMO committee report, first version.")
    head = report(api, deciding, BUREAU, "Fictional DEMO committee report, revised version.")
    current = version(api, case_id)
    refused(act(api, case_id, "issue_loa", current, BUREAU, {"decision_ref": first, "letter": letter()}),
            "DECISION_NOT_AUTHORISED")
    refused(act(api, case_id, "issue_loa", current, BUREAU, {"decision_ref": head, "letter": letter(academic_year="2026-27")}),
            "LETTER_DATA_NOT_CONFIRMED")
    backdated = (today() - timedelta(days=3)).isoformat()
    refused(act(api, case_id, "issue_loa", current, BUREAU, {"decision_ref": head, "letter": letter(issue_date=backdated)}),
            "LETTER_DATA_NOT_CONFIRMED")
    refused(act(api, case_id, "issue_eoa", current, BUREAU, {"decision_ref": head, "letter": letter()}),
            "LETTER_DECISION_MISMATCH")
    approved = ok(act(api, case_id, "issue_loa", current, BUREAU, {"decision_ref": head, "letter": letter()}))
    assert approved["status"] == "APPROVED" and approved["stage"] is None
    assert [d["rule_id"] for d in approved["closed_deadlines"]] == ["AICTE_PROCESSING"]  # response clock was not live
    letters = ok(api.get("/api/compliance/letters", params={"application_id": case_id}, headers=BUREAU))
    assert [(row["letter_type"], row["issue_date"]) for row in letters] == [("LOA", today().isoformat())]
    clocks = deadlines(api, case_id)
    assert clocks["AICTE_PROCESSING"] == "MET" and clocks["EVC_PROCESSING"] == "MET"
    assert ok(api.get("/api/ledger/verify", headers=headers("AUDITOR")))["ok"]


def test_live_clocks_are_replayed_from_the_workflow_history(api):
    case_id = create(api)
    committee(api, case_id, "SCRUTINY", SCRUTINY, SCRUTINY_USER)
    ok(act(api, case_id, "record_deficiency", 1, SCRUTINY, {"item_keys": ["DEMO_CORE_REFERENCE"]},
           reason_code="DEMO_MISSING_EVIDENCE"))
    with new_session() as session:
        from app.workflow.case_service import projection, state_for
        row = state_for(session, projection(session, UUID(case_id)))
        assert facts.live_clock_rules(session, row) == {"AICTE_PROCESSING", "INSTITUTION_RESPONSE"}
    # A rejection while the response window is open closes both live clocks (if_live) and nothing else.
    rejected = ok(act(api, case_id, "reject", 2, BUREAU, reason_code="DEMO_REASON"))
    assert sorted((d["rule_id"], d["outcome"]) for d in rejected["closed_deadlines"]) == [
        ("AICTE_PROCESSING", "MET"), ("INSTITUTION_RESPONSE", "WAIVED")]


def test_revert_policy_is_pinned_and_refuses_when_missing(api):
    case_id = create(api)
    committee(api, case_id, "SCRUTINY", SCRUTINY, SCRUTINY_USER)
    ok(act(api, case_id, "record_deficiency", 1, SCRUTINY, {"item_keys": ["DEMO_CORE_REFERENCE"]},
           reason_code="DEMO_MISSING_EVIDENCE"))
    with new_session() as session, session.begin():
        row = session.scalar(select(Ruleset).where(Ruleset.key == "aph-2024-27@r1"))
        original = dict(row.source_metadata)
        assert original["guard_facts"] == {"revert_second_approval_required": False,
            "source_status": "DEMO_ASSUMPTION", "assumption_code": "GUARD_FACT_POLICY_UNCONFIRMED"}
        stripped = {key: value for key, value in original.items() if key != "guard_facts"}
        required = {**original, "guard_facts": {**original["guard_facts"], "revert_second_approval_required": True}}
        session.execute(update(Ruleset).where(Ruleset.id == row.id).values(source_metadata=stripped))
    try:
        body = dict(payload={"target_stage": "SCRUTINY"}, reason_code="DEMO_REASON")
        refused(act(api, case_id, "revert", 2, BUREAU, **body), "APPROVAL_POLICY_UNAVAILABLE")
        with new_session() as session, session.begin():
            session.execute(update(Ruleset).where(Ruleset.key == "aph-2024-27@r1").values(source_metadata=required))
        # No approver directory exists, so a required second approval cannot be satisfied.
        refused(act(api, case_id, "revert", 2, BUREAU, **body), "APPROVAL_CONTEXT_UNAVAILABLE")
    finally:
        with new_session() as session, session.begin():
            session.execute(update(Ruleset).where(Ruleset.key == "aph-2024-27@r1").values(source_metadata=original))
    reverted = ok(act(api, case_id, "revert", 2, BUREAU, payload={"target_stage": "SCRUTINY"}, reason_code="DEMO_REASON"))
    assert reverted["stage"] == "SCRUTINY"


def test_assignment_is_per_stage_and_per_member(api):
    case_id = create(api)
    # A committee of another stage, or another officer's committee, does not assign this actor.
    committee(api, case_id, "EVC", SCRUTINY, SCRUTINY_USER)
    committee(api, case_id, "SCRUTINY", OTHER_BUREAU, "00000000-0000-4000-9000-0000000000b2")
    refused(act(api, case_id, "scrutinise", 1, SCRUTINY), "ASSIGNMENT_REQUIRED")
    actions = ok(api.get(f"/api/cases/{case_id}", headers=SCRUTINY))["available_actions"]
    assert next(a for a in actions if a["action"] == "advance")["reason_code"] == "ASSIGNMENT_REQUIRED"
    committee(api, case_id, "SCRUTINY", SCRUTINY, SCRUTINY_USER)
    advanced = ok(act(api, case_id, "scrutinise", 1, SCRUTINY))
    assert advanced["stage"] == "EVC"
