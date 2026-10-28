"""Deterministic fictional DEMO scenarios; no database access or wall-clock reads."""
import argparse
from collections import Counter
from datetime import datetime, time, timedelta, timezone
import json
from pathlib import Path
import random
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

import yaml

from generator.cases.answer_key_models import AnswerKey

ROOT = Path(__file__).resolve().parents[2]
RULESET = "aph-2024-27@r1"
VERSION = "1.1.0"
EPOCH = "2026-07-01T04:30:00Z"


def instant(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class LogicalClock:
    """ClockPort-compatible scenario clock; explicitly controlled, never real time."""

    def __init__(self, at: str = EPOCH):
        self._at = datetime.fromisoformat(at.replace("Z", "+00:00"))
        if self._at.tzinfo is None:
            raise ValueError("logical clock must be timezone-aware")

    def now(self) -> datetime:
        return self._at

    def move_to(self, at: str) -> None:
        target = datetime.fromisoformat(at.replace("Z", "+00:00"))
        if target.tzinfo is None or target < self._at:
            raise ValueError("logical clock cannot move backwards")
        self._at = target

    def tick(self, seconds: int = 1) -> str:
        if seconds < 0:
            raise ValueError("negative logical step")
        self._at += timedelta(seconds=seconds)
        return instant(self.now())


def identity(seed: int, kind: str, index: object) -> str:
    return str(uuid5(NAMESPACE_URL, f"SIH26262:DEMO:scale:{seed}:{kind}:{index}"))


def canonical(value: dict) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode("utf-8")


def sources() -> tuple[dict, dict, dict]:
    base = ROOT / "rulesets/aph-2024-27/r1"
    routes = yaml.safe_load((base / "routes.yaml").read_text(encoding="utf-8"))
    deadlines = yaml.safe_load((base / "deadlines.yaml").read_text(encoding="utf-8"))
    checklists = yaml.safe_load((base / "checklists.yaml").read_text(encoding="utf-8"))
    return routes, {r["id"]: r for r in deadlines["rules"]}, checklists


def generate(seed: int, institutions: int = 300, applications: int = 600,
             regions: int = 9) -> tuple[dict, dict]:
    """Return API input manifest and validated answer key for one pinned scenario."""
    for name, value, minimum in (("seed", seed, 0), ("institutions", institutions, 1),
                                 ("applications", applications, 1), ("regions", regions, 1)):
        if type(value) is not int or value < minimum:
            raise ValueError(f"{name} must be an integer >= {minimum}")
    if regions > institutions or regions > 9:
        raise ValueError("regions must be <= institutions and <= 9")
    rng = random.Random(seed)
    raw, deadlines, checklists = sources()
    # Applications filed by institutions; AICTE-initiated visits (initiated_by: AICTE, the Only-EVC routes) are not
    # part of the application mix.
    categories = sorted(c for c, route in raw["routes"].items() if route.get("initiated_by") != "AICTE")
    # Equal weights, Hamilton allocation: at most one application separates categories.
    mix = [category for i, category in enumerate(categories)
           for _ in range(applications // len(categories) + (i < applications % len(categories)))]
    rng.shuffle(mix)
    master = [{"id": identity(seed, "institution", i), "name": f"DEMO Institute {seed:06d}-{i:04d}",
               "region": f"DEMO_REGION_{i % regions + 1:02d}", "ro_id": f"DEMO_RO_{i % regions + 1:02d}",
               "category": "DEMO_TECHNICAL", "label": "DEMO"} for i in range(institutions)]
    clock = LogicalClock()
    workflows, apps, scenarios, clocks = [], [], [], []

    def clock_op(app_id, operation, rule_id, at, **extra):
        rule = deadlines[rule_id]
        entry = dict(id=identity(seed, "clock", len(clocks)), application_id=app_id,
                     subject_type="application", subject_id=app_id, rule_id=rule_id,
                     clock_kind=rule["clock_kind"], clock_owner=rule["clock_owner"],
                     at_clock=at, basis="DEMO_ASSUMPTION", operation=operation, **extra)
        if operation == "OPEN":
            duration = rule["duration"]
            if duration["unit"] != "calendar_days":
                raise ValueError("generator supports configured calendar-day clocks only")
            anchor = datetime.fromisoformat(at.replace("Z", "+00:00"))
            due = anchor.astimezone(ZoneInfo("Asia/Kolkata")).date() + timedelta(days=duration["value"])
            entry.update(anchor_at_clock=at, expected_due_date=due.isoformat(),
                         expected_due_at_clock=instant(datetime.combine(due, time(23, 59, 59), ZoneInfo("Asia/Kolkata"))))
        clocks.append(entry)

    for index, category in enumerate(mix):
        evc_rule = raw["routes"][category].get("evc_rule_id", raw["evc"]["rule_id"])  # a route's own EVC timeline
        app_id = identity(seed, "application", index)
        institution = master[index % institutions]
        stage_list = [dict(stage=s, when="always") if isinstance(s, str) else dict(s)
                      for s in raw["routes"][category]["stages"]]
        shc = bool(rng.randrange(2))
        plan = [s["stage"] for s in stage_list if s["when"] == "always" or shc]
        rounds = rng.randrange(4) if "SCRUTINY" in plan else 0
        outcome = rng.choice(["REJECTED", "WITHDRAWN"])
        app = dict(id=app_id, institution_id=institution["id"], category=category,
                   route_id=category, pinned_ruleset_key=RULESET, label="DEMO")
        apps.append(app)
        operations, visited, loops, late, delays = [], [plan[0]], [], [], []

        def operation(kind, action=None, **fields):
            at = clock.tick()
            operations.append(dict(kind=kind, at_clock=at, **({"action": action} if action else {}), **fields))
            return at

        submitted = operation("action", "submit", payload={"dsc_present": True})
        clock_op(app_id, "OPEN", "AICTE_PROCESSING", submitted)
        for position, stage in enumerate(plan):
            if stage == "SCRUTINY" and rounds:
                opened = operation("action", "record_deficiency", payload={"item_keys": ["DEMO_CORE_REFERENCE"]})
                visited.append("DEFICIENT")
                for number in range(rounds):
                    clock_op(app_id, "PAUSE", "AICTE_PROCESSING", opened)
                    clock_op(app_id, "OPEN", "INSTITUTION_RESPONSE", opened)
                    loop_id = identity(seed, "loop", f"{index}:{number}")
                    response_id = identity(seed, "response", f"{index}:{number}")
                    item_id = identity(seed, "item", f"{index}:{number}")
                    response_days = 17 if rng.randrange(2) else 2
                    clock.tick(response_days * 86400)
                    responded = operation("compliance", response_ref=response_id)
                    visited.append("RESCRUTINY")
                    clock_op(app_id, "CLOSE", "INSTITUTION_RESPONSE", responded, outcome="MET")
                    clock_op(app_id, "RESUME", "AICTE_PROCESSING", responded)
                    accepted = number == rounds - 1
                    reviewed = operation("review", state="ACCEPTED" if accepted else "REJECTED")
                    loops.append(dict(id=loop_id, recorded_at_clock=opened, as_of_clock=reviewed,
                        response_id=response_id, responded_at_clock=responded,
                        items=[dict(id=item_id, status="RESOLVED" if accepted else "OPEN",
                            resolved_at_clock=responded if accepted else None,
                            resolution_response_id=response_id if accepted else None)]))
                    # P2's existing demo response deadline is end-of-day IST.
                    due = next(c["expected_due_at_clock"] for c in reversed(clocks)
                               if c["rule_id"] == "INSTITUTION_RESPONSE" and c["operation"] == "OPEN")
                    if responded > due:
                        seconds = int((datetime.fromisoformat(responded.replace("Z", "+00:00")) -
                                       datetime.fromisoformat(due.replace("Z", "+00:00"))).total_seconds())
                        late.append(dict(response_id=response_id, loop_id=loop_id, expected_by_clock=due,
                                         responded_at_clock=responded, late_by_seconds=seconds))
                    if not accepted:
                        opened = reviewed  # review creates the next round atomically
                        visited.append("DEFICIENT")
                if position + 1 < len(plan):
                    visited.append(plan[position + 1])  # final acceptance advances via YAML
                    continue
            if stage == "EVC":
                clock_op(app_id, "OPEN", evc_rule, instant(clock.now()))
                planned = instant(clock.now())
                delay_seconds = rng.randint(1, 4) * 86400
                clock.tick(delay_seconds)
                # The next command (advance or terminal outcome) ends the EVC hold.
                actual = instant(clock.now() + timedelta(seconds=1))
                delays.append(dict(request_id=identity(seed, "evc", index), planned_at_clock=planned,
                                   actual_at_clock=actual, delay_seconds=delay_seconds + 1))
            if position + 1 < len(plan):
                advanced = operation("action", "advance", payload={})
                if stage == "EVC":
                    clock_op(app_id, "CLOSE", evc_rule, advanced, outcome="MET")
                visited.append(plan[position + 1])
        terminal = operation("action", "reject" if outcome == "REJECTED" else "withdraw", payload={})
        if plan[-1] == "EVC":
            clock_op(app_id, "CLOSE", evc_rule, terminal, outcome="WAIVED")
        clock_op(app_id, "CLOSE", "AICTE_PROCESSING", terminal, outcome="MET")
        workflows.append(dict(application_id=app_id, deficiency_loop_count=len(loops), deficiency_loops=loops,
            late_responses=late, evc_delays=delays, letters_to_issue=[], route_outcome=dict(at_clock=terminal,
                expected_stage_list=stage_list, expected_visited_stages=visited, expected_status=outcome)))
        scenarios.append(dict(application_id=app_id, academic_year="2027-28", shc_applicable=shc,
                              item_keys=sorted(item["item_key"] for item in checklists["checklists"][category]["items"] if item["mandatory"]),
                              operations=operations))
    counts = dict(institutions=institutions, applications=applications, deficiency_loops=sum(len(w["deficiency_loops"]) for w in workflows),
                  deficiency_items=sum(len(loop["items"]) for w in workflows for loop in w["deficiency_loops"]),
                  late_responses=sum(len(w["late_responses"]) for w in workflows), evc_delays=sum(len(w["evc_delays"]) for w in workflows),
                  letters=0, clock_expectations=len(clocks))
    answer = AnswerKey.model_validate(dict(header=dict(schema_version="0.1.0", review_status="PROPOSED_TEAM_REVIEW",
        label="DEMO", seed=seed, generator_version=VERSION, ruleset_key=RULESET, generated_at_clock=EPOCH, counts=counts),
        institutions=[{k: v for k, v in i.items() if k != "name"} for i in master], applications=apps,
        workflow_expectations=workflows, clock_expectations=clocks, p2_extensions={}, p3_extensions={})).model_dump(mode="json")
    data = dict(label="DEMO", simulation_status="SIMULATED", generator_version=VERSION, seed=seed,
                ruleset_key=RULESET, generated_at_clock=EPOCH, institutions=master, applications=apps, scenarios=scenarios,
                category_counts=dict(sorted(Counter(mix).items())))
    return data, answer


def write_seed(out: Path, seed: int, institutions: int = 300, applications: int = 600, regions: int = 9) -> None:
    data, answer = generate(seed, institutions, applications, regions)
    out.mkdir(parents=True, exist_ok=True)
    for name, value in (("seed_data.json", data), ("answer_key.json", answer)):
        path = out / name
        if path.exists():
            raise FileExistsError(f"refusing to overwrite {path}")
    (out / "seed_data.json").write_bytes(canonical(data))
    (out / "answer_key.json").write_bytes(canonical(answer))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--institutions", type=int, default=300)
    parser.add_argument("--applications", type=int, default=600)
    parser.add_argument("--regions", type=int, default=9)
    args = parser.parse_args()
    try:
        write_seed(args.out, args.seed, args.institutions, args.applications, args.regions)
    except (ValueError, FileExistsError) as exc:
        parser.error(str(exc))
    print(f"DEMO seed {args.seed}: {args.applications} applications written to {args.out}")


if __name__ == "__main__":
    main()
