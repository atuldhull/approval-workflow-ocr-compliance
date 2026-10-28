"""Pinned workflow-owned EVC metadata validation; never imports EVC/P2 internals."""
from contracts.errors import ValidationFailed


def _check_rule(rules: dict, rule_id) -> None:
    rule = rules.get(rule_id) if isinstance(rule_id, str) else None
    value = lambda obj, key: obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)
    duration = value(rule, "duration")
    if (value(rule, "clock_kind") != "INTERNAL" or value(rule, "clock_owner") != "COMMITTEE"
        or value(duration, "unit") != "calendar_days" or type(value(duration, "value")) is not int
        or value(duration, "value") <= 0):
        raise ValidationFailed("EVC_DEADLINE_CONFIG_INVALID")
    source = value(rule, "source_status") or (value(rule, "source") or {}).get("status")
    if source != "demo_assumption":
        raise ValidationFailed("EVC_DURATION_SOURCE_INVALID")


def validate_config(raw: dict, rules: dict) -> dict | None:
    config = raw.get("evc")
    if config is None:
        if any(any((stage if isinstance(stage, str) else stage.get("stage")) == "EVC" for stage in route.get("stages", []))
               for route in raw.get("routes", {}).values()):
            raise ValidationFailed("EVC_CONFIG_UNAVAILABLE")
        return None
    if not isinstance(config, dict) or not isinstance(config.get("rule_id"), str):
        raise ValidationFailed("EVC_CONFIG_INVALID")
    if config != {"rule_id": config.get("rule_id"), "source_status": "DEMO_ASSUMPTION",
                  "assumption_code": "EVC_DURATION_UNCONFIRMED"}:
        raise ValidationFailed("EVC_CONFIG_INVALID")
    _check_rule(rules, config["rule_id"])
    result = dict(config)
    # A route may set its own EVC timeline (evc_rule_id); the same demo-assumption checks apply to its rule.
    route_rules = {}
    for category, route in sorted(raw.get("routes", {}).items()):
        if not isinstance(route, dict) or "evc_rule_id" not in route:
            continue
        if not any((stage if isinstance(stage, str) else stage.get("stage")) == "EVC" for stage in route.get("stages", [])):
            raise ValidationFailed("EVC_ROUTE_RULE_WITHOUT_EVC")
        _check_rule(rules, route["evc_rule_id"])
        route_rules[category] = route["evc_rule_id"]
    if route_rules:
        result["route_rules"] = route_rules
    return result


def rule_for(config: dict, route_id: str) -> str:
    """The EVC deadline rule of a case on this route: the route's own rule, else the ruleset default."""
    return (config.get("route_rules") or {}).get(route_id, config["rule_id"])
