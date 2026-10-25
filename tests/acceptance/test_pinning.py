from uuid import UUID

import pytest
from sqlalchemy import select

from app.platform.db import new_session
from app.platform.registry import provide
from app.workflow import engine
from app.workflow.commands import Command, Options
from app.workflow.loader import sync_rulesets
from app.workflow.models import CaseState, Ruleset
from app.workflow.registry import RulesetRegistry
from contracts.enums import Role
from contracts.errors import Forbidden, ValidationFailed
from contracts.ports import RulesetPort
from contracts.types import Principal
from acceptance.route_support import DEMO_REF, R1, R3, ROOT
from acceptance.runtime_support import SUNRISE, headers, snapshot, submit_case


def load_demo(env):
    registry = RulesetRegistry(ROOT / "rulesets", R3, demo_mode=True)
    with new_session() as session, session.begin():
        result = sync_rulesets(session, registry)
    assert result.inserted == (R3,) and result.unchanged == (R1,)
    provide(RulesetPort, registry)
    env.registry = registry
    return registry


def test_loading_r3_preserves_existing_case_pin_and_state(acceptance_env):
    env = acceptance_env
    old_id = submit_case(env)
    before = snapshot(old_id)
    assert before[0] == R1
    with new_session() as session:
        assert session.scalar(select(Ruleset).where(Ruleset.key == R3)) is None
    registry = load_demo(env)
    assert snapshot(old_id) == before
    assert registry.get(R1).roles["evc_constituted_by"] == "REGIONAL_OFFICER"
    assert registry.get(R3).roles["evc_constituted_by"] == "COUNCIL"
    assert "SIMULATION" in registry.get(R3).banner
    # A real subsequent command still uses the old persisted pin, not the new default.
    result = engine.execute(Command(application_id=UUID(old_id), action="advance", expected_version=before[4],
        actor=Principal(DEMO_REF, Role.BUREAU_OFFICER, institution_id=SUNRISE)))
    assert result.ruleset_key == R1 and snapshot(old_id)[0] == R1


def test_new_demo_case_uses_selected_r3_default_without_repinning_old_case(acceptance_env):
    env = acceptance_env
    old_id = submit_case(env)
    before = snapshot(old_id)
    load_demo(env)
    new_id = submit_case(env)
    assert snapshot(old_id) == before
    assert snapshot(new_id)[0] == R3
    old = env.client.get(f"/api/cases/{old_id}", headers=headers("INSTITUTION", SUNRISE))
    new = env.client.get(f"/api/cases/{new_id}", headers=headers("INSTITUTION", SUNRISE))
    assert old.status_code == new.status_code == 200
    assert old.json()["ruleset_key"] == R1 and new.json()["ruleset_key"] == R3
    assert new.json()["assumption_status"] == "DEMO_ASSUMPTION"


def test_r3_refused_outside_demo_by_registry_loader_http_and_engine(acceptance_env, monkeypatch):
    env = acceptance_env
    load_demo(env)
    demo_id = submit_case(env)
    before = snapshot(demo_id)
    disabled = RulesetRegistry(ROOT / "rulesets", R1, demo_mode=False)
    with pytest.raises(Forbidden):
        disabled.get(R3)
    with pytest.raises(ValidationFailed, match="demo-only outside demo mode"):
        with new_session() as session, session.begin():
            sync_rulesets(session, RulesetRegistry(ROOT / "rulesets", R3, demo_mode=False))
    provide(RulesetPort, disabled)
    assert env.client.get(f"/api/rulesets/{R3}", headers=headers("INSTITUTION", SUNRISE)).status_code == 403
    monkeypatch.setattr(engine, "options", lambda: Options(demo_mode=False))
    with pytest.raises(Forbidden, match="DEMO_RULESET_REFUSED"):
        engine.execute(Command(application_id=UUID(demo_id), action="advance", expected_version=before[4],
            actor=Principal(DEMO_REF, Role.BUREAU_OFFICER, institution_id=SUNRISE)))
    assert snapshot(demo_id) == before
    with new_session() as session:
        assert session.get(CaseState, UUID(demo_id)).ruleset_key == R3
    assert env.client.get("/api/ledger/verify", headers=headers("AUDITOR")).json()["ok"]
