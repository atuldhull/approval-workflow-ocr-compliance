"""Role x endpoint regression matrix.

Pins the status every role gets from every Person 3 endpoint, and from the Person 1/2 endpoints whose access
Person 3's policy decides. When a new API is added or the policy changes, this table shows exactly which cell moved.
Codes: 200/201 allowed; 403 refused by policy; 404/409/422/503 = got past authorisation (nothing to act on, wrong
state, rejected input, not configured). The document, compliance and alert records are prepared so that every role
which passes authorisation gets a fixed answer, whatever order the roles are tried in.
Uses demo sign-in with the local engine; Cerbos is held to the same decisions by test_cerbos_parity.py.
"""
from dataclasses import replace
from uuid import uuid4

import pytest

from app.deadlines.wiring import clock
from app.platform import auth
from app.platform.demo_seed import seed_directory
from backend.tests.intake_test_helpers import ensure_intake_rules, provide_fixture_items
from conftest import NORTHFIELD, SUNRISE, headers
from document_fakes import CleanScanner, configure_documents, pdf

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
# who may see Sunrise's (Southern) case records: the institution itself, officers in scope, oversight
CASE_READERS = ("inst_sunrise", "committee", "ro_south") + OVERSIGHT
# officers in scope of Sunrise's case who may confirm a fact or verify evidence
CASE_OFFICERS = ("committee", "ro_south", "bureau_officer", "bureau_head")
# users outside ROLES prepare records, so no role in the matrix is the extractor, first reviewer or registrar
EXTRACTOR = headers("SCRUTINY_COMMITTEE", user=U(90))
REGISTRAR = headers("BUREAU_OFFICER", user=U(91))


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
     expect({"inst_sunrise": 200, "committee": 200, "ro_south": 200, "bureau_officer": 200, "bureau_head": 200, "auditor": 200})),
    ("case timeline", "GET", "/api/cases/{app}/timeline", None,
     expect({"inst_sunrise": 200, "committee": 200, "ro_south": 200, "bureau_officer": 200, "bureau_head": 200,
             "auditor": 200})),
    ("file for Sunrise", "POST", "/api/applications",
     {"institution_id": str(SUNRISE), "category": "NEW_PROGRAMME", "academic_year": "2027-28"},
     expect({"inst_sunrise": 201})),
    # regional officers get their own region's deadlines (the list is filtered, not refused)
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

    # ---- Person 2: documents. {version} is a clean, extracted upload on Sunrise's case. ----
    ("upload a document", "POST", "/api/applications/{app}/documents", lambda w: {
        "data": {"doc_type": "LAND_DEED"}, "files": {"file": ("deed.pdf", pdf("matrix-upload"), "application/pdf")},
        "headers": {"Idempotency-Key": "matrix-upload-0001"}}, expect({"inst_sunrise": 201})),
    ("a case's documents", "GET", "/api/applications/{app}/documents", None, expect(CASE_READERS)),
    # institutions get only their own, a regional officer only their region
    ("documents across cases", "GET", "/api/documents", None, expect(ALL)),
    ("another region's documents", "GET", "/api/documents?region=Northern", None,
     expect(tuple(r for r in ALL if r != "ro_south"))),
    # a rescan (document.rescan) is for the owning institution and the case officers who can chase a stuck scan;
    # the version is already clean, so nothing changes
    ("rescan a version", "POST", "/api/document-versions/{version}/scan", None,
     expect(("inst_sunrise", "ro_south", "bureau_officer", "bureau_head"))),
    # the stored file is served to whoever may read the version's facts
    ("view a clean version", "GET", "/api/document-versions/{version}/content", None, expect(CASE_READERS)),
    # {quarantined} never got a scan verdict: the same readers pass authorisation and are told it cannot be viewed
    ("view a quarantined version", "GET", "/api/document-versions/{quarantined}/content", None,
     expect(CASE_READERS, code=409)),
    ("extract facts again", "POST", "/api/document-versions/{version}/extract", None,
     expect(("committee", "ro_south"))),
    # institutions see confirmed values only (none yet); officers and oversight see the proposals
    ("a version's facts", "GET", "/api/document-versions/{version}/facts", None, expect(CASE_READERS)),
    # another reviewer already typed a value for {fact_open}: allowed reviewers get 409, never the suggestion
    ("type a value", "POST", "/api/document-facts/{fact_open}/entry", {"value": "2025-03-12"},
     expect(("committee", "ro_south"), code=409)),
    # only the reviewer who typed first sees the suggestion again; {fact_mine} was typed by "committee"
    ("reveal the suggestion", "POST", "/api/document-facts/{fact_mine}/reveal", None, expect(("committee",))),
    ("review someone else's entry", "POST", "/api/document-facts/{fact_open}/review", {"decision": "ACCEPTED"},
     expect(("committee", "ro_south"), code=409)),
    ("confirm an unreviewed fact", "POST", "/api/document-facts/{fact_proposed}/confirm", None,
     expect(CASE_OFFICERS, code=409)),

    # ---- Person 2: compliance. {letter} is an LoA for Sunrise's case with its obligations. ----
    # the second bureau role finds the same LoA already registered
    ("register an LoA", "POST", "/api/compliance/letters", lambda w: {"json": letter_body(w["app"], "2026-27")},
     expect({"bureau_officer": 201, "bureau_head": 409})),
    ("letters", "GET", "/api/compliance/letters", None, expect(ALL)),
    ("another region's letters", "GET", "/api/compliance/letters?region=Northern", None,
     expect(tuple(r for r in ALL if r != "ro_south"))),
    ("a case's letters", "GET", "/api/compliance/letters?application_id={app}", None, expect(CASE_READERS)),
    ("one letter", "GET", "/api/compliance/letters/{letter}", None, expect(CASE_READERS)),
    ("obligations", "GET", "/api/compliance/obligations", None, expect(ALL)),
    ("one obligation", "GET", "/api/compliance/obligations/{obligation}", None, expect(CASE_READERS)),
    ("submit evidence", "POST", "/api/compliance/obligations/{obligation_open}/evidence",
     lambda w: {"json": {"document_version_id": w["version"]}}, expect({"inst_sunrise": 201})),
    # a rejection without a reason code is refused after authorisation, so nothing is decided
    ("verify evidence", "POST", "/api/compliance/evidence/{evidence}/verify", {"decision": "REJECTED"},
     expect(CASE_OFFICERS, code=422)),
    # the verifier's note: officers who may verify and the owning institution; oversight-only roles see has_note only
    ("an evidence note", "GET", "/api/compliance/evidence/{evidence}/note", None,
     expect(CASE_OFFICERS + ("inst_sunrise",))),
    # the regional officer records the lease deed's date first; the bureau then finds that version recorded
    ("record a validity date", "POST", "/api/compliance/validity",
     lambda w: {"json": {"document_version_id": w["version"], "valid_until": "2031-03-31"}},
     expect({"ro_south": 201, "bureau_officer": 409, "bureau_head": 409})),
    ("record an undertaking", "POST", "/api/compliance/obligations",
     lambda w: {"json": {"application_id": w["app"], "kind": "UNDERTAKING", "title": "Synthetic undertaking",
                         "evidence_required": "A synthetic receipt", "source_clause": "2.25(f)",
                         "due_date": "2099-01-01"}},
     expect(("ro_south", "bureau_officer", "bureau_head"), code=201)),

    # ---- Person 2: alerts and demo timers. {alert} is the level-0 reminder to the Southern regional office. ----
    ("alerts", "GET", "/api/alerts", None, expect(ALL)),
    # a regional officer asking for another region is refused rather than silently given its own
    ("another region's alerts", "GET", "/api/alerts?region=Northern", None,
     expect(tuple(r for r in ALL if r != "ro_south"))),
    # policy lets officers and institutions acknowledge; the deadlines module then requires the addressed role
    ("acknowledge an alert", "POST", "/api/alerts/{alert}/ack", None, expect(("ro_south",))),
    ("time travel", "POST", "/api/sim/clock", {"days": 1}, expect(ALL)),
    ("run the timers", "POST", "/api/sim/timers/run", None, expect(ALL)),
    # checked as a "deadline" record with the case's institution and region: the Southern officer passes
    ("explain a deadline", "GET", "/api/deadlines/{deadline}/explain", None,
     expect(("inst_sunrise", "committee", "ro_south") + OVERSIGHT)),
]


def letter_body(app_id: str, year: str = "2025-26") -> dict:
    return {"application_id": app_id, "institution_id": str(SUNRISE), "letter_type": "LOA", "academic_year": year,
            "issue_date": "2025-08-31", "issue_date_source": "PORTAL_EVENT", "lists_deficiencies": False,
            "f_no": "F.No. DEMO/SOUTH/2025/00099"}


class World(dict):
    """The records a row names, built the first time a row asks for one."""

    def __init__(self, client, app_id, scanner):
        super().__init__(app=app_id, random=str(uuid4()))
        self.client = client
        self.scanner = scanner

    @staticmethod
    def ok(response):
        assert response.status_code in (200, 201), response.text
        return response.json()

    def __missing__(self, key):
        build = getattr(self, f"_{key}", None)
        if build is None:
            raise KeyError(key)
        build()
        return self[key]

    def _version(self):
        c = self.client
        up = self.ok(c.post(f"/api/applications/{self['app']}/documents",
                            headers={**ROLES["inst_sunrise"], "Idempotency-Key": "matrix-world-0001"},
                            data={"doc_type": "LEASE_DEED"},
                            files={"file": ("lease.pdf", pdf("matrix-world"), "application/pdf")}))
        version = up["version"]["version_id"]
        # the scan runs as a background task after the upload response
        listed = self.ok(c.get(f"/api/applications/{self['app']}/documents", headers=ROLES["auditor"]))
        assert listed[0]["versions"][0]["scan_status"] == "clean", listed
        self.ok(c.post(f"/api/document-versions/{version}/extract", headers=EXTRACTOR))
        self["version"] = version

    def _quarantined(self):
        self.scanner.down = True   # the scan after the upload cannot run, so the version stays quarantined
        try:
            up = self.ok(self.client.post(f"/api/applications/{self['app']}/documents",
                                          headers={**ROLES["inst_sunrise"], "Idempotency-Key": "matrix-world-0002"},
                                          data={"doc_type": "FIRE_NOC"},
                                          files={"file": ("noc.pdf", pdf("matrix-pending"), "application/pdf")}))
        finally:
            self.scanner.down = False
        assert up["version"]["status"] == "QUARANTINED", up
        self["quarantined"] = up["version"]["version_id"]

    def _facts(self):
        facts = self.ok(self.client.get(f"/api/document-versions/{self['version']}/facts",
                                        headers=ROLES["auditor"]))["facts"]
        by_field = {f["field_key"]: f["fact_id"] for f in facts}
        self["fact_proposed"] = by_field["letter_file_number"]
        self["fact_open"] = by_field["letter_issue_date"]
        self["fact_mine"] = by_field["lease_end_date"]
        self.ok(self.client.post(f"/api/document-facts/{self['fact_open']}/entry", headers=EXTRACTOR,
                                 json={"value": "2025-03-12"}))
        self.ok(self.client.post(f"/api/document-facts/{self['fact_mine']}/entry", headers=ROLES["committee"],
                                 json={"value": "2030-03-31"}))

    _fact_proposed = _fact_open = _fact_mine = _facts

    def _letter(self):
        letter = self.ok(self.client.post("/api/compliance/letters", headers=REGISTRAR,
                                          json=letter_body(self["app"])))
        self["letter"] = letter["id"]
        self["obligation"], self["obligation_open"] = letter["obligation_ids"][:2]

    _obligation = _obligation_open = _letter

    def _evidence(self):
        self["evidence"] = self.ok(self.client.post(
            f"/api/compliance/obligations/{self['obligation']}/evidence", headers=ROLES["inst_sunrise"],
            json={"document_version_id": self["version"]}))["id"]

    def _deadline(self):
        mine = self.ok(self.client.get(f"/api/deadlines?subject_id={self['app']}", headers=ROLES["auditor"]))
        self["deadline"] = next(d["id"] for d in mine if d["rule_id"] == "AICTE_PROCESSING")

    def _alert(self):
        seed_directory()
        clock.advance(29)   # two days before the 30-day processing clock is due: the level-0 reminder
        self.ok(self.client.post("/api/sim/timers/run", headers=ROLES["auditor"]))
        alerts = self.ok(self.client.get(f"/api/alerts?deadline_id={self['deadline']}", headers=ROLES["auditor"]))
        self["alert"] = next(a["id"] for a in alerts if a["level"] == 0 and a["role"] == "RO_OFFICER")


@pytest.fixture
def case(client, tmp_path):
    scanner = CleanScanner()
    reset = configure_documents(tmp_path, scanner)
    h = ROLES["inst_sunrise"]
    ensure_intake_rules(client)
    app_id = client.post("/api/applications", headers=h, json={
        "institution_id": str(SUNRISE), "category": "NEW_PROGRAMME", "academic_year": "2027-28"}).json()["id"]
    provide_fixture_items(app_id)
    assert client.post(f"/api/applications/{app_id}/submit", headers=h, json={"dsc_present": True}).status_code == 200
    yield World(client, app_id, scanner)
    reset()


def _request(client, method, url, h, body, world):
    kw = body(world) if callable(body) else {"json": body}
    return client.request(method, url, **{**kw, "headers": {**h, **kw.get("headers", {})}})


@pytest.mark.parametrize("name, method, path, body, expected", MATRIX, ids=[m[0] for m in MATRIX])
def test_role_matrix(client, case, name, method, path, body, expected):
    url = path.format_map(case)
    got = {role: _request(client, method, url, h, body, case).status_code for role, h in ROLES.items()}
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
