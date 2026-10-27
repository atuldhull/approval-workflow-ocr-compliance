"""Read-only checklist data for the documents screen: per ruleset/category and per application with item state."""
from conftest import NORTHFIELD, SUNRISE, headers

INST = headers("INSTITUTION", SUNRISE)
REF = "b870b346-498b-55b1-945e-c0e24d268980"  # DEMO fixture document reference (UUID5), accepted only in DEMO_MODE
KEY = "aph-2024-27@r1"


def test_ruleset_checklist_by_category(client):
    with client:
        response = client.get(f"/api/rulesets/{KEY}/checklists/NEW_PROGRAMME", headers=headers("AUDITOR"))
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["ruleset_key"] == KEY and body["category"] == "NEW_PROGRAMME"
        assert body["status"] == "DEMO_ASSUMPTION" and body["label"] == "DEMO ASSUMPTION" and body["assumption_refs"]
        assert {"item_key": "DEMO_CORE_REFERENCE", "mandatory": True} in body["items"]
        assert client.get(f"/api/rulesets/{KEY}/checklists/NOT_A_CATEGORY", headers=INST).status_code == 404
        assert client.get("/api/rulesets/missing@r9/checklists/NEW_PROGRAMME", headers=INST).status_code == 404
        assert client.get(f"/api/rulesets/{KEY}/checklists/NEW_PROGRAMME").status_code == 401


def test_application_checklist_state_and_scope(client):
    with client:
        created = client.post("/api/applications", headers=INST, json={"institution_id": str(SUNRISE),
            "category": "NEW_PROGRAMME", "academic_year": "2027-28"}).json()["id"]
        draft = client.get(f"/api/applications/{created}/checklist", headers=INST)
        assert draft.status_code == 200, draft.text
        body = draft.json()
        assert body["pinned"] is False and body["ruleset_key"] == KEY and not body["mandatory_items_complete"]
        assert "DEMO_CORE_REFERENCE" in body["missing_mandatory_item_keys"]
        assert all(item["state"] == "MISSING" for item in body["items"])
        client.post(f"/api/applications/{created}/items", headers=INST,
                    json={"items": [{"item_key": "DEMO_CORE_REFERENCE", "document_ref": REF}]})
        assert client.post(f"/api/applications/{created}/submit", headers=INST, json={"dsc_present": True}).status_code == 200
        after = client.get(f"/api/applications/{created}/checklist", headers=headers("BUREAU_OFFICER")).json()
        assert after["pinned"] is True and after["dsc_present"] is True and after["mandatory_items_complete"]
        core = next(item for item in after["items"] if item["item_key"] == "DEMO_CORE_REFERENCE")
        assert core == {"item_key": "DEMO_CORE_REFERENCE", "mandatory": True, "state": "PROVIDED", "document_ref": REF}
        other = headers("INSTITUTION", NORTHFIELD)
        assert client.get(f"/api/applications/{created}/checklist", headers=other).status_code == 403
        north_ro = {**headers("RO_OFFICER"), "X-Demo-Region": "Northern"}
        assert client.get(f"/api/applications/{created}/checklist", headers=north_ro).status_code == 403
