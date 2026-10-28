"""Pendency report with a snapshot hash, report types, and the OCEL event-log export."""
import csv
import io
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


def test_the_catalogue_lists_every_report_with_its_columns_and_source(client):
    listed = client.get("/api/reports", headers=BUREAU).json()
    assert [r["type"] for r in listed] == ["pendency", "evc_status", "undertakings", "overdue", "region_performance"]
    assert all(r["title"] and r["source"] and r["columns"] for r in listed)
    assert client.get("/api/reports", headers=RO_SOUTH).status_code == 200
    assert client.get("/api/reports", headers=SUNRISE_H).status_code == 403


def register_loa(client, app_id, inst=SUNRISE, issued="2025-08-31"):
    r = client.post("/api/compliance/letters", headers=headers("BUREAU_OFFICER", user="00000000-0000-4000-9000-000000000006"),
                    json={"application_id": app_id, "institution_id": str(inst), "letter_type": "LOA",
                          "academic_year": "2025-26", "issue_date": issued, "issue_date_source": "PORTAL_EVENT",
                          "lists_deficiencies": False, "f_no": "F.No. DEMO/SOUTH/2025/00042"})
    assert r.status_code == 201, r.text
    return r.json()["obligation_ids"]


def test_overdue_lists_every_late_clock_with_its_owner_and_days(client):
    from app.deadlines.wiring import clock
    south = file(client, SUNRISE_H, SUNRISE)
    file(client, NORTHFIELD_H, NORTHFIELD)
    obligations = register_loa(client, south)
    clock.advance(35)                                   # past the 30-day processing clocks too
    body = client.get("/api/reports/overdue", headers=BUREAU).json()
    rules = sorted(r["rule_id"] for r in body["rows"])
    assert rules == sorted(["AICTE_PROCESSING"] * 2 + ["LOA_DEPOSIT_AFFIDAVIT_15D"] * len(obligations))
    processing = next(r for r in body["rows"] if r["rule_id"] == "AICTE_PROCESSING" and r["region"] == "Southern")
    assert processing["application_id"] == south and processing["case_ref"] == south[:8]
    assert processing["owner_role"] == "RO_OFFICER" and processing["days_overdue"] == 5
    assert processing["status"] == "RUNNING" and processing["escalation_level"] is None
    loa = next(r for r in body["rows"] if r["rule_id"] == "LOA_DEPOSIT_AFFIDAVIT_15D")
    assert loa["owner_role"] == "INSTITUTION" and loa["subject_type"] == "obligation" and loa["days_overdue"] > 400
    assert body["rows"][0]["days_overdue"] >= body["rows"][-1]["days_overdue"]     # most overdue first
    assert body["total"]["overdue"] == len(body["rows"]) and body["scope"]["as_of"]
    regional = client.get("/api/reports/overdue", headers=RO_SOUTH).json()
    assert {r["region"] for r in regional["rows"]} == {"Southern"}


def test_undertakings_count_obligations_by_kind_and_overdue(client):
    app_id = file(client, SUNRISE_H, SUNRISE)
    obligations = register_loa(client, app_id)
    body = client.get("/api/reports/undertakings", headers=BUREAU).json()
    assert sum(r["obligations"] for r in body["rows"]) == len(obligations)
    assert {(r["region"], r["status"]) for r in body["rows"]} == {("Southern", "OPEN")}
    assert body["total"] == {"obligations": len(obligations), "overdue": len(obligations),
                             "awaiting_verification": 0, "met_late": 0}
    assert client.get("/api/reports/undertakings", headers={
        **headers("RO_OFFICER", user="00000000-0000-4000-9000-000000000008"), "X-Demo-Region": "Northern"}
        ).json()["rows"] == []


def test_evc_status_and_region_performance_cover_every_region_in_scope(client):
    from app.deadlines.wiring import clock
    file(client, SUNRISE_H, SUNRISE)
    clock.advance(4)
    file(client, NORTHFIELD_H, NORTHFIELD)
    file(client, NORTHFIELD_H, NORTHFIELD)
    evc = client.get("/api/reports/evc_status", headers=BUREAU).json()
    assert evc["rows"] == [] and evc["total"]["requests"] == 0 and evc["total"]["completion_rate"] is None
    perf = client.get("/api/reports/region_performance", headers=BUREAU).json()
    rows = {r["region"]: r for r in perf["rows"]}
    assert (rows["Southern"]["in_process"], rows["Southern"]["median_age_days"]) == (1, 4)
    assert (rows["Northern"]["in_process"], rows["Northern"]["median_age_days"]) == (2, 0)
    assert rows["Southern"]["median_days_in_stage"] == 4 and rows["Southern"]["alerts_acknowledged_on_time"] is None
    assert [r["region"] for r in client.get("/api/reports/region_performance", headers=RO_SOUTH).json()["rows"]] == [
        "Southern"]


def test_every_report_downloads_as_csv_with_its_provenance(client):
    file(client, SUNRISE_H, SUNRISE)
    for report_type in ("pendency", "evc_status", "undertakings", "overdue", "region_performance"):
        body = client.get(f"/api/reports/{report_type}", headers=BUREAU).json()
        r = client.get(f"/api/reports/{report_type}?format=csv", headers=BUREAU)
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
        assert r.headers["content-disposition"].startswith(f'attachment; filename="{report_type}-all-')
        lines = r.text.splitlines()
        assert lines[0].split(",") == [c["label"] for c in body["columns"]]
        assert f"Snapshot hash,{body['snapshot_hash']}" in lines and r.headers["x-snapshot-hash"] == body["snapshot_hash"]
    by_accept = client.get("/api/reports/pendency", headers={**BUREAU, "Accept": "text/csv"})
    assert by_accept.headers["content-type"].startswith("text/csv") and "Southern,SCRUTINY,1" in by_accept.text
    assert client.get("/api/reports/pendency?format=xml", headers=BUREAU).status_code == 422


def test_csv_cells_are_never_read_as_formulas():
    from app.analytics.reports import to_csv
    body = {"title": "t", "source": "s", "scope": {"region": "=cmd"}, "columns": [{"key": "a", "label": "A"}],
            "rows": [{"a": "=HYPERLINK(1)"}, {"a": -3}, {"a": None}], "ledger_head": {"seq": 1},
            "snapshot_hash": "h"}
    rows = list(csv.reader(io.StringIO(to_csv(body))))
    assert rows[1:4] == [["'=HYPERLINK(1)"], ["-3"], [""]] and ["Region", "'=cmd"] in rows
