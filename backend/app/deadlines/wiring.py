from app.deadlines.clock import SystemClock
from app.deadlines.rules import RuleParser
from app.deadlines.service import DeadlineEngine
from app.platform.registry import provide
from contracts.ports import ClockPort, DeadlinePort, DeadlineRuleParserPort

clock = SystemClock()


def wire() -> None:
    provide(ClockPort, clock)
    provide(DeadlineRuleParserPort, RuleParser())
    provide(DeadlinePort, DeadlineEngine())
