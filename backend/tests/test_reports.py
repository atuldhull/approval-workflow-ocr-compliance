"""Pendency report with a snapshot hash, report types, and the OCEL event-log export."""
import json

from backend.tests.intake_test_helpers import ensure_intake_rules, provide_fixture_items
from conftest import NORTHFIELD, SUNRISE, headers

SUNRISE_H = headers("INSTITUTION", SUNRISE)
NORTHFIELD_H = headers("INSTITUTION", NORTHFIELD, user="00000000-0000-4000-9000-000000000004")
BUREAU = headers("BUREAU_HEAD", user="00000000-0000-4000-9000-000000000007")
AUDITOR = headers("AUDITOR", user="00000000-0000-4000-9000-000000000003")
RO_SOUTH = {**headers("RO_OFFICER", user="00000000-0000-4000-9000-000000000005"), "X-Demo-Region": "Southern"}


def file(client, h, inst, submit=True):
    ensure_intake_rules(client)
    app_id = client.post("/api/applications", headers=h, json={
        "institution_id": str(inst), "category": "NEW_PROGRAMME", "academic_year": "2027-28"}).json()["id"]
    if submit:
        provide_fixture_items(app_id)
        assert client.post(f"/api/applications/{app_id}/submit", headers=h, json={"dsc_present": True}).status_code == 200
    return app_id


def test_pendency_counts_cases_in_process_by_region_and_stage(client):
    file(client, SUNRISE_H, SUNRISE)
    file(client, SUNRISE_H, SUNRISE)
    file(client, SUNRISE_H, SUNRISE, submit=False)          # a draft is not pending at AICTE
    file(client, NORTHFIELD_H, NORTHFIELD)
    body = client.get("/api/dashboards/pendency", headers=BUREAU).json()
    rows = {(r["region"], r["stage"]): r["count"] for r in body["rows"]}
    assert rows == {("Northern", "SCRUTINY"): 1, ("Southern", "SCRUTINY"): 2}
    assert body["total"] == 3


def test_a_regional_officer_gets_only_their_region(client):
    file(client, SUNRISE_H, SUNRISE)
    file(client, NORTHFIELD_H, NORTHFIELD)
    body = client.get("/api/dashboards/pendency", headers=RO_SOUTH).json()
    assert body["scope"]["region"] == "Southern"
    assert {r["region"] for r in body["rows"]} == {"Southern"}
    assert client.get("/api/dashboards/pendency?region=Northern", headers=RO_SOUTH).status_code == 403
    assert client.get("/api/dashboards/pendency", headers=SUNRISE_H).status_code == 403


def test_the_snapshot_hash_is_reproducible_and_moves_with_the_ledger(client):
    file(client, SUNRISE_H, SUNRISE)
    first = client.get("/api/dashboards/pendency", headers=BUREAU).json()
    again = client.get("/api/dashboards/pendency", headers=BUREAU).json()
    assert first["snapshot_hash"] == again["snapshot_hash"]
    assert first["ledger_head"]["seq"] > 0 and len(first["ledger_head"]["entry_hash"]) == 64
    file(client, NORTHFIELD_H, NORTHFIELD, submit=False)   # a new event, even one that changes no count
    later = client.get("/api/dashboards/pendency", headers=BUREAU).json()
    assert later["rows"] == first["rows"]
    assert later["ledger_head"]["seq"] > first["ledger_head"]["seq"]
    assert later["snapshot_hash"] != first["snapshot_hash"]


def test_reports_by_type_and_unknown_types(client):
    file(client, SUNRISE_H, SUNRISE)
    by_type = client.get("/api/reports/pendency", headers=BUREAU).json()
    direct = client.get("/api/dashboards/pendency", headers=BUREAU).json()
    assert by_type["snapshot_hash"] == direct["snapshot_hash"]
    assert client.get("/api/reports/nonsense", headers=BUREAU).status_code == 404


def test_ocel_export_carries_the_log_without_payloads_or_personal_references(client):
    app_id = file(client, SUNRISE_H, SUNRISE)
    r = client.post("/api/exports", headers=AUDITOR, json={"format": "ocel2"})
    assert r.status_code == 200
    body = r.json()
    types = {e["type"] for e in body["events"]}
    assert {"wf.application_created", "wf.application_submitted"} <= types
    assert {t["name"] for t in body["eventTypes"]} == types
    assert {"id": app_id, "type": "application"} in body["objects"]
    event = next(e for e in body["events"] if e["type"] == "wf.application_submitted")
    assert event["relationships"] == [{"objectId": app_id, "qualifier": "application"}]
    assert {a["name"] for a in event["attributes"]} == {"role", "event_version", "ruleset_rev"}
    text = json.dumps(body)
    for leaked in ("payload", "personal_ref", "note_ref", "note_hash", "actor_id", str(SUNRISE)):
        assert leaked not in text
    assert len(body["snapshot_hash"]) == 64


def test_export_rejects_unknown_formats_and_non_oversight_roles(client):
    assert client.post("/api/exports", headers=AUDITOR, json={"format": "csv"}).status_code == 422
    assert client.post("/api/exports", headers=RO_SOUTH, json={"format": "ocel2"}).status_code == 403
    assert client.post("/api/exports", headers=SUNRISE_H, json={"format": "ocel2"}).status_code == 403
