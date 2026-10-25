"""Fictional setup for older tests whose subject is not the item-write API."""
from uuid import UUID, NAMESPACE_URL, uuid5

from sqlalchemy import func, select

from app.intake.models import Application, ApplicationItem
from app.intake.rules import plan
from app.platform.db import new_session
from app.platform.registry import port
from app.workflow.models import Ruleset
from contracts.ports import RulesetPort


def ensure_intake_rules(client):
    with new_session() as session:
        loaded = session.scalar(select(func.count()).select_from(Ruleset))
    if not loaded:
        with client:
            pass  # production startup performs the actual immutable import


def provide_fixture_items(application_id):
    application_id = UUID(str(application_id))
    with new_session() as session, session.begin():
        app = session.get(Application, application_id)
        config = plan(session, app.category, app.ruleset_rev or port(RulesetPort).default_key()).checklist
        for item in config["items"]:
            if item["mandatory"] and session.get(ApplicationItem, (application_id, item["item_key"])) is None:
                session.add(ApplicationItem(application_id=application_id, item_key=item["item_key"], state="PROVIDED",
                    document_ref=uuid5(NAMESPACE_URL, f"DEMO:test-document:{application_id}:{item['item_key']}")))
