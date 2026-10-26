"""Loads, validates and pins versioned rulesets from rulesets/<ruleset>/<revision>/."""
from pathlib import Path
from typing import Any

import yaml

from app.platform.registry import port
from app.workflow.grammar import validate_workflow
from app.workflow.checklists import Citation, validate_checklists
from app.workflow.deficiency_config import validate_config
from pydantic import ValidationError
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
    if not isinstance(raw, dict) or not raw:
        raise ValidationFailed("routes must be a nonempty mapping")
    for category, spec in raw.items():
        if not isinstance(spec, dict) or not isinstance(spec.get("stages"), list):
            raise ValidationFailed(f"{category}: stages must be a list")
        stages: list[RouteStage] = []
        for item in spec.get("stages", []):
            if not isinstance(item, (str, dict)) or (isinstance(item, dict) and set(item) - {"stage", "when"}):
                raise ValidationFailed(f"{category}: malformed stage item")
            name, when = (item, "always") if isinstance(item, str) else (item.get("stage"), item.get("when", "always"))
            if not isinstance(name, str) or name not in Stage.__members__:
                problems.append(f"{category}: unknown stage {name}")
                continue
            if not isinstance(when, str) or when not in WHEN_VALUES:
                problems.append(f"{category}: unknown condition {when}")
            stages.append(RouteStage(Stage(name), when))
        if not stages:
            problems.append(f"{category}: no stages")
        names = [s.stage for s in stages]
        if (Stage.EVC in names) != (Stage.SHC in names):
            problems.append(f"{category}: Table 2.3 pairs SHC with EVC")
        if len(names) != len(set(names)):
            problems.append(f"{category}: duplicate stage")
        if any(s.stage == Stage.SHC and s.when != "as_applicable" for s in stages):
            problems.append(f"{category}: SHC must be as_applicable")
        if any(s.stage == Stage.EVC and s.when != "always" for s in stages):
            problems.append(f"{category}: EVC must be always")
        if Stage.EVC in names and Stage.SHC in names and names.index(Stage.SHC) < names.index(Stage.EVC):
            problems.append(f"{category}: SHC must follow EVC")
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

    def intake_definitions(self, key: str) -> dict:
        """Workflow-local loader capability; not an addition to shared RulesetPort."""
        name, revision = split_key(key)
        folder = self.root / name / revision
        overlay = folder / "overlay.yaml"
        if overlay.exists():
            return self.intake_definitions(_read(overlay)["extends"])
        path = folder / "checklists.yaml"
        routes_raw = _read(folder / "routes.yaml")
        if routes_raw.get("intake") is not None:
            if routes_raw["intake"] != {"checklist_file": "checklists.yaml"} or not path.exists():
                raise ValidationFailed("intake checklist file is missing or invalid")
        if not path.exists():
            return {}
        routes = routes_raw["routes"]
        result = validate_checklists(_read(path), set(routes))
        for category, route in routes.items():
            try:
                Citation.model_validate(route.get("clause_citation"))
            except ValidationError:
                raise ValidationFailed(f"{category}: intake route citation is missing or invalid") from None
        return result

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
        clocks = routes_raw.get("clocks", {})
        if not isinstance(clocks, dict) or not isinstance(clocks.get("on_submit", []), list):
            raise ValidationFailed(f"{key}: clocks.on_submit must be a list")
        on_submit = tuple(clocks.get("on_submit", []))
        if any(not isinstance(r, str) for r in on_submit):
            raise ValidationFailed(f"{key}: clocks.on_submit must contain rule names")
        missing = [r for r in on_submit if r not in rules]
        if missing:
            raise ValidationFailed(f"{key}: clocks.on_submit refers to unknown deadline rules {missing}")
        routes = parse_routes(routes_raw.get("routes", {}))
        intake = self.intake_definitions(key)
        if intake:
            submits = [t for t in routes_raw.get("templates", {}).values() if t.get("action") == "submit"]
            if not submits or any(not {"checklist_complete", "dsc_required"} <= set(t.get("guards", [])) for t in submits):
                raise ValidationFailed("intake submit requires checklist_complete and dsc_required guards")
        validate_workflow(routes_raw, routes, rules)
        validate_config(routes_raw, rules)
        return RuleSet(
            key=key, ruleset=ruleset, revision=revision, status=routes_raw.get("status", "unknown"),
            routes=routes, deadline_rules=rules,
            clocks_on_submit=on_submit, roles=routes_raw.get("roles", {}), banner=routes_raw.get("banner"),
        )


def _read(path: Path) -> dict[str, Any]:
    class UniqueKeyLoader(yaml.SafeLoader):
        pass

    def mapping(loader, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in result:
                raise ValidationFailed(f"{path.name}: non-string or duplicate mapping key {key}")
            result[key] = loader.construct_object(value_node, deep=deep)
        return result

    UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    try:
        with path.open(encoding="utf-8") as f:
            raw = yaml.load(f, Loader=UniqueKeyLoader)
    except (yaml.YAMLError, OSError, RecursionError) as exc:
        raise ValidationFailed(f"cannot read ruleset {path.name}: {exc}") from None
    if not isinstance(raw, dict):
        raise ValidationFailed(f"{path.name}: expected mapping")
    return raw
