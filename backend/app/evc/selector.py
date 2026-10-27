"""SIMULATED authorised selector (stand-in).

Pure, deterministic lexicographic selection: eligibility, expertise, workload,
oldest prior assignment date, UUID. Policy is a labelled DEMO ASSUMPTION.
"""
from collections import Counter
from dataclasses import dataclass
from datetime import date as DateValue
import re
from typing import Literal
from uuid import UUID

from app.evc.eligibility import EligibilityRequest, eligible_experts
from contracts.errors import ValidationFailed

SELECTOR_LABEL = "SIMULATED authorised selector (stand-in)"
CRITERIA = ("ELIGIBILITY", "EXPERTISE_MATCH", "WORKLOAD", "ROTATION", "EXPERT_ID")
CODE = re.compile(r"^[A-Z][A-Z0-9_]*$")
CriteriaOrder = tuple[Literal["ELIGIBILITY"], Literal["EXPERTISE_MATCH"], Literal["WORKLOAD"],
                      Literal["ROTATION"], Literal["EXPERT_ID"]]


@dataclass(frozen=True)
class SelectorPolicy:
    panel_size: int
    required_expertise_tags: tuple[str, ...]
    category_expertise_tags: tuple[tuple[str, tuple[str, ...]], ...] = ()
    minimum_expertise_matches: int = 1

    def __post_init__(self) -> None:
        def valid_tags(values):
            return (isinstance(values, tuple) and bool(values)
                    and all(isinstance(v, str) and CODE.fullmatch(v) for v in values) and len(values) == len(set(values)))
        if (type(self.panel_size) is not int or self.panel_size < 1
            or type(self.minimum_expertise_matches) is not int or self.minimum_expertise_matches < 1
            or not valid_tags(self.required_expertise_tags) or not isinstance(self.category_expertise_tags, tuple)):
            raise ValidationFailed("SELECTOR_POLICY_INVALID")
        seen = set()
        for entry in self.category_expertise_tags:
            if not isinstance(entry, tuple) or len(entry) != 2:
                raise ValidationFailed("SELECTOR_CATEGORY_POLICY_INVALID")
            category, tags = entry
            if not isinstance(category, str) or not CODE.fullmatch(category) or category in seen or not valid_tags(tags):
                raise ValidationFailed("SELECTOR_CATEGORY_POLICY_INVALID")
            seen.add(category)
        if any(self.minimum_expertise_matches > len(tags) for tags in
               [self.required_expertise_tags, *(tags for _, tags in self.category_expertise_tags)]):
            raise ValidationFailed("SELECTOR_MINIMUM_EXPERTISE_INVALID")

    @classmethod
    def from_mapping(cls, raw: dict) -> "SelectorPolicy":
        keys = {"version", "panel_size", "required_expertise_tags", "category_expertise_tags",
                "minimum_expertise_matches", "source_status", "assumption_code"}
        if (not isinstance(raw, dict) or set(raw) != keys or raw.get("version") != "DEMO_SELECTOR_V1"
            or raw.get("source_status") != "DEMO_ASSUMPTION" or raw.get("assumption_code") != "SELECTOR_POLICY_UNCONFIRMED"
            or not isinstance(raw.get("required_expertise_tags"), list) or not isinstance(raw.get("category_expertise_tags"), dict)):
            raise ValidationFailed("SELECTOR_POLICY_UNAVAILABLE")
        mappings = raw["category_expertise_tags"]
        if any(not isinstance(key, str) or not isinstance(value, list) for key, value in mappings.items()):
            raise ValidationFailed("SELECTOR_CATEGORY_POLICY_INVALID")
        # Validate before sorting malformed input so errors stay coded 422s.
        result = cls(raw["panel_size"], tuple(raw["required_expertise_tags"]),
                     tuple((key, tuple(value)) for key, value in mappings.items()), raw["minimum_expertise_matches"])
        return cls(result.panel_size, tuple(sorted(result.required_expertise_tags)),
                   tuple(sorted((key, tuple(sorted(tags))) for key, tags in result.category_expertise_tags)),
                   result.minimum_expertise_matches)

    def tags_for(self, category: str) -> tuple[str, ...]:
        return tuple(sorted(dict(self.category_expertise_tags).get(category, self.required_expertise_tags)))


@dataclass(frozen=True)
class AssignmentFact:
    assignment_id: UUID
    expert_id: UUID
    date: DateValue
    slot_part: str


@dataclass(frozen=True)
class SelectorRequest:
    eligibility: EligibilityRequest
    category: str
    policy: SelectorPolicy
    assignments: tuple[AssignmentFact, ...] = ()


@dataclass(frozen=True)
class CriterionScores:
    expertise_matches: int
    workload_assignments: int
    last_assignment_date: DateValue | None
    rotation_days: int | None
    rotation_ordinal: int
    eligibility_passed: Literal[True] = True


@dataclass(frozen=True)
class RankedExpert:
    rank: int
    expert_id: UUID
    selected: bool
    matched_expertise_tags: tuple[str, ...]
    criterion_scores: CriterionScores


@dataclass(frozen=True)
class PanelSelection:
    request_id: UUID
    ruleset_key: str
    date: DateValue
    slot_part: Literal["AM", "PM"]
    requested_size: int
    status: Literal["SELECTED", "INSUFFICIENT_CANDIDATES"]
    panel: tuple[UUID, ...]
    eligible_count: int
    required_expertise_tags: tuple[str, ...]
    ranked_experts: tuple[RankedExpert, ...]
    selector_label: Literal["SIMULATED authorised selector (stand-in)"] = SELECTOR_LABEL
    simulation_status: Literal["SIMULATED"] = "SIMULATED"
    source_status: Literal["DEMO_ASSUMPTION"] = "DEMO_ASSUMPTION"
    assumption_code: Literal["SELECTOR_POLICY_UNCONFIRMED"] = "SELECTOR_POLICY_UNCONFIRMED"
    identity_status: Literal["P3_USER_REF_UNVERIFIED"] = "P3_USER_REF_UNVERIFIED"
    policy_version: Literal["DEMO_SELECTOR_V1"] = "DEMO_SELECTOR_V1"
    criteria_order: CriteriaOrder = CRITERIA


def _workload(assignments: tuple[AssignmentFact, ...], on_date: DateValue) -> tuple[Counter, dict[UUID, DateValue]]:
    unique = {}
    for fact in assignments:
        key = (fact.assignment_id, fact.expert_id)
        if key in unique and unique[key] != fact:
            raise ValidationFailed("SELECTOR_HISTORY_CONFLICT")
        unique[key] = fact
    counts = Counter()
    last = {}
    for fact in unique.values():
        counts[fact.expert_id] += 1  # Every distinct proposed/published commitment, including future ones.
        if fact.date < on_date:
            last[fact.expert_id] = max(last.get(fact.expert_id, fact.date), fact.date)
    return counts, last


def select_panel(request: SelectorRequest, date: DateValue, slot_part: str) -> PanelSelection:
    """SIMULATED authorised selector (stand-in); exactly N or an explained empty panel."""
    experts = request.eligibility.experts
    if len({expert.id for expert in experts}) != len(experts):
        raise ValidationFailed("SELECTOR_DUPLICATE_EXPERT")
    candidates = eligible_experts(request.eligibility, date, slot_part)
    tags = request.policy.tags_for(request.category)
    counts, last = _workload(request.assignments, date)
    scored = []
    for expert in candidates:
        matched = tuple(sorted(set(expert.expertise_tags) & set(tags)))
        if len(matched) < request.policy.minimum_expertise_matches:
            continue
        previous = last.get(expert.id)
        scores = CriterionScores(len(matched), counts[expert.id], previous,
                                 (date - previous).days if previous else None, previous.toordinal() if previous else 0)
        key = (-scores.expertise_matches, scores.workload_assignments, scores.rotation_ordinal, expert.id.int)
        scored.append((key, expert.id, matched, scores))
    scored.sort(key=lambda row: row[0])
    complete = len(scored) >= request.policy.panel_size
    panel = tuple(row[1] for row in scored[:request.policy.panel_size]) if complete else ()
    ranked = tuple(RankedExpert(index, row[1], complete and index <= request.policy.panel_size, row[2], row[3])
                   for index, row in enumerate(scored, 1))
    return PanelSelection(request.eligibility.id, request.eligibility.ruleset_key, date, slot_part,
                          request.policy.panel_size, "SELECTED" if complete else "INSUFFICIENT_CANDIDATES",
                          panel, len(scored), tags, ranked)
