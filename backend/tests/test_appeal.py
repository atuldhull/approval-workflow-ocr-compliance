"""Appeal against an LoD (APH cl. 1.11 / 2.24), SAC recommendation, Council decision and the Letter of Rejection,
on the running app with trusted facts only (fictional DEMO data)."""
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, text

from app.deadlines.worker import TimerWorker
from app.platform.db import new_session
from app.platform.registry import port
from app.workflow.models import Appeal
from conftest import NORTHFIELD, SUNRISE, headers
from contracts.ports import ClockPort

INST = headers("INSTITUTION", SUNRISE)
OTHER_INST = headers("INSTITUTION", NORTHFIELD)
SCRUTINY_USER = "00000000-0000-4000-9000-0000000000a1"
SAC_USER = "00000000-0000-4000-9000-0000000000a2"
BUREAU_USER = "00000000-0000-4000-9000-0000000000b1"
SCRUTINY = headers("SCRUTINY_COMMITTEE", user=SCRUTINY_USER)
SAC = headers("SCRUTINY_COMMITTEE", user=SAC_USER)
BUREAU = headers("BUREAU_OFFICER", user=BUREAU_USER)
HEAD = headers("BUREAU_HEAD", user="00000000-0000-4000-9000-0000000000c1")
AUDITOR = headers("AUDITOR")
REF = "b870b346-498b-55b1-945e-c0e24d268980"  # DEMO fixture document reference (UUID5), accepted only in DEMO_MODE
GROUNDS = "Fictional DEMO grounds: the deficiency was met before the LoD."
SPEAKING_ORDER = "Fictional DEMO speaking order: the deficiency in item 1 remains unmet after the hearing."


@pytest.fixture
def api(client, monkeypatch):
    monkeypatch.setenv("WF_ENABLE_LETTER_ISSUANCE", "true")
    with client:
        yield client
    with new_session() as session, session.begin():
        session.execute(text("TRUNCATE evc.assignment_expert, evc.assignment, evc.availability, evc.coi, "
                             "evc.slot, evc.schedule_run_request, evc.schedule_run, evc.evc_request, evc.expert"))


def ok(response):
    assert response.status_code in {200, 201}, response.text
    return response.json()


def refused(response, code, status=422):
    assert response.status_code == status, response.text
    if status == 422:
        assert response.json()["detail"] == code
    return response


def version(api, case_id):
    return ok(api.get(f"/api/cases/{case_id}", headers=BUREAU))["version"]


def act(api, case_id, action, actor, payload=None, **extra):
    return api.post(f"/api/cases/{case_id}/actions", headers=actor, json={
        "action": action, "expected_version": version(api, case_id), "payload": payload or {}, **extra})


def create(api, category="CHANGE_OF_NAME"):
    result = api.post("/api/applications", headers=INST, json={"institution_id": str(SUNRISE),
        "category": category, "academic_year": "2027-28", "submit": True, "dsc_present": True,
        "items": [{"item_key": "DEMO_CORE_REFERENCE", "state": "PROVIDED", "document_ref": REF}]})
    assert result.status_code == 201, result.text
    return result.json()["id"]


def committee(api, case_id, kind, actor, user):
    return ok(api.post(f"/api/cases/{case_id}/committees", headers=actor,
                       json={"type": kind, "members": [{"user_ref": user, "role": "CHAIR"}]}))["id"]


def report(api, committee_id, actor, content):
    return ok(api.post(f"/api/committees/{committee_id}/reports", headers=actor, json={"content": content}))["id"]


def letter(kind):
    today = port(ClockPort).now().astimezone(ZoneInfo("Asia/Kolkata")).date()
    return {"type": kind, "academic_year": "2027-28", "issue_date": today.isoformat(),
            "issue_date_source": "PORTAL_EVENT", "lists_deficiencies": False, "f_no": f"F.No. DEMO-APPEAL/{kind}/2027-28"}


def deadlines(api, case_id):
    return {row["rule_id"]: row["status"] for row in
            ok(api.get("/api/deadlines", params={"subject_id": case_id}, headers=AUDITOR))}


def appeal(api, case_id, actor=BUREAU):
    return ok(api.get(f"/api/cases/{case_id}/appeal", headers=actor))["appeal"]


def lod(api, case_id):
    """Scrutiny (the last stage of CHANGE_OF_NAME) decides; the bureau issues the LoD citing its report."""
    scrutiny = committee(api, case_id, "SCRUTINY", SCRUTINY, SCRUTINY_USER)
    decision = report(api, scrutiny, SCRUTINY, "Fictional DEMO scrutiny report.")
    issued = ok(act(api, case_id, "issue_lod", BUREAU, {"decision_ref": decision, "letter": letter("LOD")}))
    assert issued["status"] == "IN_PROCESS" and issued["stage"] == "SCRUTINY"
    assert [d["rule_id"] for d in issued["opened_deadlines"]] == ["APPEAL_7D"]
    return decision


def to_sac(api, case_id):
    lod(api, case_id)
    filed = ok(act(api, case_id, "file_appeal", INST, note=GROUNDS))
    assert filed["stage"] == "SAC" and filed["status"] == "IN_PROCESS"
    sac = committee(api, case_id, "SAC", SAC, SAC_USER)
    return sac, report(api, sac, SAC, "Fictional DEMO SAC report.")


def events(case_id):
    with new_session() as session:
        return [row[0] for row in session.execute(text(
            "SELECT event_type FROM plat.domain_event WHERE aggregate_id = :id ORDER BY seq"), {"id": case_id})]


def test_lod_opens_the_window_and_only_the_appeal_can_follow(api):
    case_id = create(api)
    lod(api, case_id)
    window = appeal(api, case_id, INST)
    assert window["status"] == "WINDOW_OPEN" and window["max_appeals"] == 1 and window["window"]["days_left"] == 7
    assert window["window"]["rule_id"] == "APPEAL_7D" and window["window"]["clause"] == "2.24(a)"
    assert window["source"]["status"] == "VERIFIED"
    assert deadlines(api, case_id) == {"AICTE_PROCESSING": "MET", "APPEAL_7D": "RUNNING"}
    # the LoD is not final yet: nothing else can be decided while the window is open
    refused(act(api, case_id, "issue_lod", BUREAU, {"letter": letter("LOD")}), "APPEAL_WINDOW_OPEN")
    refused(act(api, case_id, "withdraw", INST, reason_code="DEMO_REASON"), "APPEAL_WINDOW_OPEN")
    refused(act(api, case_id, "close_appeal_window", BUREAU), "APPEAL_WINDOW_STILL_OPEN")
    refused(act(api, case_id, "file_appeal", OTHER_INST), None, status=403)
    refused(act(api, case_id, "file_appeal", BUREAU), None, status=403)
    actions = {a["action"]: a for a in ok(api.get(f"/api/cases/{case_id}", headers=INST))["available_actions"]}
    assert actions["file_appeal"]["enabled"] and actions["file_appeal"]["targets"] == ["SAC"]
    filed = ok(act(api, case_id, "file_appeal", INST, note=GROUNDS))
    assert filed["closed_deadlines"] == [{"subject_id": case_id, "rule_id": "APPEAL_7D", "outcome": "MET"}]
    record = appeal(api, case_id)
    assert record["status"] == "FILED" and record["hearing_no"] == 1 and len(record["grounds_note_hash"]) == 64
    # an appeal lies once
    refused(act(api, case_id, "file_appeal", INST), "INVALID_TRANSITION")
    assert {"wf.appeal_window_opened", "wf.appeal_filed"} <= set(events(case_id))


def test_unappealed_window_lapses_when_its_clock_is_breached(api):
    case_id = create(api)
    lod(api, case_id)
    ok(api.post("/api/sim/clock", headers=BUREAU, json={"days": 8}))
    # past the due date the window is shut even before the worker marks the clock
    refused(act(api, case_id, "file_appeal", INST, note=GROUNDS), "APPEAL_WINDOW_CLOSED")
    TimerWorker().run_once()
    case = ok(api.get(f"/api/cases/{case_id}", headers=BUREAU))
    assert case["status"] == "REJECTED" and case["stage"] is None
    assert case["stage_history"][-1]["outcome"] == "CLOSE_APPEAL_WINDOW"
    record = appeal(api, case_id)
    assert record["status"] == "LAPSED" and record["closed_at"] is not None and record["window"]["days_left"] is None
    assert deadlines(api, case_id)["APPEAL_7D"] == "WAIVED"
    assert "wf.appeal_lapsed" in events(case_id)
    assert TimerWorker().run_expiry_actions() == 0  # nothing left to close
    assert ok(api.get("/api/ledger/verify", headers=AUDITOR))["ok"]


def test_sac_not_recommended_then_council_letter_of_rejection_with_speaking_order(api):
    case_id = create(api)
    refused(act(api, case_id, "file_appeal", INST), "APPEAL_WINDOW_NOT_OPEN")
    _, sac_report = to_sac(api, case_id)
    refused(act(api, case_id, "sac_not_recommend", SCRUTINY, {"decision_ref": sac_report}), "ASSIGNMENT_REQUIRED")
    refused(act(api, case_id, "issue_lor", HEAD, {"decision_ref": sac_report, "letter": letter("LOR")},
                note=SPEAKING_ORDER), "SAC_RECOMMENDATION_REQUIRED")
    ok(act(api, case_id, "sac_not_recommend", SAC, {"decision_ref": sac_report}))
    record = appeal(api, case_id)
    assert (record["status"], record["recommendation"], record["recommendation_report_ref"]) == (
        "NOT_RECOMMENDED", "NOT_RECOMMEND", sac_report)
    # the Council's decision is recorded by the bureau head, and a rejection must carry its speaking order
    refused(act(api, case_id, "issue_lor", BUREAU, {"decision_ref": sac_report, "letter": letter("LOR")},
                note=SPEAKING_ORDER), None, status=403)
    refused(act(api, case_id, "issue_lor", HEAD, {"decision_ref": sac_report, "letter": letter("LOR")}),
            "SPEAKING_ORDER_REQUIRED")
    refused(act(api, case_id, "issue_lor", HEAD, {"decision_ref": sac_report, "letter": letter("LOR")}, note="   "),
            "SPEAKING_ORDER_REQUIRED")
    rejected = ok(act(api, case_id, "issue_lor", HEAD, {"decision_ref": sac_report, "letter": letter("LOR")},
                      note=SPEAKING_ORDER))
    assert rejected["status"] == "REJECTED" and rejected["stage"] is None
    record = appeal(api, case_id)
    assert record["status"] == "DECIDED" and record["outcome"] == "LOR" and len(record["speaking_order_note_hash"]) == 64
    letters = ok(api.get("/api/compliance/letters", params={"application_id": case_id}, headers=BUREAU))
    assert sorted(row["letter_type"] for row in letters) == ["LOD", "LOR"]
    assert record["decision_letter_ref"] in {row["id"] for row in letters}
    assert {"wf.appeal_recommended", "wf.appeal_decided"} <= set(events(case_id))
    with new_session() as session:
        row = session.scalar(select(Appeal).where(Appeal.application_id == UUID(case_id)))
        assert row.speaking_order_note_ref is not None and row.grounds_note_ref is not None
    assert ok(api.get("/api/ledger/verify", headers=AUDITOR))["ok"]


def test_sac_referral_returns_to_another_hearing_and_the_council_approves(api):
    case_id = create(api)
    _, sac_report = to_sac(api, case_id)
    referred = ok(act(api, case_id, "sac_refer_scrutiny", SAC, {"decision_ref": sac_report}))
    assert referred["stage"] == "SCRUTINY"
    assert appeal(api, case_id)["status"] == "REFERRED_BACK"
    actions = {a["action"] for a in ok(api.get(f"/api/cases/{case_id}", headers=SAC))["available_actions"]}
    assert "sac_refer_evc" not in actions  # CHANGE_OF_NAME has no EVC to refer to
    # the decision belongs to another SAC hearing, not to a second LoD
    scrutiny = ok(api.get(f"/api/cases/{case_id}/committees", headers=BUREAU))[0]
    refused(act(api, case_id, "issue_lod", BUREAU, {"decision_ref": scrutiny["latest_report"]["id"],
                                                    "letter": letter("LOD")}), "APPEAL_REFERRED_BACK")
    refused(act(api, case_id, "issue_loa", BUREAU, {"decision_ref": scrutiny["latest_report"]["id"],
                                                    "letter": letter("LOA")}), "APPEAL_REFERRED_BACK")
    returned = ok(act(api, case_id, "return_to_sac", BUREAU))
    assert returned["stage"] == "SAC"
    record = appeal(api, case_id)
    assert record["status"] == "FILED" and record["hearing_no"] == 2 and record["recommendation"] is None
    second = report(api, ok(api.get(f"/api/cases/{case_id}/committees", headers=BUREAU))[-1]["id"], SAC,
                    "Fictional DEMO SAC report after the fresh scrutiny.")
    ok(act(api, case_id, "sac_recommend", SAC, {"decision_ref": second}))
    approved = ok(act(api, case_id, "issue_loa", HEAD, {"decision_ref": second, "letter": letter("LOA")}))
    assert approved["status"] == "APPROVED"
    record = appeal(api, case_id)
    assert (record["status"], record["outcome"], record["recommendation"]) == ("DECIDED", "LOA", "RECOMMEND")
    assert record["speaking_order_note_hash"] is None


def test_case_summary_is_scoped_like_the_case_and_shows_fingerprints_only(api):
    case_id = create(api)
    to_sac(api, case_id)
    summary = ok(api.get(f"/api/cases/{case_id}/summary", headers=INST))
    assert summary["case_id"] == case_id and summary["route_id"] == "CHANGE_OF_NAME" and summary["stage"] == "SAC"
    assert summary["clause_citation"]["status"] == "VERIFIED" and summary["clause_citation"]["page"] == 46
    assert summary["route_label"] and summary["academic_year"] == "2027-28" and summary["withheld"] == []
    assert [v["stage"] for v in summary["stage_visits"]] == ["SCRUTINY", "SCRUTINY", "SAC"]
    assert [v["outcome"] for v in summary["stage_visits"]] == ["ISSUE_LOD", "FILE_APPEAL", None]
    assert [c["type"] for c in summary["committees"]] == ["SCRUTINY", "SAC"]
    reports = [r for c in summary["committees"] for r in c["reports"]]
    assert reports and all(set(r) == {"id", "version_no", "created_at", "author_user_ref", "content_note_hash"}
                           for r in reports)
    assert [row["letter_type"] for row in summary["letters"]] == ["LOD"]
    assert summary["open_deadlines"] == []  # AICTE_PROCESSING closed at the LoD, APPEAL_7D met by the filing
    assert summary["appeal"]["status"] == "FILED" and summary["evc_requests"] == []
    body = api.get(f"/api/cases/{case_id}/summary", headers=AUDITOR).text
    assert GROUNDS not in body and "Fictional DEMO SAC report" not in body
    refused(api.get(f"/api/cases/{case_id}/summary", headers=OTHER_INST), None, status=403)
    regional = {**BUREAU, "X-Demo-Role": "RO_OFFICER", "X-Demo-Region": "NOT-THE-CASE-REGION"}
    refused(api.get(f"/api/cases/{case_id}/summary", headers=regional), None, status=403)
    refused(api.get(f"/api/cases/{case_id}/appeal", headers=OTHER_INST), None, status=403)
    assert api.get("/api/cases/00000000-0000-4000-8000-00000000dead/summary", headers=BUREAU).status_code == 404


def test_only_evc_route_queues_the_visit_on_submission_and_routes_use_their_own_evc_timeline(api):
    inspection = create(api, "RANDOM_INSPECTION")
    case = ok(api.get(f"/api/cases/{inspection}", headers=BUREAU))
    assert case["stage"] == "EVC" and case["clause_citation"]["clause"] == "2.3.5(a)"
    evc = ok(api.get(f"/api/applications/{inspection}/evc", headers=BUREAU))["current"]
    assert evc["status"] == "QUEUED" and evc["rule_id"] == "EVC_PROCESSING" and evc["duration_days"] == 7
    assert deadlines(api, inspection)["EVC_PROCESSING"] == "RUNNING"

    new = create(api, "NEW_INSTITUTION")
    committee(api, new, "SCRUTINY", SCRUTINY, SCRUTINY_USER)
    assert ok(act(api, new, "advance_to_evc", SCRUTINY))["stage"] == "EVC"
    evc = ok(api.get(f"/api/applications/{new}/evc", headers=BUREAU))["current"]
    assert evc["rule_id"] == "EVC_NEW_INSTITUTION" and evc["duration_days"] == 14
    assert evc["source_status"] == "DEMO_ASSUMPTION"


def test_expiry_actions_are_optional_for_the_worker(monkeypatch):
    from app.platform import registry as bindings
    monkeypatch.setattr(bindings, "_impls", {})
    assert TimerWorker(now=lambda: None).run_expiry_actions() == 0
