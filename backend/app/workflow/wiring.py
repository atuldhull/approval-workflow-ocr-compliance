from app.platform.registry import provide
from app.platform.settings import settings
from app.workflow import appeal, facts, guards
from app.workflow.registry import RulesetRegistry
from contracts.ports import DeadlineExpiryPort, RulesetPort


def wire() -> None:
    provide(RulesetPort, RulesetRegistry(settings.rulesets_dir, settings.default_ruleset, settings.demo_mode))
    # Guard facts in the running app come only from persisted records and ports, never the request payload.
    guards.register_default_fact_loader(facts.load)
    # The deadline worker runs the workflow's expiry actions (APPEAL_7D lapses close the appeal window).
    provide(DeadlineExpiryPort, appeal.Expiry())
