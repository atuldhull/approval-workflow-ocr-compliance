"""DEMO scheduling policy validation; P2 due dates and clocks are unchanged."""
from contracts.errors import ValidationFailed


def validate_scheduler(raw: dict) -> dict:
    if (not isinstance(raw, dict) or set(raw) != {"capacity_unit", "allow_late", "source_status", "assumption_code"}
        or raw["capacity_unit"] != "PANELS" or type(raw["allow_late"]) is not bool
        or raw["source_status"] != "DEMO_ASSUMPTION" or raw["assumption_code"] != "EDF_PLANNING_UNCONFIRMED"):
        raise ValidationFailed("SCHEDULER_POLICY_INVALID")
    return dict(raw)
