"""Read endpoints the frontend needed, and intake's document_ref check (fictional DEMO data only)."""
from dataclasses import replace
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest

from conftest import NORTHFIELD, SUNRISE, headers
from document_fakes import CleanScanner, configure_documents, pdf

INST = headers("INSTITUTION", SUNRISE)
NORTH_INST = headers("INSTITUTION", NORTHFIELD)
RO_SOUTH = dict(headers("RO_OFFICER"), **{"X-Demo-Region": "Southern"})
RO_NORTH = dict(headers("RO_OFFICER"), **{"X-Demo-Region": "Northern"})
ALICE = "00000000-0000-4000-9000-0000000000c1"
BOB = "00000000-0000-4000-9000-0000000000c2"
CHAIR = headers("SCRUTINY_COMMITTEE", user=ALICE)
FIXTURE = str(uuid5(NAMESPACE_URL, "DEMO:gap-read-document"))
KEY = "aph-2024-27@r1"


@pytest.fixture
def api(client, tmp_path):
    scanner = CleanScanner()
    with client:  # startup wires the real document adapters; the fakes replace them afterwards
        undo = configure_documents(tmp_path, scanner)
        client.scanner = scanner
        yield client
        undo()


def draft(api, auth=INST, institution=SUNRISE):
    response = api.post("/api/applications", headers=auth, json=dict(
        institution_id=str(institution), category="NEW_PROGRAMME", academic_year="2027-28"))
    assert response.status_code == 201, response.text
    return response.json()["id"]


def upload(api, app_id, marker, auth=INST):
    response = api.post(f"/api/applications/{app_id}/documents", headers={**auth, "Idempotency-Key": f"gap-upload-{app_id}-{marker}"}, data={"doc_type": "DEMO_CORE_REFERENCE"},
                        files={"file": (f"{marker}.pdf", pdf(marker), "application/pdf")})
    assert response.status_code == 201, response.text
    version = response.json()["version"]
    from app.documents.models import DocumentVersion
    from app.platform.db import new_session
    with new_session() as session:  # the scan runs after the upload response, so read the settled status
        version["status"] = session.get(DocumentVersion, UUID(version["version_id"])).status
    return version


def provide(api, app_id, ref, auth=INST):
    return api.post(f"/api/applications/{app_id}/items", headers=auth,
                    json={"items": [{"item_key": "DEMO_CORE_REFERENCE", "document_ref": str(ref)}]})


def test_document_ref_must_be_an_available_version_of_the_same_application(api):
    app_id, other = draft(api), draft(api)
    version = upload(api, app_id, "core")
    assert version["status"] == "AVAILABLE"
    accepted = provide(api, app_id, version["version_id"])
    assert accepted.status_code == 200, accepted.text
    core = next(item for item in accepted.json()["items"] if item["item_key"] == "DEMO_CORE_REFERENCE")
    assert core == dict(item_key="DEMO_CORE_REFERENCE", mandatory=True, state="PROVIDED", document_ref=version["version_id"])
    # another application's clean version and an unknown random ID read the same: nothing about other files leaks
    for ref in (version["version_id"], uuid4()):
        refused = provide(api, other, ref)
        assert refused.status_code == 422 and refused.json()["detail"] == "DOCUMENT_REF_UNKNOWN", refused.text
    api.scanner.down = True  # the scan never answers: the version stays QUARANTINED
    pending = upload(api, other, "pending")
    assert pending["status"] == "QUARANTINED"
    refused = provide(api, other, pending["version_id"])
    assert refused.status_code == 422 and refused.json()["detail"] == "DOCUMENT_REF_NOT_AVAILABLE"
    checklist = api.get(f"/api/applications/{other}/checklist", headers=INST).json()
    assert all(item["state"] == "MISSING" for item in checklist["items"])  # refused writes leave nothing behind


def test_demo_fixture_references_are_accepted_only_in_demo_mode(api, monkeypatch):
    import app.platform.settings as configuration
    app_id = draft(api)
    assert provide(api, app_id, FIXTURE).status_code == 200
    created = api.post("/api/applications", headers=INST, json=dict(institution_id=str(SUNRISE), category="NEW_PROGRAMME",
        academic_year="2027-28", items=[dict(item_key="DEMO_CORE_REFERENCE", document_ref=FIXTURE)]))
    assert created.status_code == 201, created.text
    monkeypatch.setattr(configuration, "settings", replace(configuration.settings, demo_mode=False))
    refused = provide(api, draft(api), str(uuid5(NAMESPACE_URL, "DEMO:gap-read-document-2")))
    assert refused.status_code == 422 and refused.json()["detail"] == "DOCUMENT_REF_UNKNOWN"
    version = upload(api, app_id, "real")
    assert provide(api, app_id, version["version_id"]).status_code == 200  # real versions still work without DEMO_MODE


def test_application_read_is_region_scoped_for_regional_officers(api):
    south, north = draft(api), draft(api, NORTH_INST, NORTHFIELD)
    assert api.get(f"/api/applications/{south}", headers=RO_SOUTH).json()["id"] == south
    assert api.get(f"/api/applications/{north}", headers=RO_SOUTH).status_code == 403
    assert api.get(f"/api/applications/{north}", headers=RO_NORTH).status_code == 200
    assert api.get(f"/api/applications/{north}", headers=INST).status_code == 403
    assert api.get(f"/api/applications/{south}", headers=headers("AUDITOR")).status_code == 200
    assert api.get(f"/api/applications/{uuid4()}", headers=RO_SOUTH).status_code == 404


def test_deficiency_vocabulary_comes_from_the_pinned_configuration(api):
    from app.platform.db import new_session
    from app.workflow.deficiency import config
    body = api.get(f"/api/rulesets/{KEY}/deficiency-vocabulary", headers=INST)
    assert body.status_code == 200, body.text
    with new_session() as session:
        pinned = config(session, KEY)
    assert body.json() == dict(ruleset_key=KEY, item_keys=pinned["item_keys"], reason_codes=pinned["reason_codes"],
        response_rule_id=pinned["response_rule_id"], source_status="DEMO_ASSUMPTION", assumption_code=pinned["assumption_code"])
    assert body.json()["item_keys"] and body.json()["reason_codes"]
    for auth in (RO_SOUTH, headers("AUDITOR"), headers("BUREAU_HEAD")):
        assert api.get(f"/api/rulesets/{KEY}/deficiency-vocabulary", headers=auth).status_code == 200
    assert api.get("/api/rulesets/missing@r9/deficiency-vocabulary", headers=INST).status_code == 404


def test_case_committee_list_in_formation_order_with_latest_report(api):
    case_id = draft(api)
    members = [{"user_ref": ALICE, "role": "CHAIR"}, {"user_ref": BOB, "role": "MEMBER"}]
    assert api.get(f"/api/cases/{case_id}/committees", headers=CHAIR).json() == []
    ids = []
    for kind in ("SCRUTINY", "EVC"):
        formed = api.post(f"/api/cases/{case_id}/committees", headers=CHAIR, json={"type": kind, "members": members})
        assert formed.status_code == 201, formed.text
        ids.append(formed.json()["id"])
    for content in ("Fictional DEMO report v1", "Fictional DEMO report v2"):
        assert api.post(f"/api/committees/{ids[1]}/reports", headers=CHAIR, json={"content": content}).status_code == 201
    listed = api.get(f"/api/cases/{case_id}/committees", headers=CHAIR)
    assert listed.status_code == 200, listed.text
    first, second = listed.json()
    assert [first["id"], second["id"]] == ids and [first["ordinal"], second["ordinal"]] == [1, 2]
    assert first["type"] == "SCRUTINY" and first["latest_report"] is None and first["report_count"] == 0
    assert sorted(m["user_ref"] for m in second["members"]) == [ALICE, BOB]
    assert second["report_count"] == 2 and second["latest_report"]["version_no"] == 2
    assert set(second["latest_report"]) == {"id", "version_no", "created_at", "author_user_ref", "content_note_hash"}
    assert api.get(f"/api/cases/{case_id}/committees", headers=INST).status_code == 200
    assert api.get(f"/api/cases/{case_id}/committees", headers=RO_SOUTH).status_code == 200
    assert api.get(f"/api/cases/{case_id}/committees", headers=RO_NORTH).status_code == 403
    assert api.get(f"/api/cases/{case_id}/committees", headers=NORTH_INST).status_code == 403
    assert api.get(f"/api/cases/{uuid4()}/committees", headers=CHAIR).status_code == 404
    # a single committee and its reports read with the same case scope
    for path in (f"/api/committees/{ids[1]}", f"/api/committees/{ids[1]}/reports"):
        assert api.get(path, headers=RO_SOUTH).status_code == 200
        assert api.get(path, headers=RO_NORTH).status_code == 403
        assert api.get(path, headers=NORTH_INST).status_code == 403
