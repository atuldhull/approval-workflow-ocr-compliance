"""Immutable comparison inputs shared by EDF, metrics and the future CP-SAT planner."""
from dataclasses import asdict, dataclass, fields, is_dataclass, replace
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from typing import Literal
from uuid import UUID, NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from app.evc.selector import AssignmentFact, SELECTOR_LABEL, SelectorRequest
from contracts.errors import ValidationFailed

IST = ZoneInfo("Asia/Kolkata")
PART_ORDER = {"AM": 0, "PM": 1}


def logical_date(instant: datetime) -> date:
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValidationFailed("SCHEDULER_CLOCK_MUST_BE_AWARE")
    return instant.astimezone(IST).date()


@dataclass(frozen=True)
class SchedulingRequest:
    selector: SelectorRequest
    requested_at: datetime
    allow_late: bool

    def __post_init__(self) -> None:
        logical_date(self.requested_at)
        if type(self.allow_late) is not bool:
            raise ValidationFailed("SCHEDULER_POLICY_INVALID")

    @property
    def id(self) -> UUID:
        return self.selector.eligibility.id


@dataclass(frozen=True)
class SchedulingSlot:
    id: UUID
    date: date
    slot_part: str
    capacity: int

    def __post_init__(self) -> None:
        if type(self.capacity) is not int or self.capacity <= 0 or self.slot_part not in PART_ORDER:
            raise ValidationFailed("SCHEDULER_SLOT_INVALID")


@dataclass(frozen=True)
class Allocation:
    request_id: UUID
    slot_id: UUID
    expert_ids: tuple[UUID, ...]


def request_order(request: SchedulingRequest) -> tuple:
    return request.selector.eligibility.due_by, request.requested_at.astimezone(timezone.utc), request.id.int


def slot_order(slot: SchedulingSlot) -> tuple:
    return slot.date, PART_ORDER[slot.slot_part], slot.id.int


@dataclass(frozen=True)
class SchedulingProblem:
    requests: tuple[SchedulingRequest, ...]
    slots: tuple[SchedulingSlot, ...]
    existing: tuple[Allocation, ...]
    horizon_start: date
    horizon_end: date
    clock_at: datetime

    def __post_init__(self) -> None:
        logical_date(self.clock_at)
        if self.horizon_end < self.horizon_start:
            raise ValidationFailed("SCHEDULER_HORIZON_INVALID")
        if len({r.id for r in self.requests}) != len(self.requests) or len({s.id for s in self.slots}) != len(self.slots):
            raise ValidationFailed("SCHEDULER_DUPLICATE_INPUT")
        if any(not self.horizon_start <= slot.date <= self.horizon_end for slot in self.slots):
            raise ValidationFailed("SCHEDULER_SLOT_OUTSIDE_HORIZON")

    @property
    def ordered_requests(self) -> tuple[SchedulingRequest, ...]:
        return tuple(sorted(self.requests, key=request_order))

    @property
    def ordered_slots(self) -> tuple[SchedulingSlot, ...]:
        return tuple(sorted(self.slots, key=slot_order))

    @property
    def fingerprint(self) -> str:
        unordered_fields = {"requests", "slots", "existing", "experts", "availability", "assignments",
                            "required_expertise_tags", "category_expertise_tags", "expertise_tags", "expert_ids"}
        def normalize(value, *, unordered=False):
            if is_dataclass(value):
                return {field.name: normalize(getattr(value, field.name), unordered=field.name in unordered_fields) for field in fields(value)}
            if isinstance(value, datetime):
                return value.astimezone(timezone.utc).isoformat()
            if isinstance(value, date):
                return value.isoformat()
            if isinstance(value, UUID):
                return str(value)
            if isinstance(value, (frozenset, set)):
                return sorted((normalize(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True))
            if isinstance(value, (tuple, list)):
                items = [normalize(item) for item in value]
                return sorted(items, key=lambda item: json.dumps(item, sort_keys=True)) if unordered else items
            if isinstance(value, dict):
                return {key: normalize(item) for key, item in sorted(value.items())}
            return value
        encoded = json.dumps(normalize(self), sort_keys=True, separators=(",", ":")).encode()
        return sha256(encoded).hexdigest()


def earliest_date(problem: SchedulingProblem, request: SchedulingRequest) -> date:
    return max(problem.horizon_start, logical_date(problem.clock_at), logical_date(request.requested_at),
               request.selector.eligibility.earliest_date)


def selector_at(problem: SchedulingProblem, request: SchedulingRequest, planned: tuple[Allocation, ...]) -> SelectorRequest:
    """Reuse the same pinned selector with explicit current reservations and workload."""
    slots = {slot.id: slot for slot in problem.slots}
    end = problem.horizon_end if request.allow_late else min(problem.horizon_end, request.selector.eligibility.due_by)
    reservations = set(request.selector.eligibility.reservations)
    for allocation in (*problem.existing, *planned):
        slot = slots.get(allocation.slot_id)
        if slot:
            reservations.update((expert, slot.date, slot.slot_part) for expert in allocation.expert_ids)
    history = list(request.selector.assignments)
    for allocation in planned:
        slot = slots.get(allocation.slot_id)
        if slot:
            assignment_id = uuid5(NAMESPACE_URL, f"sih26262:planning:{allocation.request_id}:{allocation.slot_id}")
            history.extend(AssignmentFact(assignment_id, expert, slot.date, slot.slot_part) for expert in allocation.expert_ids)
    eligibility = replace(request.selector.eligibility, planning_until=end, reservations=frozenset(reservations))
    return replace(request.selector, eligibility=eligibility, assignments=tuple(history))


@dataclass(frozen=True)
class SchedulingMetrics:
    queue_count: int
    scheduled: int
    unscheduled: int
    late_count: int
    total_lateness: int
    max_lateness: int
    total_waiting: int
    hard_constraint_violations: int
    lateness_days: tuple[int | None, ...]

    def numeric_json(self) -> dict:
        result = asdict(self)
        result["lateness_days"] = list(self.lateness_days)
        return result


@dataclass(frozen=True)
class SchedulingPlan:
    algorithm: Literal["EDF", "CPSAT"]
    allocations: tuple[Allocation, ...]
    unscheduled: tuple[UUID, ...]
    metrics: SchedulingMetrics
    input_fingerprint: str
    selector_label: str = SELECTOR_LABEL
    simulation_status: Literal["SIMULATED"] = "SIMULATED"
    source_status: Literal["DEMO_ASSUMPTION"] = "DEMO_ASSUMPTION"
    assumption_code: Literal["EDF_PLANNING_UNCONFIRMED"] = "EDF_PLANNING_UNCONFIRMED"
    unscheduled_reason: Literal["NO_FEASIBLE_SLOT"] = "NO_FEASIBLE_SLOT"
