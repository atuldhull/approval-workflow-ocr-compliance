"""Immutable eligibility inputs and a pure core; database loading is separate."""
from dataclasses import dataclass
from datetime import date as DateValue
from uuid import UUID

from contracts.errors import ValidationFailed


@dataclass(frozen=True)
class ExpertPolicy:
    region_rule: str
    slot_parts: tuple[str, ...]

    @classmethod
    def from_mapping(cls, raw: dict) -> "ExpertPolicy":
        if (not isinstance(raw, dict) or raw.get("region_rule") not in ("SAME_REGION", "ANY_REGION", "OTHER_REGION")
            or raw.get("slot_parts") != ["AM", "PM"]
            or raw.get("coi_reasons") != {key: key for key in ("INSTITUTION_LINK", "PRIOR_ENGAGEMENT", "RECUSAL")}
            or raw.get("source_status") != "DEMO_ASSUMPTION"
            or raw.get("assumption_code") != "EXPERT_POLICY_UNCONFIRMED"):
            raise ValidationFailed("EXPERT_POOL_POLICY_UNAVAILABLE")
        return cls(raw["region_rule"], tuple(raw["slot_parts"]))


@dataclass(frozen=True)
class ExpertCandidate:
    id: UUID
    user_ref: UUID
    region: str
    expertise_tags: tuple[str, ...]
    active: bool


@dataclass(frozen=True)
class AvailabilityFact:
    expert_id: UUID
    date: DateValue
    slot_part: str
    available: bool


@dataclass(frozen=True)
class EligibilityRequest:
    id: UUID
    institution_ref: UUID
    region: str
    ruleset_key: str
    earliest_date: DateValue
    due_by: DateValue
    policy: ExpertPolicy
    experts: tuple[ExpertCandidate, ...]
    availability: tuple[AvailabilityFact, ...]
    conflicts: frozenset[tuple[UUID, UUID]]
    reservations: frozenset[tuple[UUID, DateValue, str]]


def eligible_experts(request: EligibilityRequest, date: DateValue, slot_part: str) -> list[ExpertCandidate]:
    """No I/O, time or mutation. Missing availability is unavailable; proposals reserve too."""
    if request.policy.region_rule not in ("SAME_REGION", "ANY_REGION", "OTHER_REGION"):
        raise ValidationFailed("EXPERT_POOL_REGION_RULE_INVALID")
    if slot_part not in request.policy.slot_parts:
        raise ValidationFailed("EXPERT_SLOT_PART_INVALID")
    if not request.earliest_date <= date <= request.due_by:
        return []
    declared = {row.expert_id for row in request.availability if row.date == date and row.slot_part == slot_part and row.available}
    unavailable = {row.expert_id for row in request.availability if row.date == date and row.slot_part == slot_part and not row.available}
    result = []
    for expert in request.experts:
        same_region = expert.region.upper() == request.region.upper()
        if (not expert.active or expert.id not in declared or expert.id in unavailable
            or (expert.id, request.institution_ref) in request.conflicts
            or (expert.id, date, slot_part) in request.reservations
            or (request.policy.region_rule == "SAME_REGION" and not same_region)
            or (request.policy.region_rule == "OTHER_REGION" and same_region)):
            continue
        result.append(expert)
    return sorted(result, key=lambda expert: expert.id.int)
