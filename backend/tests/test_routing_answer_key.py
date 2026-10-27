"""The workflow owner's routing answer key, transcribed from the frozen CSV, is what the scorecard evaluates."""
import csv
import json

from conftest import headers
from generator.cases import routing_answer_key as key

BUREAU = headers("BUREAU_OFFICER")


def test_routing_json_is_the_frozen_csv_and_labelled_unverified():
    assert key.main(["--check"]) == 0
    data = json.loads(key.OUTPUT.read_text(encoding="utf-8"))
    rows = list(csv.DictReader(key.CSV_PATH.read_text(encoding="utf-8").splitlines()))
    assert [c["category"] for c in data["cases"]] == [r["route_id"] for r in rows] and len(rows) == 22
    assert data["source_verification"] == "PRIMARY_SOURCE_UNAVAILABLE" and data["assumption_ref"] == "ACCEPTANCE_SOURCE_UNVERIFIED"
    assert "expected_routes.csv" in data["source"] and "Table 2.3" in data["source"]
    new_institution = next(c for c in data["cases"] if c["category"] == "NEW_INSTITUTION")
    assert new_institution["expected_stages"] == ["SCRUTINY", "EVC", "SHC", "EC", "COUNCIL"]
    assert new_institution["as_applicable_stages"] == ["SHC"] and new_institution["source_table"] == "CHAPTER_I"


def test_scorecard_routing_line_is_evaluated_from_the_default_answer_keys(client, monkeypatch):
    monkeypatch.delenv("ANSWER_KEYS_DIR", raising=False)
    with client:
        items = {i["key"]: i for i in client.get("/api/analytics/scorecard", headers=BUREAU).json()["items"]}
    routing = items["routing"]
    assert routing["kind"] == "EVALUATED_ON_ANSWER_KEY" and routing["outcome"] == "PASS", routing
    assert routing["result"]["cases"] == 22 and routing["result"]["correct"] == 22 and routing["result"]["mismatches"] == []
    assert "PRIMARY_SOURCE_UNAVAILABLE" in routing["source"]
