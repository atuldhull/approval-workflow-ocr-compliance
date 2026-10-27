"""Pinned policy values for guard facts that have no authoritative record yet (DEMO ASSUMPTION)."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from contracts.errors import ValidationFailed


class GuardFactsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    revert_second_approval_required: Annotated[bool, Field(strict=True)]
    source_status: Literal["DEMO_ASSUMPTION"]
    assumption_code: Literal["GUARD_FACT_POLICY_UNCONFIRMED"]


def validate_config(raw: dict) -> dict | None:
    if "guard_facts" not in raw:
        return None  # older pinned rulesets keep refusing: no implicit defaults
    try:
        return GuardFactsConfig.model_validate(raw["guard_facts"]).model_dump(mode="json")
    except ValidationError as exc:
        raise ValidationFailed("INVALID_GUARD_FACTS_CONFIG") from exc
