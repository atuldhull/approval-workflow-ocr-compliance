"""Real P1/P3/P2 runtime with explicitly fictional missing guard/compliance data."""
from types import SimpleNamespace

import pytest

from app.platform import registry as bindings
from app.platform.db import new_session
from app.platform.registry import provide
from app.workflow import engine, guards
from app.workflow.commands import GuardFacts, Options
from app.workflow.loader import sync_rulesets
from app.workflow.registry import RulesetRegistry
from contracts.fakes import FakeCompliance
from contracts.ports import CompliancePort, RulesetPort
from acceptance.route_support import DECISION_REF, R1, ROOT


@pytest.fixture
def acceptance_env(client, monkeypatch):
    # Isolate test-local registrations while keeping real auth/clock/deadline/ledger ports.
    monkeypatch.setattr(bindings, "_impls", bindings._impls.copy())
    initial = RulesetRegistry(ROOT / "rulesets", R1, demo_mode=False)
    with new_session() as session, session.begin():
        loaded = sync_rulesets(session, initial)
        assert loaded.inserted == (R1,)
    registry = RulesetRegistry(ROOT / "rulesets", R1, demo_mode=True)
    provide(RulesetPort, registry)
    compliance = FakeCompliance()
    provide(CompliancePort, compliance)
    env = SimpleNamespace(client=client, registry=registry, compliance=compliance, shc=True, letter=None)
    monkeypatch.setattr(engine, "options", lambda: Options(demo_mode=True, enable_letter_issuance=True))

    def facts(uow, case, command):
        return GuardFacts(open_item_count=0, has_assignment=True, reason_codes=frozenset({"DEMO_ACCEPTANCE"}),
            decision_refs=frozenset({DECISION_REF}), confirmed_letter=env.letter,
            applicability={"SHC": env.shc}, live_clock_rules=frozenset({"AICTE_PROCESSING"}),
            second_approval_required=False)

    monkeypatch.setattr(guards, "_fact_loader", facts)
    yield env
