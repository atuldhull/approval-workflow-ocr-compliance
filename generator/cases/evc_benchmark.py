"""EDF vs CP-SAT EVC date scheduling on the seeded DEMO pool; pure, no database.

Experts, availability and COIs come from seed_evc_demo.demo_rows (30 fictional
experts, 60 days, 3 COIs). Requests are synthetic and seeded: per DEMO region and
day, 0-2 arrivals with a 7-day window (the EVC_PROCESSING DEMO ASSUMPTION), and a
share of requests from the three COI institutions. Panels always come from the
SIMULATED authorised selector (stand-in); the algorithms only choose dates.
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
from app.evc.scheduler import Calendar, ScheduleItem, SchedulerParameters, schedule  # noqa: E402
from app.evc.selector import SelectorPolicy, SelectorRequest  # noqa: E402
from generator.cases.scale_generator import LogicalClock  # noqa: E402
from generator.cases.seed_evc_demo import demo_rows  # noqa: E402

AT = "2026-07-01T04:30:00Z"
WINDOW_DAYS = 7
INSTITUTIONS = [uuid5(NAMESPACE_URL, f"SIH26262:DEMO:EVC:benchmark:institution:{i}") for i in range(3)]


def policies():
    raw = yaml.safe_load((ROOT / "rulesets" / "aph-2024-27" / "r1" / "routes.yaml").read_text(encoding="utf-8"))["expert_pool"]
    return ExpertPolicy.from_mapping(raw), SelectorPolicy.from_mapping(raw["selector"])


def scenario(seed: int = 26262, arrival_days: int = 40, coi_share: float = 0.35, max_lateness_days: int = 0,
             regions: int = 9) -> list[ScheduleItem]:
    """Deterministic synthetic queue over the seeded DEMO pool (fictional data only)."""
    rows = demo_rows(LogicalClock(AT), INSTITUTIONS)
    expert_policy, selector_policy = policies()
    experts = tuple(sorted((ExpertCandidate(r["id"], r["user_ref"], r["region"], tuple(sorted(r["expertise_tags"])), r["active"])
                            for r in rows["experts"]), key=lambda e: e.id.int))
    availability = [AvailabilityFact(r["expert_id"], r["date"], r["slot_part"], r["available"]) for r in rows["availability"]]
    coi_region = {c["institution_ref"]: next(e.region for e in experts if e.id == c["expert_id"]) for c in rows["coi"]}
    conflicts = {inst: frozenset((c["expert_id"], inst) for c in rows["coi"] if c["institution_ref"] == inst) for inst in INSTITUTIONS}
    start = datetime.fromisoformat(AT.replace("Z", "+00:00")).astimezone(timezone.utc).date()
    rng = random.Random(seed)
    items = []
    for day in range(arrival_days):
        for index in range(regions):
            region = f"DEMO_REGION_{index + 1:02d}"
            for n in range(rng.choice((0, 1, 1, 2))):
                local = [inst for inst, reg in coi_region.items() if reg == region]
                institution = local[0] if local and rng.random() < coi_share else uuid5(
                    NAMESPACE_URL, f"SIH26262:DEMO:EVC:benchmark:inst:{region}:{day}:{n}")
                request_id = uuid5(NAMESPACE_URL, f"SIH26262:DEMO:EVC:benchmark:request:{seed}:{day}:{region}:{n}")
                earliest = start + timedelta(days=day)
                due = earliest + timedelta(days=WINDOW_DAYS)
                last = due + timedelta(days=max_lateness_days)
                window = tuple(f for f in availability if earliest <= f.date <= last)
                eligibility = EligibilityRequest(request_id, institution, region.capitalize(), "aph-2024-27@r1", earliest, due,
                                                 expert_policy, experts, window, conflicts.get(institution, frozenset()), frozenset())
                items.append(ScheduleItem(SelectorRequest(eligibility, "NEW_PROGRAMME", selector_policy), f"{earliest}:{request_id}"))
    return items


def run(algorithm: str, items, params: SchedulerParameters) -> dict:
    started = time.perf_counter()  # benchmark-only timer; never stored as a domain time
    result = schedule(algorithm, items, Calendar(), params)
    elapsed = time.perf_counter() - started
    m = result.metrics
    return dict(algorithm=algorithm, scheduled=m["scheduled_count"], unscheduled=m["unscheduled_count"],
                total_lateness_days=m["total_lateness_days"], late_count=m["late_count"],
                total_start_offset_days=m["total_start_offset_days"], runtime_seconds=round(elapsed, 2),
                reasons={k: v for k, v in m.items() if k.startswith("reason_") and v},
                **{k: m[k] for k in ("solver_status", "fallback_to_edf", "repair_rounds") if k in m})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=26262)
    parser.add_argument("--days", type=int, default=40)
    parser.add_argument("--lateness", type=int, nargs="*", default=[0, 7])
    args = parser.parse_args()
    for lateness in args.lateness:
        params = SchedulerParameters(max_lateness_days=lateness)
        items = scenario(args.seed, args.days, max_lateness_days=lateness)
        print(json.dumps(dict(label="DEMO / SIMULATED", seed=args.seed, requests=len(items), max_lateness_days=lateness,
                              results=[run(a, items, params) for a in ("EDF", "CPSAT")])))


if __name__ == "__main__":
    main()
