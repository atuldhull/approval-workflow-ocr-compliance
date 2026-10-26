"""Pinned, coded deficiency configuration; durations remain owned by P2."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from contracts.errors import ValidationFailed

Code = Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]*$")]


class DeficiencyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    item_keys: tuple[Code, ...] = Field(min_length=1)
    reason_codes: tuple[Code, ...] = Field(min_length=1)
    response_rule_id: Code
    source_status: Literal["DEMO_ASSUMPTION"]
    assumption_code: Code


def validate_config(raw: dict, rules: dict) -> dict | None:
    if "deficiency" not in raw:
        return None  # older published configurations never acquire implicit defaults
    try:
        config = DeficiencyConfig.model_validate(raw["deficiency"])
    except ValidationError as exc:
        raise ValidationFailed("INVALID_DEFICIENCY_CONFIG") from exc
    if len(set(config.item_keys)) != len(config.item_keys) or len(set(config.reason_codes)) != len(config.reason_codes):
        raise ValidationFailed("DUPLICATE_DEFICIENCY_CODE")
    rule = rules.get(config.response_rule_id)
    duration = rule.get("duration") if isinstance(rule, dict) else getattr(rule, "duration", None)
    if duration is None:
        raise ValidationFailed("DEFICIENCY_RESPONSE_RULE_MISSING")
    for template in raw.get("templates", {}).values():
        if template.get("action") in {"record_deficiency", "submit_compliance", "start_rescrutiny"}:
            operation = "open" if template["action"] == "record_deficiency" else "close"
            if not any(t.get("op") == operation and t.get("rule_id") == config.response_rule_id for t in template.get("timers", [])):
                raise ValidationFailed("DEFICIENCY_RESPONSE_TIMER_MISMATCH")
    return config.model_dump(mode="json")
