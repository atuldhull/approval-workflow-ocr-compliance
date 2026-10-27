"""EVC date/slot scheduling: EDF greedy baseline and CP-SAT.

Both algorithms choose DATES and AM/PM parts only. Every panel comes from the
SIMULATED authorised selector (stand-in); neither algorithm picks experts.
CP-SAT uses per-expert variables purely as a feasibility witness (a panel can
exist), then the selector forms the real panel in date order.

Pure: no database, clock, random source or mutation. Capacities and the
lateness allowance are labelled DEMO ASSUMPTION parameters.
"""
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import date as DateValue, timedelta
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from app.evc.selector import AssignmentFact, PanelSelection, SelectorRequest, select_panel
from contracts.errors import ValidationFailed

ALGORITHMS = ("EDF", "CPSAT")
# Ordered from "nothing to work with" to "possible, but taken by other visits".
REASONS = ("NO_AVAILABILITY", "PANEL_INCOMPLETE", "COI_ONLY", "CAPACITY_EXHAUSTED")
Reason = Literal["NO_AVAILABILITY", "PANEL_INCOMPLETE", "COI_ONLY", "CAPACITY_EXHAUSTED"]
CPSAT_STATUS = {"UNKNOWN": 0, "MODEL_INVALID": 1, "FEASIBLE": 2, "INFEASIBLE": 3, "OPTIMAL": 4}


@dataclass(frozen=True)
class SchedulerParameters:
    """DEMO ASSUMPTION defaults; no APH visit duration, calendar or expert load limit exists."""
    default_slot_capacity: int = 4
    expert_daily_capacity: int = 1
    max_lateness_days: int = 0
    time_limit_seconds: float = 60.0
    deterministic_time_limit: float = 2.0
    random_seed: int = 7
    workers: int = 1
    max_repair_rounds: int = 5

    def __post_init__(self) -> None:
        ints = (self.default_slot_capacity, self.expert_daily_capacity, self.max_lateness_days,
                self.random_seed, self.workers, self.max_repair_rounds)
        if (any(type(value) is not int for value in ints) or self.default_slot_capacity < 1
            or self.expert_daily_capacity < 1 or not 0 <= self.max_lateness_days <= 60 or self.workers != 1
            or self.random_seed < 0 or not 0 <= self.max_repair_rounds <= 20
            or not 0 < self.time_limit_seconds <= 120 or not 0 < self.deterministic_time_limit <= 120):
            raise ValidationFailed("EVC_SCHEDULER_PARAMETERS_INVALID")

    def numeric(self) -> dict:
        return dict(default_slot_capacity=self.default_slot_capacity, expert_daily_capacity=self.expert_daily_capacity,
                    max_lateness_days=self.max_lateness_days, time_limit_seconds=self.time_limit_seconds,
                    deterministic_time_limit=self.deterministic_time_limit, random_seed=self.random_seed,
                    workers=self.workers, max_repair_rounds=self.max_repair_rounds)


@dataclass(frozen=True)
class ScheduleItem:
    """One queued request. Its eligibility availability must cover due_by + max_lateness_days."""
    selector: SelectorRequest
    priority_key: str

    @property
    def id(self) -> UUID:
        return self.selector.eligibility.id


@dataclass(frozen=True)
class Calendar:
    """Commitments outside this run: slot use per (date, part) and expert visits per (expert, date)."""
    slot_capacity: tuple[tuple[tuple[DateValue, str], int], ...] = ()
    slot_used: tuple[tuple[tuple[DateValue, str], int], ...] = ()
    expert_day_load: tuple[tuple[tuple[UUID, DateValue], int], ...] = ()


@dataclass(frozen=True)
class Proposal:
    request_id: UUID
    date: DateValue
    slot_part: str
    panel: tuple[UUID, ...]
    due_by: DateValue
    lateness_days: int
    start_offset_days: int
    selection: PanelSelection


@dataclass(frozen=True)
class Explanation:
    request_id: UUID
    reason_code: Reason
    slots_considered: int
    best_qualified_count: int
    panel_size: int
    slot_reasons: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class ScheduleResult:
    algorithm: str
    proposals: tuple[Proposal, ...]
    unscheduled: tuple[Explanation, ...]
    metrics: dict


def horizon(item: ScheduleItem, params: SchedulerParameters) -> DateValue:
    return item.selector.eligibility.due_by + timedelta(days=params.max_lateness_days)


def candidate_slots(item: ScheduleItem, params: SchedulerParameters) -> list[tuple[DateValue, str]]:
    eligibility = item.selector.eligibility
    days = (horizon(item, params) - eligibility.earliest_date).days + 1
    return [(eligibility.earliest_date + timedelta(days=offset), part)
            for offset in range(max(days, 0)) for part in eligibility.policy.slot_parts]


def tentative_id(request_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"sih26262:evc:tentative:{request_id}")


@dataclass
class _State:
    """Commitments made by this run on top of the external calendar."""
    calendar: Calendar
    params: SchedulerParameters
    reserved: set = field(default_factory=set)
    day_load: Counter = field(default_factory=Counter)
    slot_used: Counter = field(default_factory=Counter)
    facts: list = field(default_factory=list)

    def __post_init__(self):
        self.capacity = dict(self.calendar.slot_capacity)
        self.day_load.update(dict(self.calendar.expert_day_load))
        self.slot_used.update(dict(self.calendar.slot_used))

    def remaining(self, slot) -> int:
        return self.capacity.get(slot, self.params.default_slot_capacity) - self.slot_used[slot]

    def blocked(self, day: DateValue, parts) -> frozenset:
        full = {expert for (expert, on), load in self.day_load.items() if on == day and load >= self.params.expert_daily_capacity}
        return frozenset((expert, day, part) for expert in full for part in parts)

    def commit(self, item: ScheduleItem, day: DateValue, part: str, panel: tuple[UUID, ...]) -> None:
        for expert in panel:
            self.reserved.add((expert, day, part))
            self.day_load[(expert, day)] += 1
            self.facts.append(AssignmentFact(tentative_id(item.id), expert, day, part))
        self.slot_used[(day, part)] += 1


def _select(item: ScheduleItem, state: _State, day: DateValue, part: str, *, conflicts=True, reservations=True) -> PanelSelection:
    eligibility = item.selector.eligibility
    held = eligibility.reservations | frozenset(state.reserved) | state.blocked(day, eligibility.policy.slot_parts)
    widened = replace(eligibility, due_by=horizon(item, state.params),
                      conflicts=eligibility.conflicts if conflicts else frozenset(),
                      reservations=held if reservations else frozenset())
    request = replace(item.selector, eligibility=widened, assignments=item.selector.assignments + tuple(state.facts))
    return select_panel(request, day, part)


def _proposal(item: ScheduleItem, day: DateValue, part: str, selection: PanelSelection) -> Proposal:
    eligibility = item.selector.eligibility
    return Proposal(item.id, day, part, selection.panel, eligibility.due_by, max((day - eligibility.due_by).days, 0),
                    (day - eligibility.earliest_date).days, selection)


def explain(item: ScheduleItem, calendar: Calendar, params: SchedulerParameters) -> Explanation:
    """Classify every candidate slot, then report the closest-to-feasible reason for the request."""
    state = _State(calendar, params)
    size = item.selector.policy.panel_size
    counts = Counter()
    best = 0
    slots = candidate_slots(item, params)
    for day, part in slots:
        open_count = _select(item, state, day, part, conflicts=False, reservations=False).eligible_count
        best = max(best, open_count)
        if open_count == 0:
            counts["NO_AVAILABILITY"] += 1
        elif open_count < size:
            counts["PANEL_INCOMPLETE"] += 1
        elif _select(item, state, day, part, reservations=False).eligible_count < size:
            counts["COI_ONLY"] += 1
        else:
            counts["CAPACITY_EXHAUSTED"] += 1
    reason = next((code for code in reversed(REASONS) if counts[code]), "NO_AVAILABILITY")
    return Explanation(item.id, reason, len(slots), best, size, tuple((code, counts[code]) for code in REASONS))


def _ordered(items) -> list[ScheduleItem]:
    """EDF: earliest due date, then queue priority key, then request UUID."""
    return sorted(items, key=lambda item: (item.selector.eligibility.due_by, item.priority_key, str(item.id)))


def _metrics(items, proposals, unscheduled) -> dict:
    late = [p.lateness_days for p in proposals]
    reasons = Counter(row.reason_code for row in unscheduled)
    return dict(requests_considered=len(items), scheduled_count=len(proposals), unscheduled_count=len(unscheduled),
                total_lateness_days=sum(late), late_count=sum(1 for value in late if value),
                max_lateness_days=max(late, default=0),
                total_start_offset_days=sum(p.start_offset_days for p in proposals),
                **{f"reason_{code.lower()}": reasons[code] for code in REASONS})


def _finish(algorithm, items, proposals, calendar, params, extra=None) -> ScheduleResult:
    done = {p.request_id for p in proposals}
    unscheduled = tuple(explain(item, calendar, params) for item in _ordered(items) if item.id not in done)
    proposals = tuple(sorted(proposals, key=lambda p: (p.date, p.slot_part, str(p.request_id))))
    metrics = _metrics(items, proposals, unscheduled)
    metrics.update(extra or {})
    return ScheduleResult(algorithm, proposals, unscheduled, metrics)


def _edf_proposals(items, calendar, params) -> list[Proposal]:
    state = _State(calendar, params)
    proposals = []
    for item in _ordered(items):
        for day, part in candidate_slots(item, params):
            if state.remaining((day, part)) <= 0:
                continue
            selection = _select(item, state, day, part)
            if selection.status == "SELECTED":
                state.commit(item, day, part, selection.panel)
                proposals.append(_proposal(item, day, part, selection))
                break
    return proposals


def schedule_edf(items, calendar: Calendar, params: SchedulerParameters) -> ScheduleResult:
    """Greedy baseline: each request, most urgent first, takes its earliest slot where the selector fills a panel."""
    _unique(items)
    return _finish("EDF", items, _edf_proposals(items, calendar, params), calendar, params)


def _unique(items) -> None:
    if len({item.id for item in items}) != len(items):
        raise ValidationFailed("EVC_SCHEDULE_DUPLICATE_REQUEST")


def _materialize(items, chosen, calendar, params):
    """Form real panels with the selector in date order; most constrained request first within a slot."""
    state = _State(calendar, params)
    by_id = {item.id: item for item in items}
    proposals, failed = [], []
    order = sorted(chosen.items(), key=lambda row: (row[1][0], row[1][1], row[1][2], by_id[row[0]].selector.eligibility.due_by, str(row[0])))
    for request_id, (day, part, _) in order:
        item = by_id[request_id]
        selection = _select(item, state, day, part)
        if state.remaining((day, part)) > 0 and selection.status == "SELECTED":
            state.commit(item, day, part, selection.panel)
            proposals.append(_proposal(item, day, part, selection))
        else:
            failed.append((request_id, (day, part)))
    return proposals, failed


def schedule_cpsat(items, calendar: Calendar, params: SchedulerParameters) -> ScheduleResult:
    """CP-SAT chooses dates/parts: maximise scheduled visits, then minimise lateness, then start earlier.

    Deterministic: one worker, fixed seed and a deterministic-time limit (wall-clock limit only as a safety cap).
    The EDF plan is supplied as a solution hint; if panel formation ever leaves CP-SAT behind EDF, the EDF plan
    is kept and reported through fallback_to_edf.
    """
    from ortools.sat.python import cp_model

    _unique(items)
    baseline = _edf_proposals(items, calendar, params)
    base = _State(calendar, params)
    witnesses = {}
    for item in items:
        for day, part in candidate_slots(item, params):
            if base.remaining((day, part)) <= 0:
                continue
            selection = _select(item, base, day, part)
            if selection.status == "SELECTED":
                witnesses[(item.id, day, part)] = tuple(row.expert_id for row in selection.ranked_experts)
    by_id = {item.id: item for item in items}
    forbidden: set = set()
    rounds = 0
    solver_status = CPSAT_STATUS["OPTIMAL"] if not witnesses else 0
    objective = bound = 0
    while True:
        model = cp_model.CpModel()
        x, y = {}, {}
        for key, experts in witnesses.items():
            if (key[0], (key[1], key[2])) in forbidden:
                continue
            x[key] = model.new_bool_var("")
            members = []
            for expert in experts:
                y[key + (expert,)] = var = model.new_bool_var("")
                model.add_implication(var, x[key])
                members.append(var)
            model.add(sum(members) == by_id[key[0]].selector.policy.panel_size * x[key])
        per_request, per_slot, per_time, per_day = {}, {}, {}, {}
        for key, var in x.items():
            per_request.setdefault(key[0], []).append(var)
            per_slot.setdefault(key[1:], []).append(var)
        for (request_id, day, part, expert), var in y.items():
            per_time.setdefault((expert, day, part), []).append(var)
            per_day.setdefault((expert, day), []).append(var)
        for group in per_request.values():
            model.add_at_most_one(group)
        for slot, group in per_slot.items():
            model.add(sum(group) <= max(base.remaining(slot), 0))
        for group in per_time.values():
            model.add_at_most_one(group)
        for (expert, day), group in per_day.items():
            model.add(sum(group) <= max(params.expert_daily_capacity - base.day_load[(expert, day)], 0))
        lateness, offset, worst_late, worst_offset = {}, {}, Counter(), Counter()
        for key in x:
            eligibility = by_id[key[0]].selector.eligibility
            lateness[key] = max((key[1] - eligibility.due_by).days, 0)
            offset[key] = 2 * (key[1] - eligibility.earliest_date).days + eligibility.policy.slot_parts.index(key[2])
            worst_late[key[0]] = max(worst_late[key[0]], lateness[key])
            worst_offset[key[0]] = max(worst_offset[key[0]], offset[key])
        # Lexicographic weights: one more visit beats any lateness change, which beats any start-offset change.
        lateness_weight = sum(worst_offset.values()) + 1
        count_weight = lateness_weight * (sum(worst_late.values()) + 1)
        model.maximize(sum((count_weight - lateness_weight * lateness[k] - offset[k]) * var for k, var in x.items()))
        hinted = {(p.request_id, p.date, p.slot_part): p.panel for p in baseline}
        for key, var in x.items():
            model.add_hint(var, int(key in hinted))
        for key, var in y.items():
            model.add_hint(var, int(key[:3] in hinted and key[3] in hinted[key[:3]]))
        solver = cp_model.CpSolver()
        solver.parameters.num_workers = params.workers
        solver.parameters.random_seed = params.random_seed
        solver.parameters.max_time_in_seconds = params.time_limit_seconds
        solver.parameters.max_deterministic_time = params.deterministic_time_limit
        status = solver.solve(model)
        solver_status = CPSAT_STATUS.get(solver.status_name(status), 0)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            chosen = {}
        else:
            objective, bound = int(solver.objective_value), int(solver.best_objective_bound)
            chosen = {key[0]: (key[1], key[2], len(witnesses[key])) for key, var in x.items() if solver.value(var)}
        proposals, failed = _materialize(items, chosen, calendar, params)
        if not failed or rounds >= params.max_repair_rounds:
            break
        forbidden.update(failed)
        rounds += 1

    def score(rows):
        return (len(rows), -sum(p.lateness_days for p in rows))
    fallback = score(baseline) > score(proposals)
    extra = dict(solver_status=solver_status, objective_value=objective, best_bound=bound, repair_rounds=rounds,
                 fallback_to_edf=fallback, candidate_slot_count=len(witnesses),
                 edf_scheduled_count=len(baseline))
    return _finish("CPSAT", items, baseline if fallback else proposals, calendar, params, extra)


def schedule(algorithm: str, items, calendar: Calendar, params: SchedulerParameters) -> ScheduleResult:
    if algorithm == "EDF":
        return schedule_edf(items, calendar, params)
    if algorithm == "CPSAT":
        return schedule_cpsat(items, calendar, params)
    raise ValidationFailed("EVC_SCHEDULE_ALGORITHM_INVALID")
