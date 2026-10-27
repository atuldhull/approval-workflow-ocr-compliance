"""HTTP and state helpers for fictional route acceptance scenarios."""
from uuid import UUID

from app.platform.db import new_session
from app.platform.registry import port
from app.workflow.commands import LetterPayload
from app.workflow.models import CaseState
from contracts.ports import ClockPort
from acceptance.route_support import DEMO_REF

SUNRISE = UUID("00000000-0000-4000-8000-000000000001")


def headers(role, institution=None):
    values = {"X-Demo-User": str(DEMO_REF), "X-Demo-Role": role}
    if institution is not None:
        values["X-Demo-Institution"] = str(institution)
    return values


def create_ready(env, category="NEW_INSTITUTION") -> str:
    auth = headers("INSTITUTION", SUNRISE)
    response = env.client.post("/api/applications", headers=auth, json={
        "institution_id": str(SUNRISE), "category": category, "academic_year": "2027-28"})
    assert response.status_code == 201, response.text
    application_id = response.json()["id"]
    response = env.client.post(f"/api/applications/{application_id}/items", headers=auth, json={
        "items": [{"item_key": "DEMO_CORE_REFERENCE", "document_ref": str(DEMO_REF)}]})
    assert response.status_code == 200, response.text
    return application_id


def submit_route(env, category):
    application_id = create_ready(env, category)
    response = env.client.post(f"/api/applications/{application_id}/submit",
        headers=headers("INSTITUTION", SUNRISE), json={"dsc_present": True})
    assert response.status_code == 200, response.text
    app = response.json()
    # Adopt the legacy intake projection for the engine, without replaying submission.
    with new_session() as session, session.begin():
        session.add(CaseState(application_id=UUID(application_id), route_id=app["route_id"],
            ruleset_key=app["ruleset_key"], current_stage=app["current_stage"], status=app["status"]))
    return application_id, app


def submit_case(env, category="NEW_INSTITUTION") -> str:
    application_id = create_ready(env, category)
    response = env.client.post(f"/api/cases/{application_id}/actions", headers=headers("INSTITUTION", SUNRISE),
        json={"action": "submit", "expected_version": 1, "payload": {"dsc_present": True}})
    assert response.status_code == 200, response.text
    return application_id


def letter_for(env, kind="LOA") -> LetterPayload:
    env.letter = LetterPayload(type=kind, academic_year="2027-28", issue_date=port(ClockPort).now().date(),
                              issue_date_source="PORTAL_EVENT", lists_deficiencies=False)
    return env.letter


def snapshot(application_id):
    with new_session() as session:
        row = session.get(CaseState, UUID(str(application_id)))
        return row.ruleset_key, row.route_id, row.current_stage, row.status, row.version
