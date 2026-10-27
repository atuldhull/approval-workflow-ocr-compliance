"""Static validation of DEMO selector YAML; no import of EVC internals."""
import re

from contracts.errors import ValidationFailed

CODE = re.compile(r"^[A-Z][A-Z0-9_]*$")
KEYS = {"version", "panel_size", "required_expertise_tags", "category_expertise_tags",
        "minimum_expertise_matches", "source_status", "assumption_code"}


def validate_selector(raw: dict, categories: set[str] | None = None) -> dict:
    def tags(value):
        return (isinstance(value, list) and bool(value) and all(isinstance(v, str) and CODE.fullmatch(v) for v in value)
                and len(value) == len(set(value)))

    if not isinstance(raw, dict) or set(raw) != KEYS:
        raise ValidationFailed("SELECTOR_POLICY_INVALID")
    mappings = raw["category_expertise_tags"]
    minimum = raw["minimum_expertise_matches"]
    if (raw["version"] != "DEMO_SELECTOR_V1" or type(raw["panel_size"]) is not int or raw["panel_size"] < 1
        or not tags(raw["required_expertise_tags"]) or type(minimum) is not int or minimum < 1
        or not isinstance(mappings, dict) or raw["source_status"] != "DEMO_ASSUMPTION"
        or raw["assumption_code"] != "SELECTOR_POLICY_UNCONFIRMED"):
        raise ValidationFailed("SELECTOR_POLICY_INVALID")
    for category, values in mappings.items():
        if (not isinstance(category, str) or not CODE.fullmatch(category) or not tags(values)
            or (categories is not None and category not in categories)):
            raise ValidationFailed("SELECTOR_CATEGORY_POLICY_INVALID")
    if any(minimum > len(values) for values in [raw["required_expertise_tags"], *mappings.values()]):
        raise ValidationFailed("SELECTOR_MINIMUM_EXPERTISE_INVALID")
    return {**raw, "required_expertise_tags": sorted(raw["required_expertise_tags"]),
            "category_expertise_tags": {key: sorted(mappings[key]) for key in sorted(mappings)}}
