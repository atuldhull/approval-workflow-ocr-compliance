"""Validate the P1 YAML expert policy without importing EVC internals."""
from contracts.errors import ValidationFailed

REGION_RULES = {"SAME_REGION", "ANY_REGION", "OTHER_REGION"}
COI_PAIRS = {key: key for key in ("INSTITUTION_LINK", "PRIOR_ENGAGEMENT", "RECUSAL")}


def validate_config(raw: dict) -> dict:
    policy = raw.get("expert_pool")
    if policy is None:
        return {}
    if not isinstance(policy, dict) or set(policy) != {
        "region_rule", "slot_parts", "coi_reasons", "source_status", "assumption_code"
    }:
        raise ValidationFailed("EXPERT_POOL_CONFIG_INVALID")
    if (not isinstance(policy["region_rule"], str) or policy["region_rule"] not in REGION_RULES
        or policy["slot_parts"] != ["AM", "PM"] or policy["coi_reasons"] != COI_PAIRS
        or policy["source_status"] != "DEMO_ASSUMPTION"
        or policy["assumption_code"] != "EXPERT_POLICY_UNCONFIRMED"):
        raise ValidationFailed("EXPERT_POOL_CONFIG_INVALID")
    return {**policy, "slot_parts": list(policy["slot_parts"]), "coi_reasons": dict(COI_PAIRS)}
