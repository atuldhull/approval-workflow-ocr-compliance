"""The alert ladder from deadlines.yaml: who is told about a deadline, when, and who comes next.

Every value is configuration. The APH sets no reminder or escalation schedule, so the shipped ladder is a labelled
demo assumption until the team confirms one.
"""
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.platform.providers import TEMPLATES
from contracts.enums import ClockOwner, Role
from contracts.errors import ValidationFailed

OWNER = "owner"  # the role responsible for the clock, from owner_roles
CHANNELS = frozenset({"in_app", "email", "sms"})
ADDRESSABLE = frozenset(Role) - {Role.SYSTEM, Role.AUDITOR}
MAX_LEVELS = 10
_OFFSET = re.compile(r"^([+-]?)(\d{1,4})([dh])$")


def parse_offset(value: object, context: str) -> timedelta:
    """'-2d', '0d', '+12h': relative to the deadline's due instant."""
    m = _OFFSET.match(value) if isinstance(value, str) else None
    if m is None:
        raise ValidationFailed(f"{context}: offset must look like -2d, 0d or 12h")
    sign, amount, unit = m.groups()
    delta = timedelta(days=int(amount)) if unit == "d" else timedelta(hours=int(amount))
    return -delta if sign == "-" else delta


@dataclass(frozen=True)
class LadderStep:
    level: int
    to: str          # OWNER or a Role value
    offset: timedelta
    template: str


@dataclass(frozen=True)
class AlertConfig:
    source_status: str
    channels: tuple[str, ...]
    owner_roles: dict[str, Role]
    ladders: dict[str, tuple[LadderStep, ...]]
    default_ladder: str
    retry_after: timedelta

    def ladder(self, rule) -> tuple[LadderStep, ...]:
        name = (getattr(rule, "extra", None) or {}).get("alert_ladder", self.default_ladder)
        return () if name == "none" else self.ladders[name]

    def role_for(self, step: LadderStep, clock_owner: str) -> Role:
        return self.owner_roles[str(clock_owner)] if step.to == OWNER else Role(step.to)

    @staticmethod
    def fire_at(step: LadderStep, due_at: datetime) -> datetime:
        return due_at + step.offset


def _parse_ladder(name: str, raw: object) -> tuple[LadderStep, ...]:
    if not isinstance(raw, list) or not raw or len(raw) > MAX_LEVELS:
        raise ValidationFailed(f"alert ladder {name} needs 1 to {MAX_LEVELS} steps")
    steps: list[LadderStep] = []
    for i, item in enumerate(raw):
        ctx = f"alert ladder {name} step {i}"
        if not isinstance(item, dict) or item.get("level") != i:
            raise ValidationFailed(f"{ctx}: steps need level numbers 0, 1, 2 ... in order")
        to = item.get("to")
        if to != OWNER and to not in {r.value for r in ADDRESSABLE}:
            raise ValidationFailed(f"{ctx}: 'to' must be '{OWNER}' or one of {sorted(r.value for r in ADDRESSABLE)}")
        if item.get("template") not in TEMPLATES:
            raise ValidationFailed(f"{ctx}: template must be one of {sorted(TEMPLATES)}")
        step = LadderStep(i, to, parse_offset(item.get("at"), ctx), item["template"])
        if steps and step.offset <= steps[-1].offset:
            raise ValidationFailed(f"{ctx}: each level must fire after the previous one")
        steps.append(step)
    return tuple(steps)


def parse_alert_config(raw: object) -> AlertConfig | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValidationFailed("alerts must be an object")
    source = raw.get("source") or {}
    if not isinstance(source, dict) or source.get("status") not in {"verified", "demo_assumption"}:
        raise ValidationFailed("alerts.source.status must be verified or demo_assumption")
    channels = raw.get("channels")
    if not isinstance(channels, list) or not channels or not set(channels) <= CHANNELS or len(set(channels)) != len(channels):
        raise ValidationFailed(f"alerts.channels must be distinct values from {sorted(CHANNELS)}")
    owners = raw.get("owner_roles")
    if not isinstance(owners, dict) or set(owners) != {o.value for o in ClockOwner}:
        raise ValidationFailed(f"alerts.owner_roles must map every clock owner {sorted(o.value for o in ClockOwner)}")
    try:
        owner_roles = {k: Role(v) for k, v in owners.items()}
    except ValueError:
        raise ValidationFailed("alerts.owner_roles values must be roles") from None
    if not set(owner_roles.values()) <= ADDRESSABLE:
        raise ValidationFailed("alerts.owner_roles cannot address SYSTEM or AUDITOR")
    ladders_raw = raw.get("ladders")
    if not isinstance(ladders_raw, dict) or not ladders_raw or "none" in ladders_raw:
        raise ValidationFailed("alerts.ladders must name one or more ladders ('none' is reserved)")
    ladders = {str(name): _parse_ladder(str(name), steps) for name, steps in ladders_raw.items()}
    default = raw.get("default_ladder")
    if default not in ladders:
        raise ValidationFailed("alerts.default_ladder must name one of alerts.ladders")
    retry = raw.get("retry_after_minutes", 15)
    if type(retry) is not int or not 1 <= retry <= 1440:
        raise ValidationFailed("alerts.retry_after_minutes must be 1 to 1440")
    return AlertConfig(source["status"], tuple(channels), owner_roles, ladders, default, timedelta(minutes=retry))


def check_rule_ladders(rules: dict[str, Any], config: AlertConfig | None) -> None:
    for rule in rules.values():
        name = rule.extra.get("alert_ladder")
        if name is None or name == "none":
            continue
        if config is None or name not in config.ladders:
            raise ValidationFailed(f"{rule.id}: alert_ladder {name} is not configured under alerts.ladders")
