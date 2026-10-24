"""Loads, validates and pins versioned rulesets from rulesets/<ruleset>/<revision>/."""
from pathlib import Path
from typing import Any

import yaml

from app.platform.registry import port
from contracts.enums import Stage
from contracts.errors import Forbidden, NotFound, ValidationFailed
from contracts.ports import DeadlineRuleParserPort
from contracts.types import Route, RouteStage, RuleSet

WHEN_VALUES = {"always", "as_applicable"}


def split_key(key: str) -> tuple[str, str]:
    ruleset, sep, revision = key.partition("@")
    if not sep or not ruleset or not revision:
        raise ValidationFailed(f"ruleset key must look like 'aph-2024-27@r1': {key}")
    return ruleset, revision


def parse_routes(raw: dict[str, Any]) -> dict[str, Route]:
    """Static validation: known stages only, and SHC is optional exactly where an EVC is required."""
    routes: dict[str, Route] = {}
    problems: list[str] = []
    for category, spec in (raw or {}).items():
        stages: list[RouteStage] = []
        for item in spec.get("stages", []):
            name, when = (item, "always") if isinstance(item, str) else (item.get("stage"), item.get("when", "always"))
            if name not in Stage.__members__:
                problems.append(f"{category}: unknown stage {name}")
                continue
            if when not in WHEN_VALUES:
                problems.append(f"{category}: unknown condition {when}")
            stages.append(RouteStage(Stage(name), when))
        if not stages:
            problems.append(f"{category}: no stages")
        names = [s.stage for s in stages]
        if (Stage.EVC in names) != (Stage.SHC in names):
            problems.append(f"{category}: Table 2.3 pairs SHC with EVC")
        routes[category] = Route(category, spec.get("label", category), tuple(stages))
    if problems:
        raise ValidationFailed("; ".join(problems))
    return routes


class RulesetRegistry:
    def __init__(self, root: Path, default_key: str, demo_mode: bool):
        self.root = root
        self._default = default_key
        self.demo_mode = demo_mode
        self._cache: dict[str, RuleSet] = {}

    def default_key(self) -> str:
        return self._default

    def available(self) -> list[str]:
        return sorted(f"{rs.name}@{rev.name}" for rs in self.root.iterdir() if rs.is_dir()
                      for rev in rs.iterdir() if rev.is_dir())

    def get(self, key: str) -> RuleSet:
        if key not in self._cache:
            self._cache[key] = self._load(key)
        return self._cache[key]

    def route_for(self, category: str, key: str) -> Route:
        try:
            return self.get(key).routes[category]
        except KeyError:
            raise ValidationFailed(f"category {category} has no route in {key}") from None

    def _load(self, key: str) -> RuleSet:
        ruleset, revision = split_key(key)
        folder = self.root / ruleset / revision
        if not folder.is_dir():
            raise NotFound(f"ruleset {key} not found")

        overlay = folder / "overlay.yaml"
        if overlay.exists():
            raw = _read(overlay)
            if raw.get("status") == "unverified_demo" and not self.demo_mode:
                raise Forbidden(f"{key} is an unverified demo overlay and is refused outside demo mode")
            base = self.get(raw["extends"])
            return RuleSet(
                key=key, ruleset=ruleset, revision=revision, status=raw.get("status", base.status),
                routes=base.routes, deadline_rules=base.deadline_rules, clocks_on_submit=base.clocks_on_submit,
                roles={**base.roles, **raw.get("roles", {})}, banner=raw.get("banner"),
            )

        routes_raw = _read(folder / "routes.yaml")
        deadlines_raw = _read(folder / "deadlines.yaml") if (folder / "deadlines.yaml").exists() else {}
        rules = port(DeadlineRuleParserPort).parse(deadlines_raw)
        on_submit = tuple(routes_raw.get("clocks", {}).get("on_submit", []))
        missing = [r for r in on_submit if r not in rules]
        if missing:
            raise ValidationFailed(f"{key}: clocks.on_submit refers to unknown deadline rules {missing}")
        return RuleSet(
            key=key, ruleset=ruleset, revision=revision, status=routes_raw.get("status", "unknown"),
            routes=parse_routes(routes_raw.get("routes", {})), deadline_rules=rules,
            clocks_on_submit=on_submit, roles=routes_raw.get("roles", {}), banner=routes_raw.get("banner"),
        )


def _read(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
