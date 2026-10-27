"""DEMO scheduling policy validation; P2 due dates and clocks are unchanged."""
from contracts.errors import ValidationFailed

REQUIRED = {"capacity_unit", "allow_late", "source_status", "assumption_code"}
# DEMO ASSUMPTION defaults when a pinned ruleset predates these keys (decided 28 October 2026).
OPTIONAL = {"expert_daily_cap": 1, "cpsat_candidate_slots": 12}
LIMITS = {"expert_daily_cap": (1, 10), "cpsat_candidate_slots": (1, 200)}


def validate_scheduler(raw: dict) -> dict:
    if (not isinstance(raw, dict) or not REQUIRED <= set(raw) <= REQUIRED | set(OPTIONAL)
        or raw["capacity_unit"] != "PANELS" or type(raw["allow_late"]) is not bool
        or raw["source_status"] != "DEMO_ASSUMPTION" or raw["assumption_code"] != "EDF_PLANNING_UNCONFIRMED"):
        raise ValidationFailed("SCHEDULER_POLICY_INVALID")
    result = {**OPTIONAL, **raw}
    for key, (low, high) in LIMITS.items():
        if type(result[key]) is not int or not low <= result[key] <= high:
            raise ValidationFailed("SCHEDULER_POLICY_INVALID")
    return result
