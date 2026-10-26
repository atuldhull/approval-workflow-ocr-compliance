"""Real API/member authorization, protected content and database report invariants."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
from threading import Barrier
from uuid import UUID, NAMESPACE_URL, uuid5

import pytest
from sqlalchemy import func, insert, select, text
from sqlalchemy.exc import DBAPIError

from app.platform import registry as bindings
from app.platform.db import get_engine, new_session
from app.platform.models import CaseNote, DomainEvent
from app.platform.registry import port, provide
from app.workflow.models import Committee, CommitteeMember, ReportVersion
from conftest import SUNRISE, NORTHFIELD, headers
from contracts.fakes import FakeClock
from contracts.ports import AuthzPort, ClockPort, LedgerPort

ALICE = UUID("00000000-0000-4000-9000-000000000001")
BOB = UUID("00000000-0000-4000-9000-000000000002")
OUTSIDER = UUID("00000000-0000-4000-9000-000000000003")
A = headers("SCRUTINY_COMMITTEE", user=str(ALICE))
B = headers("BUREAU_OFFICER", user=str(BOB))
C = headers("SCRUTINY_COMMITTEE", user=str(OUTSIDER))


@pytest.fixture
def workspace(client, monkeypatch):
    with client:
        monkeypatch.setattr(bindings, "_impls", bindings._impls.copy())
        result = client.post("/api/applications", headers=headers("INSTITUTION", SUNRISE), json={
            "institution_id": str(SUNRISE), "category": "NEW_PROGRAMME", "academic_year": "2027-28"})
        assert result.status_code == 201, result.text
        yield client, result.json()["id"]


def form(api, case_id, actor=A, members=None):
    result = api.post(f"/api/cases/{case_id}/committees", headers=actor, json={"type": "SCRUTINY",
        "members": members or [{"user_ref": str(ALICE), "role": "CHAIR"}, {"user_ref": str(BOB), "role": "SECRETARY"}]})
    assert result.status_code == 201, result.text
    return result.json()


def task(api, committee_id):
    result = api.post(f"/api/committees/{committee_id}/tasks", headers=A,
        json={"title_key": "REVIEW_RESPONSES", "assignee_user_ref": str(BOB)})
    assert result.status_code == 201, result.text
    return result.json()


def report(api, committee_id, content="Fictional DEMO report", actor=A, **extra):
    return api.post(f"/api/committees/{committee_id}/reports", headers=actor,
                    json={"content": content, **extra})


def reports(api, committee_id):
    result = api.get(f"/api/committees/{committee_id}/reports", headers=A)
    assert result.status_code == 200, result.text
    return result.json()


def test_attribution_notes_hash_diff_and_event_order(workspace):
    api, case_id = workspace
    group = form(api, case_id)
    assigned = task(api, group["id"])
    body = "Fictional DEMO observation, kept out of workflow tables"
    observation = api.post(f"/api/tasks/{assigned['id']}/observations", headers=B, json={"body": body})
    assert observation.status_code == 201, observation.text
    assert observation.json()["author_user_ref"] == str(BOB)
    assert observation.json()["body_note_hash"] == sha256(body.encode()).hexdigest()
    first = report(api, group["id"], "Fictional DEMO report v1")
    second = report(api, group["id"], "Fictional DEMO report v2", B, parent_version=first.json()["id"])
    third = report(api, group["id"], "Fictional DEMO report v2", B)
    assert first.status_code == second.status_code == third.status_code == 201
    versions = reports(api, group["id"])
    assert [v["version_no"] for v in versions] == [1, 2, 3]
    assert versions[0] == first.json()  # appending never rewrites the first version
    assert [v["author_user_ref"] for v in versions] == [str(ALICE), str(BOB), str(BOB)]
    assert versions[1]["parent_version"] == versions[0]["id"]
    assert versions[1]["diff"] == {"comparison": "HASH_ONLY", "parent_version_no": 1,
        "previous_content_hash": versions[0]["content_note_hash"], "content_changed": True, "author_changed": True}
    assert not versions[2]["diff"]["content_changed"] and not versions[2]["diff"]["author_changed"]
    detail = api.get(f"/api/committees/{group['id']}", headers=A).json()
    assert detail["report_count"] == 3 and detail["tasks"][0]["observations"] == [observation.json()]
    assert body not in str(detail) and "Fictional DEMO report" not in str(versions)
    timeline = api.get(f"/api/cases/{case_id}/timeline", headers=headers("INSTITUTION", SUNRISE)).json()
    assert [event["event_type"] for event in timeline] == ["wf.application_created", "wf.committee_formed",
        "wf.task_assigned", "wf.observation_added", "wf.report_version_added", "wf.report_version_added", "wf.report_version_added"]
    assert body not in str(timeline) and "Fictional DEMO report" not in str(timeline)
    with new_session() as session:
        note = session.get(CaseNote, UUID(observation.json()["body_note_ref"]))
        assert note.body == body
        for version in versions:
            stored = session.get(CaseNote, UUID(version["content_note_ref"]))
            assert sha256(stored.body.encode()).hexdigest() == version["content_note_hash"]
    assert api.get("/api/ledger/verify", headers=headers("AUDITOR")).json()["ok"]


@pytest.mark.parametrize("operation", ["task", "observation", "report"])
def test_nonmember_cannot_write_even_when_member_of_another_committee(workspace, operation):
    api, case_id = workspace
    group = form(api, case_id)
    assigned = task(api, group["id"])
    form(api, case_id, C, [{"user_ref": str(OUTSIDER), "role": "CHAIR"}])
    url, body = {
        "task": (f"/api/committees/{group['id']}/tasks", {"title_key": "PREPARE_REPORT", "assignee_user_ref": str(BOB)}),
        "observation": (f"/api/tasks/{assigned['id']}/observations", {"body": "Fictional forbidden observation"}),
        "report": (f"/api/committees/{group['id']}/reports", {"content": "Fictional forbidden report"}),
    }[operation]
    before = api.get(f"/api/cases/{case_id}/timeline", headers=A).json()
    result = api.post(url, headers=C, json=body)
    assert result.status_code == 403 and result.json()["detail"] == "COMMITTEE_MEMBERSHIP_REQUIRED"
    assert api.get(f"/api/cases/{case_id}/timeline", headers=A).json() == before
    with new_session() as session:
        assert session.scalar(select(func.count()).select_from(CaseNote)) == 0


def test_formation_requires_caller_membership_and_officer_authority(workspace):
    api, case_id = workspace
    url = f"/api/cases/{case_id}/committees"
    body = {"type": "SCRUTINY", "members": [{"user_ref": str(BOB), "role": "MEMBER"}]}
    assert api.post(url, headers=A, json=body).status_code == 403
    body["members"] = [{"user_ref": str(ALICE), "role": "CHAIR"}]
    assert api.post(url, headers=headers("INSTITUTION", SUNRISE), json=body).status_code == 403
    body["members"] *= 2
    assert api.post(url, headers=A, json=body).status_code == 422
    with new_session() as session:
        assert session.scalar(select(func.count()).select_from(Committee)) == 0


def test_controlled_keys_member_assignees_and_author_spoofing(workspace):
    api, case_id = workspace
    group = form(api, case_id)
    url = f"/api/committees/{group['id']}/tasks"
    assert api.post(url, headers=A, json={"title_key": "arbitrary prose", "assignee_user_ref": str(BOB)}).status_code == 422
    result = api.post(url, headers=A, json={"title_key": "REVIEW_DOCUMENTS", "assignee_user_ref": str(OUTSIDER)})
    assert result.status_code == 422 and result.json()["detail"] == "TASK_ASSIGNEE_NOT_MEMBER"
    assigned = task(api, group["id"])
    assert api.post(f"/api/tasks/{assigned['id']}/observations", headers=A,
        json={"body": "Fictional", "author_user_ref": str(BOB)}).status_code == 422
    assert report(api, group["id"], author_user_ref=str(BOB)).status_code == 422
    assert report(api, group["id"], "   ").status_code == 422


def test_case_scope_and_each_call_uses_authz(workspace):
    api, case_id = workspace
    group = form(api, case_id)
    foreign = headers("INSTITUTION", NORTHFIELD)
    ro = headers("RO_OFFICER") | {"X-Demo-Region": "DEMO_OTHER_REGION"}
    for suffix in ("", "/reports"):
        url = f"/api/committees/{group['id']}{suffix}"
        assert api.get(url, headers=foreign).status_code == 403
        assert api.get(url, headers=ro).status_code == 403
        assert api.get(url, headers=headers("AUDITOR")).status_code == 200
    real, calls = port(AuthzPort), []
    class Spy:
        def check(self, principal, action, resource):
            calls.append((action, resource))
            real.check(principal, action, resource)
    provide(AuthzPort, Spy())
    assigned = task(api, group["id"])
    assert calls[0][0] == "committee.task.assign"
    assert any(resource.id == UUID(case_id) for _, resource in calls)
    calls.clear()
    assert api.post(f"/api/tasks/{assigned['id']}/observations", headers=A, json={"body": "Fictional"}).status_code == 201
    assert calls[0][0] == "committee.observation.add"
    calls.clear()
    assert report(api, group["id"]).status_code == 201 and calls[0][0] == "committee.report.add"
    calls.clear()
    assert api.get(f"/api/committees/{group['id']}", headers=A).status_code == 200
    assert calls[0][0] == "committee.read"
    calls.clear()
    assert api.get(f"/api/committees/{group['id']}/reports", headers=A).status_code == 200
    assert calls[0][0] == "committee.read"
    calls.clear()
    form(api, case_id)
    assert calls[0][0] == "committee.create"


def db_report_fixture(workspace):
    # Administrative wf-only test setup deliberately bypasses HTTP so SQL guards
    # are tested independently of application authorization and NotesPort.
    _, case_id = workspace
    group_id = uuid5(NAMESPACE_URL, f"committee:db-fixture:{case_id}")
    report_id = uuid5(NAMESPACE_URL, f"committee:db-report:{case_id}")
    with new_session() as session, session.begin():
        session.add(Committee(id=group_id, application_id=UUID(case_id), type="SCRUTINY", status="ACTIVE"))
        session.flush()
        session.add(CommitteeMember(committee_id=group_id, user_ref=ALICE, role="CHAIR"))
        session.flush()
        session.add(ReportVersion(id=report_id, committee_id=group_id, version_no=1,
            content_note_ref=uuid5(NAMESPACE_URL, "committee:opaque-test-note"), content_note_hash="a" * 64,
            author_user_ref=ALICE, created_at=datetime(2026, 10, 26, 8, tzinfo=timezone.utc), parent_version=None))
    return group_id, stored_versions(group_id)[0]


def stored_versions(group_id):
    with new_session() as session:
        return [dict(row) for row in session.execute(select(ReportVersion.__table__)
            .where(ReportVersion.committee_id == group_id).order_by(ReportVersion.version_no)).mappings()]


@pytest.mark.parametrize("sql", ["UPDATE wf.report_version SET content_note_hash = content_note_hash WHERE id = :id",
                                  "DELETE FROM wf.report_version WHERE id = :id"])
def test_report_update_delete_blocked_by_database(workspace, sql):
    group_id, first = db_report_fixture(workspace)
    with pytest.raises(DBAPIError, match="REPORT_APPEND_ONLY"):
        with get_engine().begin() as connection:
            connection.execute(text(sql), {"id": first["id"]})
    assert stored_versions(group_id) == [first]


def test_no_report_update_or_delete_api(workspace):
    api, case_id = workspace
    group = form(api, case_id)
    first = report(api, group["id"]).json()
    for method in ("put", "patch", "delete"):
        result = getattr(api, method)(f"/api/committees/{group['id']}/reports/{first['id']}", headers=A)
        assert result.status_code in (404, 405)
    assert reports(api, group["id"]) == [first]


@pytest.mark.parametrize("number,parent", [(3, "LATEST"), (2, None)])
def test_database_rejects_report_gaps_and_wrong_parent(workspace, number, parent):
    group_id, first = db_report_fixture(workspace)
    with pytest.raises(DBAPIError, match="REPORT_PARENT_OR_VERSION_CONFLICT"):
        with get_engine().begin() as connection:
            connection.execute(insert(ReportVersion).values(id=uuid5(NAMESPACE_URL, "committee:invalid-version"),
                committee_id=group_id, version_no=number, content_note_ref=first["content_note_ref"],
                content_note_hash=first["content_note_hash"], author_user_ref=ALICE,
                created_at=first["created_at"], parent_version=first["id"] if parent else None))
    assert stored_versions(group_id) == [first]


def test_parent_conflict_clock_and_gap_free_concurrent_reports(workspace):
    api, case_id = workspace
    group = form(api, case_id)
    at = datetime(2026, 10, 26, 8, tzinfo=timezone.utc)
    provide(ClockPort, FakeClock(at))
    first = report(api, group["id"], parent_version=None)
    assert first.status_code == 201, first.text
    assert datetime.fromisoformat(first.json()["created_at"]) == at
    assert report(api, group["id"], parent_version=None).status_code == 409
    provide(ClockPort, FakeClock(datetime(2026, 10, 25, 8, tzinfo=timezone.utc)))
    backwards = report(api, group["id"])
    assert backwards.status_code == 409 and backwards.json()["detail"] == "CLOCK_BEFORE_REPORT_PARENT"
    with new_session() as session:
        assert session.scalar(select(func.count()).select_from(CaseNote)) == 1
    provide(ClockPort, FakeClock(at))
    barrier = Barrier(8)
    def append(index):
        barrier.wait(timeout=20)
        return report(api, group["id"], f"Fictional concurrent DEMO version {index}", A if index % 2 else B)
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(append, range(8)))
    assert all(result.status_code == 201 for result in results), [result.text for result in results]
    versions = reports(api, group["id"])
    assert [version["version_no"] for version in versions] == list(range(1, 10))
    assert sorted(result.json()["version_no"] for result in results) == list(range(2, 10))
    assert [version["parent_version"] for version in versions] == [None] + [version["id"] for version in versions[:-1]]
    for index, result in enumerate(results):
        assert result.json()["author_user_ref"] == str(ALICE if index % 2 else BOB)
    assert api.get("/api/ledger/verify", headers=headers("AUDITOR")).json()["ok"]


def test_ledger_failure_rolls_back_report_note_and_version_number(workspace, monkeypatch):
    api, case_id = workspace
    group = form(api, case_id)
    ledger = port(LedgerPort)
    append = ledger.append
    def failing(uow, event):
        result = append(uow, event)
        if event.event_type == "wf.report_version_added":
            raise RuntimeError("DEMO_REPORT_LEDGER_FAILURE")
        return result
    monkeypatch.setattr(ledger, "append", failing)
    with pytest.raises(RuntimeError, match="DEMO_REPORT_LEDGER_FAILURE"):
        report(api, group["id"])
    with new_session() as session:
        assert session.scalar(select(func.count()).select_from(ReportVersion)) == 0
        assert session.scalar(select(func.count()).select_from(CaseNote)) == 0
        assert session.scalar(select(func.count()).select_from(DomainEvent).where(DomainEvent.event_type == "wf.report_version_added")) == 0
    monkeypatch.setattr(ledger, "append", append)
    assert report(api, group["id"]).json()["version_no"] == 1
