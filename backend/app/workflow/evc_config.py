"""Pinned workflow-owned EVC metadata validation; never imports EVC/P2 internals."""
from contracts.errors import ValidationFailed


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
    rule = rules.get(config["rule_id"])
    value = lambda obj, key: obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)
    duration = value(rule, "duration")
    if (value(rule, "clock_kind") != "INTERNAL" or value(rule, "clock_owner") != "COMMITTEE"
        or value(duration, "unit") != "calendar_days" or type(value(duration, "value")) is not int
        or value(duration, "value") <= 0):
        raise ValidationFailed("EVC_DEADLINE_CONFIG_INVALID")
    source = value(rule, "source_status") or (value(rule, "source") or {}).get("status")
    if source != "demo_assumption":
        raise ValidationFailed("EVC_DURATION_SOURCE_INVALID")
    return dict(config)
