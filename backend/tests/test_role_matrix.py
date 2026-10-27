"""Role x endpoint regression matrix.

Pins the status every role gets from every Person 3 endpoint, and from the Person 1/2 endpoints whose access
Person 3's policy decides. When a new API is added or the policy changes, this table shows exactly which cell moved.
Codes: 200/201 allowed; 403 refused by policy; 404/503 = got past authorisation (nothing to act on / not configured).
Uses demo sign-in with the local engine; Cerbos is held to the same decisions by test_cerbos_parity.py.
"""
from dataclasses import replace
from uuid import uuid4

import pytest

from app.platform import auth
from conftest import NORTHFIELD, SUNRISE, headers

U = lambda n: f"00000000-0000-4000-9000-{n:012d}"  # noqa: E731
ROLES = {
    "inst_sunrise": headers("INSTITUTION", SUNRISE, user=U(1)),
    "inst_north": headers("INSTITUTION", NORTHFIELD, user=U(4)),
    "committee": headers("SCRUTINY_COMMITTEE", user=U(2)),
    "ro_south": {**headers("RO_OFFICER", user=U(5)), "X-Demo-Region": "Southern"},
    "ro_north": {**headers("RO_OFFICER", user=U(8)), "X-Demo-Region": "Northern"},
    "bureau_officer": headers("BUREAU_OFFICER", user=U(6)),
    "bureau_head": headers("BUREAU_HEAD", user=U(7)),
    "auditor": headers("AUDITOR", user=U(3)),
}
ALL = list(ROLES)
OVERSIGHT = ("bureau_officer", "bureau_head", "auditor")


def expect(allowed: dict | tuple, default=403, code=200):
    table = dict.fromkeys(ALL, default)
    table.update(allowed if isinstance(allowed, dict) else dict.fromkeys(allowed, code))
    return table


# (name, method, path template, json body, expected status per role). {app} is Sunrise's (Southern) submitted case.
MATRIX = [
    ("who am I", "GET", "/api/auth/me", None, expect(ALL)),
    # Person 1 endpoint: today every role, institutions included, can list all institutions (handoff P1 #8)
    ("institution list", "GET", "/api/institutions", None, expect(ALL)),
    ("own vs other institution's case", "GET", "/api/applications/{app}", None,
     expect({"inst_sunrise": 200, "committee": 200, "bureau_officer": 200, "bureau_head": 200, "auditor": 200})),
    ("case timeline", "GET", "/api/cases/{app}/timeline", None,
     expect({"inst_sunrise": 200, "committee": 200, "ro_south": 200, "bureau_officer": 200, "bureau_head": 200,
             "auditor": 200})),
    ("file for Sunrise", "POST", "/api/applications",
     {"institution_id": str(SUNRISE), "category": "NEW_PROGRAMME", "academic_year": "2027-28"},
     expect({"inst_sunrise": 201})),
    # regional officers list their own region's deadlines (the list is filtered to it)
    ("all deadlines", "GET", "/api/deadlines", None, expect(("committee", "ro_south", "ro_north") + OVERSIGHT)),
    ("ledger chain", "GET", "/api/ledger/verify", None, expect(OVERSIGHT)),
    ("audit verify", "GET", "/api/audit/verify", None, expect(OVERSIGHT)),
    ("checkpoint list", "GET", "/api/audit/checkpoints", None, expect(OVERSIGHT)),
    ("sign checkpoint", "POST", "/api/audit/checkpoints", None, expect(("bureau_head", "auditor"), code=503)),
    ("publish pending checkpoints", "POST", "/api/audit/checkpoints/publish", None,
     expect(("bureau_head", "auditor"), code=503)),
    ("run replay", "POST", "/api/audit/replay", None, expect(("bureau_head", "auditor"))),
    ("own inbox", "GET", "/api/notifications/inbox", None, expect(ALL)),
    ("delivery health", "GET", "/api/notifications/health", None, expect(OVERSIGHT)),
    ("outbox", "GET", "/api/notifications/outbox", None, expect(OVERSIGHT)),
    ("requeue a dead letter", "POST", "/api/notifications/outbox/{random}/retry", None,
     expect(("bureau_head",), code=404)),
    ("dashboard", "GET", "/api/analytics/dashboard", None,
     expect(("committee", "ro_south", "ro_north") + OVERSIGHT)),
    ("another region's dashboard", "GET", "/api/analytics/dashboard?region=Northern", None,
     expect(("committee", "ro_north") + OVERSIGHT)),
    ("scorecard", "GET", "/api/analytics/scorecard", None, expect(OVERSIGHT)),
    ("pendency report", "GET", "/api/dashboards/pendency", None,
     expect(("committee", "ro_south", "ro_north") + OVERSIGHT)),
    ("another region's pendency", "GET", "/api/dashboards/pendency?region=Northern", None,
     expect(("committee", "ro_north") + OVERSIGHT)),
    ("report by type", "GET", "/api/reports/pendency", None,
     expect(("committee", "ro_south", "ro_north") + OVERSIGHT)),
    ("event-log export", "POST", "/api/exports", {"format": "ocel2"}, expect(OVERSIGHT)),
]


@pytest.fixture
def case(client):
    h = ROLES["inst_sunrise"]
    app_id = client.post("/api/applications", headers=h, json={
        "institution_id": str(SUNRISE), "category": "NEW_PROGRAMME", "academic_year": "2027-28"}).json()["id"]
    client.post(f"/api/applications/{app_id}/submit", headers=h)
    return {"app": app_id, "random": str(uuid4())}


@pytest.mark.parametrize("name, method, path, body, expected", MATRIX, ids=[m[0] for m in MATRIX])
def test_role_matrix(client, case, name, method, path, body, expected):
    url = path.format(**case)
    got = {role: client.request(method, url, headers=h, json=body).status_code for role, h in ROLES.items()}
    assert got == expected, f"{name}: {[(r, got[r], expected[r]) for r in ALL if got[r] != expected[r]]}"


def test_committee_is_refused_case_access_when_assignments_are_required(client, case, monkeypatch):
    monkeypatch.setattr(auth, "settings", replace(auth.settings, authz_require_assignment=True))
    h = ROLES["committee"]
    for url in (f"/api/applications/{case['app']}", f"/api/cases/{case['app']}/timeline",
                f"/api/deadlines?subject_id={case['app']}", "/api/deadlines"):
        assert client.get(url, headers=h).status_code == 403, url
    assert client.get("/api/analytics/dashboard", headers=h).status_code == 200   # no case records in it
    assert client.get(f"/api/applications/{case['app']}", headers=ROLES["bureau_officer"]).status_code == 200


def test_time_travel_is_refused_to_everyone_outside_demo_mode(client, monkeypatch):
    monkeypatch.setattr(auth, "settings", replace(auth.settings, demo_mode=False))
    for role, h in ROLES.items():
        assert client.post("/api/sim/clock", headers=h, json={"days": 1}).status_code == 403, role


def test_an_institution_cannot_read_another_institutions_notifications(client):
    """Inbox rows are per recipient group; marking another group's notification looks like 'not found'."""
    assert client.post(f"/api/notifications/inbox/{uuid4()}/read", headers=ROLES["inst_north"]).status_code == 404
