from uuid import uuid4

import pytest
from sqlalchemy import text

from app.platform.db import get_engine
from app.platform.ledger import Ledger
from conftest import SUNRISE, headers
from contracts.errors import ValidationFailed
from contracts.types import EventIn

INST = headers("INSTITUTION", SUNRISE)
AUDITOR = headers("AUDITOR")


def submit_one(client):
    app = client.post("/api/applications", headers=INST,
                      json={"institution_id": str(SUNRISE), "category": "NEW_PROGRAMME", "academic_year": "2027-28"})
    client.post(f"/api/applications/{app.json()['id']}/submit", headers=INST)


def test_unknown_event_types_are_rejected():
    with pytest.raises(ValidationFailed, match="no contract schema"):
        Ledger().append(None, EventIn("application", uuid4(), "wf.something_new", {}))
    with pytest.raises(ValidationFailed, match="known prefix"):
        Ledger().append(None, EventIn("application", uuid4(), "misc.thing", {}))


def test_payloads_must_match_their_schema():
    payload = {"application_id": str(uuid4()), "institution_id": str(uuid4()), "category": "NEW_PROGRAMME",
               "academic_year": "2027-28", "remarks": "free text is not allowed here"}
    with pytest.raises(ValidationFailed, match="Additional properties"):
        Ledger().append(None, EventIn("application", uuid4(), "wf.application_created", payload))


def test_untouched_chain_verifies(client):
    submit_one(client)
    r = client.get("/api/ledger/verify", headers=AUDITOR).json()
    assert r == {"ok": True, "checked": 3, "first_bad_seq": None, "detail": None}


def test_editing_an_event_is_detected(client):
    submit_one(client)
    with get_engine().begin() as c:
        c.execute(text("UPDATE plat.domain_event SET payload = jsonb_set(payload, '{category}', '\"MERGER\"') "
                       "WHERE seq = 2"))
    r = client.get("/api/ledger/verify", headers=AUDITOR).json()
    assert r["ok"] is False and r["first_bad_seq"] == 2


def test_deleting_an_event_is_detected(client):
    submit_one(client)
    with get_engine().begin() as c:
        c.execute(text("DELETE FROM plat.ledger_entry WHERE seq = 1"))
        c.execute(text("DELETE FROM plat.domain_event WHERE seq = 1"))
    r = client.get("/api/ledger/verify", headers=AUDITOR).json()
    assert r["ok"] is False and r["first_bad_seq"] == 2


def test_institutions_cannot_verify_the_ledger(client):
    assert client.get("/api/ledger/verify", headers=INST).status_code == 403
