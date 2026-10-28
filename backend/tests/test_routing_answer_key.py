"""The workflow owner's routing answer key, transcribed from the frozen CSV, is what the scorecard evaluates."""
import csv
import json

from conftest import headers
from generator.cases import routing_answer_key as key

BUREAU = headers("BUREAU_OFFICER")


def test_routing_json_is_the_frozen_csv_and_labels_its_verification():
    assert key.main(["--check"]) == 0
    data = json.loads(key.OUTPUT.read_text(encoding="utf-8"))
    rows = list(csv.DictReader(key.CSV_PATH.read_text(encoding="utf-8").splitlines()))
    assert [c["category"] for c in data["cases"]] == [r["route_id"] for r in rows] and len(rows) == 24
    assert data["source_status"] == "VERIFIED_PER_ROW" and data["assumption_ref"] is None
    assert "expected_routes.csv" in data["source"] and "Table 2.3" in data["source"]
    table = [c for c in data["cases"] if c["source_table"] == "TABLE_2_3"]
    assert len(table) == 21 and all(c["source_verification"] == "VERIFIED_APH_P46" and c["assumption_ref"] is None
                                    for c in table)
    only_evc = {c["category"]: c for c in data["cases"] if c["category"] in {"RANDOM_INSPECTION", "COMPLAINT_EVC"}}
    assert {k: (c["expected_stages"], c["as_applicable_stages"], c["evc"]) for k, c in only_evc.items()} == {
        "RANDOM_INSPECTION": (["EVC", "SHC"], ["SHC"], True), "COMPLAINT_EVC": (["EVC", "SHC"], ["SHC"], True)}
    assert only_evc["RANDOM_INSPECTION"]["source_verification"] == "VERIFIED_APH_P31"
    assert only_evc["COMPLAINT_EVC"]["source_verification"] == "VERIFIED_APH_P89"
    new_institution = next(c for c in data["cases"] if c["category"] == "NEW_INSTITUTION")
    assert new_institution["expected_stages"] == ["SCRUTINY", "EVC", "SHC", "EC", "COUNCIL"]
    assert new_institution["as_applicable_stages"] == ["SHC"] and new_institution["source_table"] == "CHAPTER_I"
    assert new_institution["assumption_ref"] == "NEW_INSTITUTION_SHC_UNCONFIRMED"


def test_scorecard_routing_line_is_evaluated_from_the_default_answer_keys(client, monkeypatch):
    monkeypatch.delenv("ANSWER_KEYS_DIR", raising=False)
    with client:
        items = {i["key"]: i for i in client.get("/api/analytics/scorecard", headers=BUREAU).json()["items"]}
    routing = items["routing"]
    assert routing["kind"] == "EVALUATED_ON_ANSWER_KEY" and routing["outcome"] == "PASS", routing
    assert routing["result"]["cases"] == 24 and routing["result"]["correct"] == 24 and routing["result"]["mismatches"] == []
    assert "NEW_INSTITUTION_SHC_UNCONFIRMED" in routing["source"] and "p.46" in routing["source"]
