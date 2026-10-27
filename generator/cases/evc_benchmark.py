"""EDF baseline vs CP-SAT EVC date scheduling on the seeded DEMO pool; pure, no database.

Experts, availability and COIs come from seed_evc_demo.demo_rows (30 fictional
experts, 60 days, 3 COIs). Requests are synthetic and seeded: per DEMO region and
day, 0-2 arrivals with a 7-day window (the EVC_PROCESSING DEMO ASSUMPTION), and a
share of requests from the three COI institutions. Both planners get the same
immutable SchedulingProblem and are scored by metrics.compare_plans. Panels always
come from the SIMULATED authorised selector (stand-in); the planners choose slots.
"""
import argparse
import json
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

import yaml  # noqa: E402

from app.evc.eligibility import AvailabilityFact, EligibilityRequest, ExpertCandidate, ExpertPolicy  # noqa: E402
from app.evc.metrics import compare_plans  # noqa: E402
from app.evc.scheduler_cpsat import solve_cpsat  # noqa: E402
from app.evc.scheduler_edf import plan_edf  # noqa: E402
from app.evc.scheduling import SchedulingProblem, SchedulingRequest, SchedulingSlot  # noqa: E402
from app.evc.selector import SelectorPolicy, SelectorRequest  # noqa: E402
from generator.cases.scale_generator import LogicalClock  # noqa: E402
from generator.cases.seed_evc_demo import demo_rows  # noqa: E402

AT = "2026-07-01T04:30:00Z"
WINDOW_DAYS = 7
LATE_DAYS = 7
SLOT_CAPACITY = 4
INSTITUTIONS = [uuid5(NAMESPACE_URL, f"SIH26262:DEMO:EVC:benchmark:institution:{i}") for i in range(3)]


def policies():
    raw = yaml.safe_load((ROOT / "rulesets" / "aph-2024-27" / "r1" / "routes.yaml").read_text(encoding="utf-8"))["expert_pool"]
    return ExpertPolicy.from_mapping(raw), SelectorPolicy.from_mapping(raw["selector"])


def scenario(seed: int = 26262, arrival_days: int = 40, coi_share: float = 0.35, allow_late: bool = False,
             regions: int = 9) -> SchedulingProblem:
    """Deterministic synthetic queue over the seeded DEMO pool (fictional data only).

    The horizon ends 7 days after the last due date when late planning is allowed, otherwise at it.
    """
    clock_at = datetime.fromisoformat(AT.replace("Z", "+00:00")).astimezone(timezone.utc)
    rows = demo_rows(LogicalClock(AT), INSTITUTIONS)
    expert_policy, selector_policy = policies()
    experts = tuple(sorted((ExpertCandidate(r["id"], r["user_ref"], r["region"], tuple(sorted(r["expertise_tags"])), r["active"])
                            for r in rows["experts"]), key=lambda e: e.id.int))
    availability = [AvailabilityFact(r["expert_id"], r["date"], r["slot_part"], r["available"]) for r in rows["availability"]]
    coi_region = {c["institution_ref"]: next(e.region for e in experts if e.id == c["expert_id"]) for c in rows["coi"]}
    conflicts = {inst: frozenset((c["expert_id"], inst) for c in rows["coi"] if c["institution_ref"] == inst) for inst in INSTITUTIONS}
    start = clock_at.date()
    end = start + timedelta(days=arrival_days - 1 + WINDOW_DAYS + (LATE_DAYS if allow_late else 0))
    rng = random.Random(seed)
    requests = []
    for day in range(arrival_days):
        for index in range(regions):
            region = f"DEMO_REGION_{index + 1:02d}"
            for n in range(rng.choice((0, 1, 1, 2))):
                local = [inst for inst, reg in coi_region.items() if reg == region]
                institution = local[0] if local and rng.random() < coi_share else uuid5(
                    NAMESPACE_URL, f"SIH26262:DEMO:EVC:benchmark:inst:{region}:{day}:{n}")
                request_id = uuid5(NAMESPACE_URL, f"SIH26262:DEMO:EVC:benchmark:request:{seed}:{day}:{region}:{n}")
                earliest = start + timedelta(days=day)
                window = tuple(f for f in availability if earliest <= f.date <= end)
                eligibility = EligibilityRequest(request_id, institution, region.capitalize(), "aph-2024-27@r1", earliest,
                                                 earliest + timedelta(days=WINDOW_DAYS), expert_policy, experts, window,
                                                 conflicts.get(institution, frozenset()), frozenset())
                requests.append(SchedulingRequest(SelectorRequest(eligibility, "NEW_PROGRAMME", selector_policy),
                                                  clock_at + timedelta(days=day), allow_late))
    slots = tuple(SchedulingSlot(uuid5(NAMESPACE_URL, f"SIH26262:DEMO:EVC:benchmark:slot:{offset}:{part}"),
                                 start + timedelta(days=offset), part, SLOT_CAPACITY)
                  for offset in range((end - start).days + 1) for part in ("AM", "PM"))
    return SchedulingProblem(tuple(requests), slots, (), start, end, clock_at)


def row(plan, elapsed, extra=None) -> dict:
    m = plan.metrics
    return dict(algorithm=plan.algorithm, scheduled=m.scheduled, unscheduled=m.unscheduled, late_count=m.late_count,
                total_lateness=m.total_lateness, max_lateness=m.max_lateness, total_waiting=m.total_waiting,
                hard_constraint_violations=m.hard_constraint_violations, runtime_seconds=round(elapsed, 2), **(extra or {}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=26262)
    parser.add_argument("--days", type=int, default=40)
    args = parser.parse_args()
    for allow_late in (False, True):
        problem = scenario(args.seed, args.days, allow_late=allow_late)
        started = time.perf_counter()  # benchmark-only timer; never stored as a domain time
        edf = plan_edf(problem)
        edf_time = time.perf_counter() - started
        started = time.perf_counter()
        solved = solve_cpsat(problem)
        cpsat_time = time.perf_counter() - started
        scores = dict(compare_plans(problem, (edf, solved.plan)))  # same fingerprint, recomputed metrics
        print(json.dumps(dict(label="DEMO / SIMULATED", seed=args.seed, requests=len(problem.requests), allow_late=allow_late,
                              horizon_days=(problem.horizon_end - problem.horizon_start).days + 1,
                              results=[row(edf, edf_time), row(solved.plan, cpsat_time, dict(
                                  solver_status=solved.solver_status, repair_rounds=solved.repair_rounds,
                                  fallback_to_edf=solved.fallback_to_edf))],
                              comparison_keys=scores)))


if __name__ == "__main__":
    main()
