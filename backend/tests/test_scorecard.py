"""Scorecard items measured from Person 2's records: scanning, four-eyes, OCR agreement and alert timeliness.

Each check is driven through the real endpoints; where the database allows it, a record is then broken on
purpose (test-only SQL) to show the check reports it.
"""
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.deadlines.wiring import clock
from app.platform.db import get_engine
from app.platform.demo_seed import seed_directory
from backend.tests.intake_test_helpers import ensure_intake_rules, provide_fixture_items
from conftest import SUNRISE, headers
from document_fakes import CleanScanner, configure_documents, pdf

INST = headers("INSTITUTION", SUNRISE, user="00000000-0000-4000-9000-000000000001")
REVIEWER = headers("SCRUTINY_COMMITTEE", user="00000000-0000-4000-9000-000000000002")
CONFIRMER = {**headers("RO_OFFICER", user="00000000-0000-4000-9000-000000000005"), "X-Demo-Region": "Southern"}
HEAD = headers("BUREAU_HEAD", user="00000000-0000-4000-9000-000000000007")


@pytest.fixture
def scanner(tmp_path):
    s = CleanScanner()
    reset = configure_documents(tmp_path, scanner=s)
    yield s
    reset()


def items(client) -> dict:
    r = client.get("/api/analytics/scorecard", headers=HEAD)
    assert r.status_code == 200, r.text
    return {i["key"]: i for i in r.json()["items"]}


def submitted(client) -> str:
    ensure_intake_rules(client)
    app_id = client.post("/api/applications", headers=INST, json={
        "institution_id": str(SUNRISE), "category": "NEW_PROGRAMME", "academic_year": "2027-28"}).json()["id"]
    provide_fixture_items(app_id)
    assert client.post(f"/api/applications/{app_id}/submit", headers=INST, json={"dsc_present": True}).status_code == 200
    return app_id


def upload(client, app_id, marker="score") -> str:
    r = client.post(f"/api/applications/{app_id}/documents", headers={**INST, "Idempotency-Key": f"key-{marker}"},
                    data={"doc_type": "LEASE_DEED"}, files={"file": (f"{marker}.pdf", pdf(marker), "application/pdf")})
    assert r.status_code == 201, r.text
    return r.json()["version"]["version_id"]


def review(client, fact_id, typed, decision, value=None):
    entry = client.post(f"/api/document-facts/{fact_id}/entry", headers=REVIEWER, json={"value": typed})
    assert entry.status_code == 200, entry.text
    body = {"decision": decision, **({"value": value} if value else {})}
    r = client.post(f"/api/document-facts/{fact_id}/review", headers=REVIEWER, json=body)
    assert r.status_code == 200, r.text


def test_reviewed_and_confirmed_facts_are_measured(client, scanner):
    version = upload(client, submitted(client))
    assert client.post(f"/api/document-versions/{version}/extract", headers=REVIEWER).status_code == 201
    facts = client.get(f"/api/document-versions/{version}/facts", headers=HEAD).json()["facts"]
    fact = {f["field_key"]: f["fact_id"] for f in facts}
    review(client, fact["letter_issue_date"], "2025-03-12", "ACCEPTED")          # blind entry agrees with OCR
    review(client, fact["lease_end_date"], "2030-03-30", "CORRECTED", "2030-03-30")  # and here it does not
    # four-eyes: the reviewer is refused, a second officer confirms
    assert client.post(f"/api/document-facts/{fact['letter_issue_date']}/confirm", headers=REVIEWER).status_code == 409
    for f in ("letter_issue_date", "lease_end_date"):
        assert client.post(f"/api/document-facts/{fact[f]}/confirm", headers=CONFIRMER).status_code == 200

    got = items(client)
    scan = got["document_scanning"]
    assert (scan["kind"], scan["outcome"]) == ("VERIFIED_NOW", "PASS")
    assert scan["result"]["versions"] == scan["result"]["clean"] == 1
    assert scan["result"]["used_while_not_clean"] == {"extractions": 0, "evidence": 0, "letters": 0}
    eyes = got["four_eyes"]
    assert (eyes["kind"], eyes["outcome"]) == ("VERIFIED_NOW", "PASS")
    assert (eyes["result"]["confirmed_facts"], eyes["result"]["confirmed_by_own_reviewer"]) == (2, 0)
    ocr = got["ocr"]
    assert ocr["kind"] == "MEASURED_ON_DEMO_TRAFFIC" and ocr["outcome"] is None
    assert (ocr["result"]["reviewed"], ocr["result"]["accepted"], ocr["result"]["corrected"]) == (2, 1, 1)
    assert ocr["result"]["blind_entry_agreement"] == 0.5
    for item in (scan, eyes, ocr):
        assert item["method"] and item["finding"] and item["method"] != item["finding"]

    # the check is a second line of defence: even around the API and its guard trigger, the table refuses a fact
    # confirmed by its own reviewer, so the scorecard can only ever count zero here
    with pytest.raises(IntegrityError, match="ck_doc_fact_confirmation"), get_engine().begin() as c:
        c.execute(text("SET LOCAL session_replication_role = replica"))   # test-only: skip the guard trigger
        c.execute(text("UPDATE doc.fact SET confirmed_by = review_typed_by WHERE fact_id = :f"),
                  {"f": fact["lease_end_date"]})


def test_a_scan_that_never_finishes_needs_attention(client, scanner):
    scanner.down = True
    upload(client, submitted(client), marker="stuck")
    scan = items(client)["document_scanning"]
    assert (scan["outcome"], scan["result"]["scan_pending"]) == ("PASS", 1)
    clock.advance(1)
    scan = items(client)["document_scanning"]
    assert scan["outcome"] == "ATTENTION" and scan["result"]["oldest_pending_minutes"] >= 24 * 60


def advance_to_last_day_before_processing_due():
    """Move to the final day before AICTE_PROCESSING falls due, so every reminder level has fallen due.

    The clock counts working days on the holiday calendar, so the calendar distance depends on today's date."""
    with get_engine().connect() as c:
        due = c.scalar(text("SELECT max(due_at) FROM dl.deadline WHERE rule_id = 'AICTE_PROCESSING'"))
    clock.advance((due - clock.now()).days)


def test_alert_levels_that_fell_due_are_compared_with_alerts_raised(client):
    seed_directory()
    submitted(client)
    assert items(client)["alerts"]["kind"] == "NOT_EVALUATED"
    advance_to_last_day_before_processing_due()   # the reminders fall due; the timer worker has not run
    alerts = items(client)["alerts"]
    assert alerts["kind"] == "MEASURED_ON_DEMO_TRAFFIC" and alerts["outcome"] == "FAIL"
    assert alerts["result"]["missed"] >= 1 and alerts["result"]["raised"] == 0
    assert client.post("/api/sim/timers/run", headers=HEAD).status_code == 200
    alerts = items(client)["alerts"]
    assert alerts["outcome"] == "PASS", alerts["finding"]
    assert alerts["result"]["missed"] == 0 and alerts["result"]["raised"] == alerts["result"]["levels_due"] >= 1
    # after an acknowledgement, the levels raised before it still count as due and raised
    ro = {**headers("RO_OFFICER", user="00000000-0000-4000-9000-000000000005"), "X-Demo-Region": "Southern"}
    for alert in client.get("/api/alerts?status=OPEN", headers=ro).json():
        assert client.post(f"/api/alerts/{alert['id']}/ack", headers=ro).status_code == 200
    acked = items(client)["alerts"]
    assert acked["outcome"] == "PASS", acked["finding"]
    assert acked["result"]["raised"] == alerts["result"]["raised"]


def test_alert_raised_before_its_level_was_due_is_reported(client):
    seed_directory()
    submitted(client)
    advance_to_last_day_before_processing_due()
    client.post("/api/sim/timers/run", headers=HEAD)
    with get_engine().begin() as c:
        c.execute(text("UPDATE dl.alert SET raised_at = raised_at - :d WHERE level = 0"), {"d": timedelta(days=10)})
    alerts = items(client)["alerts"]
    assert alerts["outcome"] == "FAIL" and alerts["result"]["early"] >= 1
