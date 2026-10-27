from app.platform.registry import provide
from app.platform.settings import settings
from app.workflow import facts, guards
from app.workflow.registry import RulesetRegistry
from contracts.ports import RulesetPort


def wire() -> None:
    provide(RulesetPort, RulesetRegistry(settings.rulesets_dir, settings.default_ruleset, settings.demo_mode))
    # Guard facts in the running app come only from persisted records and ports, never the request payload.
    guards.register_default_fact_loader(facts.load)
