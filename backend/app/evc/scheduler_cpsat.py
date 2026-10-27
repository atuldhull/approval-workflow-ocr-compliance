"""CP-SAT date/slot planner over the same SchedulingProblem, selector and metrics as the EDF baseline.

CP-SAT chooses a slot per request only. Per-expert variables are a feasibility
witness (a complete panel can exist, within the pinned per-expert daily cap); the real panel is always the SIMULATED
authorised selector (stand-in)'s result, formed through selector_at in slot
order. A slot the selector cannot fill is forbidden and the model re-solved.
The result is scored with evaluate_schedule; if EDF scores better on the shared
comparison key, EDF's allocations are kept and fallback_to_edf is reported.

Pure: no database, clock or random source. One worker, fixed seed and a
deterministic-time limit make runs repeatable.
"""
from collections import Counter
from dataclasses import dataclass

from app.evc.metrics import comparison_key, evaluate_schedule
from app.evc.scheduler_edf import plan_edf
from app.evc.scheduling import (Allocation, SchedulingPlan, SchedulingProblem, commitments, earliest_date, logical_date,
                                request_order, selector_at, slot_order, visits_per_day)
from app.evc.selector import select_panel
from contracts.errors import ValidationFailed

CPSAT_STATUS = {"UNKNOWN": 0, "MODEL_INVALID": 1, "FEASIBLE": 2, "INFEASIBLE": 3, "OPTIMAL": 4}


@dataclass(frozen=True)
class CpSatParameters:
    deterministic_time_limit: float = 2.0
    time_limit_seconds: float = 60.0  # wall-clock safety cap only
    random_seed: int = 7
    max_repair_rounds: int = 5
    # Earliest feasible slots modelled per request (plus EDF's own slot), so wide late horizons stay solvable.
    # Propose passes the pinned expert_pool.scheduler.cpsat_candidate_slots (DEMO ASSUMPTION, default 12).
    max_candidate_slots: int = 12

    def __post_init__(self) -> None:
        if (type(self.max_candidate_slots) is not int or not 1 <= self.max_candidate_slots <= 200
            or not 0 < self.deterministic_time_limit <= 120 or not 0 < self.time_limit_seconds <= 120
            or type(self.random_seed) is not int or self.random_seed < 0
            or type(self.max_repair_rounds) is not int or not 0 <= self.max_repair_rounds <= 20):
            raise ValidationFailed("SCHEDULER_CPSAT_PARAMETERS_INVALID")


@dataclass(frozen=True)
class CpSatResult:
    plan: SchedulingPlan
    solver_status: int
    objective_value: int
    best_bound: int
    repair_rounds: int
    candidate_count: int
    edf_scheduled: int
    fallback_to_edf: bool
    candidate_slots: int = 12

    def numeric(self) -> dict:
        """Solver facts for schedule_run.parameters (numeric/boolean only)."""
        return dict(cpsat_solver_status=self.solver_status, cpsat_objective_value=self.objective_value,
                    cpsat_best_bound=self.best_bound, cpsat_repair_rounds=self.repair_rounds,
                    cpsat_candidate_count=self.candidate_count, cpsat_edf_scheduled=self.edf_scheduled,
                    cpsat_fallback_to_edf=self.fallback_to_edf, cpsat_candidate_slots=self.candidate_slots)


def _witnesses(problem: SchedulingProblem, limit: int, keep: set) -> dict:
    """(request, slot) -> every qualified free expert, against existing reservations only.

    Per request only the earliest `limit` feasible slots are kept, plus any (request, slot) in `keep`.
    """
    occupancy = Counter(allocation.slot_id for allocation in problem.existing)
    result = {}
    for request in problem.ordered_requests:
        snapshot = selector_at(problem, request, ())
        start = earliest_date(problem, request)
        found = 0
        for slot in problem.ordered_slots:
            if (slot.date < start or occupancy[slot.id] >= slot.capacity
                    or slot.slot_part not in snapshot.eligibility.policy.slot_parts):
                continue
            if found >= limit and (request.id, slot.id) not in keep:
                continue
            selection = select_panel(snapshot, slot.date, slot.slot_part)
            if selection.status == "SELECTED":
                result[(request.id, slot.id)] = tuple(row.expert_id for row in selection.ranked_experts)
                found += 1
    return result


def _materialize(problem: SchedulingProblem, chosen: dict) -> tuple[list[Allocation], list[tuple]]:
    """Form real panels slot by slot (most urgent request first within a slot)."""
    requests = {request.id: request for request in problem.requests}
    slots = {slot.id: slot for slot in problem.slots}
    occupancy = Counter(allocation.slot_id for allocation in problem.existing)
    planned, failed = [], []
    for request_id, slot_id in sorted(chosen.items(), key=lambda row: (slot_order(slots[row[1]]), request_order(requests[row[0]]))):
        request, slot = requests[request_id], slots[slot_id]
        selection = select_panel(selector_at(problem, request, tuple(planned)), slot.date, slot.slot_part)
        if occupancy[slot_id] < slot.capacity and selection.status == "SELECTED":
            planned.append(Allocation(request_id, slot_id, selection.panel))
            occupancy[slot_id] += 1
        else:
            failed.append((request_id, slot_id))
    return planned, failed


def solve_cpsat(problem: SchedulingProblem, params: CpSatParameters = CpSatParameters()) -> CpSatResult:
    """Maximise scheduled requests, then minimise total lateness, maximum lateness and waiting."""
    from ortools.sat.python import cp_model

    edf = plan_edf(problem)  # also validates the baseline reservations
    requests = {request.id: request for request in problem.requests}
    slots = {slot.id: slot for slot in problem.slots}
    occupancy = Counter(allocation.slot_id for allocation in problem.existing)
    hinted = {(row.request_id, row.slot_id): row.expert_ids for row in edf.allocations}
    witnesses = _witnesses(problem, params.max_candidate_slots, set(hinted))
    lateness, waiting = {}, {}
    for request_id, slot_id in witnesses:
        request, day = requests[request_id], slots[slot_id].date
        lateness[(request_id, slot_id)] = max(0, (day - request.selector.eligibility.due_by).days)
        waiting[(request_id, slot_id)] = max(0, (day - logical_date(request.requested_at)).days)
    worst_late, worst_wait = Counter(), Counter()
    for (request_id, _), value in lateness.items():
        worst_late[request_id] = max(worst_late[request_id], value)
    for (request_id, _), value in waiting.items():
        worst_wait[request_id] = max(worst_wait[request_id], value)
    max_late_bound = max(worst_late.values(), default=0)
    # Lexicographic weights: one more request beats any lateness change, total lateness beats the maximum,
    # and the maximum beats any waiting change.
    max_weight = sum(worst_wait.values()) + 1
    late_weight = max_weight * (max_late_bound + 1)
    count_weight = late_weight * (sum(worst_late.values()) + 1)
    # Daily cap: visits an expert may still take per date beyond existing commitments (None = uncapped).
    remaining_day = None
    if problem.expert_daily_cap is not None:
        used = visits_per_day(commitments(problem))
        remaining_day = lambda expert, day: max(problem.expert_daily_cap - len(used.get((expert, day), ())), 0)
    forbidden: set = set()
    rounds = status = objective = bound = 0
    while True:
        model = cp_model.CpModel()
        x, y = {}, {}
        for key, experts in witnesses.items():
            if key in forbidden:
                continue
            x[key] = model.new_bool_var("")
            members = []
            for expert in experts:
                y[key + (expert,)] = var = model.new_bool_var("")
                model.add_implication(var, x[key])
                members.append(var)
            model.add(sum(members) == requests[key[0]].selector.policy.panel_size * x[key])
        per_request, per_slot, per_time, per_day = {}, {}, {}, {}
        for key, var in x.items():
            per_request.setdefault(key[0], []).append(var)
            per_slot.setdefault(key[1], []).append(var)
        for (request_id, slot_id, expert), var in y.items():
            slot = slots[slot_id]
            per_time.setdefault((expert, slot.date, slot.slot_part), []).append(var)
            per_day.setdefault((expert, slot.date), []).append(var)
        for group in (*per_request.values(), *per_time.values()):
            model.add_at_most_one(group)
        for slot_id, group in per_slot.items():
            model.add(sum(group) <= max(slots[slot_id].capacity - occupancy[slot_id], 0))
        if remaining_day is not None:
            for (expert, day), group in per_day.items():
                model.add(sum(group) <= remaining_day(expert, day))
        worst = model.new_int_var(0, max_late_bound, "")
        for key, var in x.items():
            if lateness[key]:
                model.add(worst >= lateness[key] * var)
        model.maximize(sum((count_weight - late_weight * lateness[k] - waiting[k]) * var for k, var in x.items())
                       - max_weight * worst)
        for key, var in x.items():
            model.add_hint(var, int(key in hinted))
        for key, var in y.items():
            model.add_hint(var, int(key[:2] in hinted and key[2] in hinted[key[:2]]))
        solver = cp_model.CpSolver()
        solver.parameters.num_workers = 1
        solver.parameters.random_seed = params.random_seed
        solver.parameters.max_time_in_seconds = params.time_limit_seconds
        solver.parameters.max_deterministic_time = params.deterministic_time_limit
        code = solver.solve(model)
        status = CPSAT_STATUS.get(solver.status_name(code), 0)
        chosen = {}
        if code in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            objective, bound = int(solver.objective_value), int(solver.best_objective_bound)
            chosen = {key[0]: key[1] for key, var in x.items() if solver.value(var)}
        planned, failed = _materialize(problem, chosen)
        if not failed or rounds >= params.max_repair_rounds:
            break
        forbidden.update(failed)
        rounds += 1
    position = {request.id: index for index, request in enumerate(problem.ordered_requests)}
    planned.sort(key=lambda row: position[row.request_id])
    metrics = evaluate_schedule(problem, tuple(planned)).metrics
    fallback = comparison_key(edf.metrics) < comparison_key(metrics)
    allocations = edf.allocations if fallback else tuple(planned)
    result = evaluate_schedule(problem, allocations)
    if result.metrics.hard_constraint_violations:
        raise ValidationFailed("SCHEDULER_PLAN_INVALID")
    done = {row.request_id for row in allocations}
    plan = SchedulingPlan("CPSAT", allocations, tuple(r.id for r in problem.ordered_requests if r.id not in done),
                          result.metrics, problem.fingerprint)
    return CpSatResult(plan, status, objective, bound, rounds, len(witnesses), edf.metrics.scheduled, fallback,
                       params.max_candidate_slots)


def plan_cpsat(problem: SchedulingProblem, params: CpSatParameters = CpSatParameters()) -> SchedulingPlan:
    return solve_cpsat(problem, params).plan
