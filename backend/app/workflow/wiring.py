from app.platform.registry import provide
from app.platform.settings import settings
from app.workflow.registry import RulesetRegistry
from contracts.ports import RulesetPort


def wire() -> None:
    provide(RulesetPort, RulesetRegistry(settings.rulesets_dir, settings.default_ruleset, settings.demo_mode))
