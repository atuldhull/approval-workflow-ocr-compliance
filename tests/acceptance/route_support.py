"""Test-owned CSV oracle and raw-YAML matcher, separate from engine dispatch."""
import csv
from dataclasses import dataclass
from datetime import date
from itertools import product
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from app.workflow.commands import CaseContext, Command, GuardFacts, LetterPayload, Payload, Spec, State
from app.workflow.grammar import validate_workflow
from app.workflow.registry import _read, parse_routes
from contracts.enums import ApplicationStatus, Role, Stage
from contracts.fakes import FakeDeadlineRuleParser
from contracts.types import Principal, ResourceRef

ROOT = Path(__file__).resolve().parents[2]
R1, R3 = "aph-2024-27@r1", "aph-2024-27@r3-DEMO"
RAW = _read(ROOT / "rulesets/aph-2024-27/r1/routes.yaml")
ROUTES = parse_routes(RAW["routes"])
DEADLINES = FakeDeadlineRuleParser().parse(_read(ROOT / "rulesets/aph-2024-27/r1/deadlines.yaml"))
COMPILED = validate_workflow(RAW, ROUTES, DEADLINES)
DEMO_REF = uuid5(NAMESPACE_URL, "DEMO:route-acceptance-reference")
DECISION_REF = uuid5(NAMESPACE_URL, "DEMO:route-acceptance-decision")
INSTITUTION = uuid5(NAMESPACE_URL, "DEMO:route-acceptance-pure-institution")


@dataclass(frozen=True)
class ExpectedRoute:
    route_id: str
    source_table: str
    evc: bool
    stages: tuple[tuple[str, str], ...]
    source_verification: str
    assumption_ref: str


def read_expected() -> tuple[ExpectedRoute, ...]:
    with (ROOT / "docs/p1/expected_routes.csv").open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    return tuple(ExpectedRoute(row["route_id"], row["source_table"], row["evc"] == "YES",
        tuple((token.rstrip("?"), "as_applicable" if token.endswith("?") else "always")
              for token in row["stages"].split(";")), row["source_verification"], row["assumption_ref"]) for row in rows)


EXPECTED = read_expected()
ALIASES = {alias: template["action"] for template in RAW["templates"].values() for alias in template.get("aliases", [])}
ACTIONS = tuple(sorted({template["action"] for template in RAW["templates"].values()} | set(ALIASES) | {"unknown_action"}))
STAGES = tuple(sorted({stage.value for stage in Stage} | set(RAW["terminal_states"]) | {"DRAFT", "UNKNOWN_STAGE"}))
MATRIX = tuple(product(tuple(RAW["routes"]), STAGES, ACTIONS))


def raw_pair_allowed(category: str, source: str, action: str) -> bool:
    """Existential graph membership from raw selectors, without production expansion."""
    stages = RAW["routes"][category]["stages"]
    names = [stage if isinstance(stage, str) else stage["stage"] for stage in stages]
    optional = {stage["stage"] for stage in stages if isinstance(stage, dict) and stage.get("when") == "as_applicable"}
    auxiliary = {name: anchor for name, anchor in RAW["auxiliary_stages"].items() if anchor in names}
    resumed = {name: anchor for name, anchor in RAW["resume_after"].items() if name in auxiliary}
    if source not in set(names) | set(auxiliary) | {"DRAFT"}:
        return False
    canonical = ALIASES.get(action, action)
    for reference in RAW["routes"][category]["transitions"]:
        template = RAW["templates"][reference]
        if template["action"] != canonical or not set(template.get("requires_stages", [])) <= set(names):
            continue
        tokens = template["from_stage"]
        tokens = [tokens] if isinstance(tokens, str) else tokens
        anchor = resumed.get(source, source)
        last = anchor in names and all(stage in optional for stage in names[names.index(anchor) + 1:])
        matches = any(token == source
                      or token == "$active" and source in set(names) | set(auxiliary)
                      or token == "$route" and source in set(names) | set(resumed)
                      or token == "$last" and source in set(names) | set(resumed) and last for token in tokens)
        if not matches:
            continue
        if template["to_stage"] == source and "at_last_applicable_stage" in template.get("guards", []) and not last:
            continue
        target = template["to_stage"]
        if target == "$next":
            targets = []
            if anchor in names:
                for stage in names[names.index(anchor) + 1:]:
                    targets.append(stage)
                    if stage not in optional:
                        break
        elif target == "$previous":
            prior_anchor = auxiliary.get(source, source)
            targets = names[:names.index(prior_anchor) + int(source in auxiliary)] if prior_anchor in names else []
        elif target == "$first":
            targets = names[:1]
        else:
            targets = [target]
        if any(template.get("match_to") in (None, candidate) for candidate in targets):
            return True
    return False


def specifications(category: str) -> tuple[Spec, ...]:
    result = []
    for index, edge in enumerate(COMPILED.routes[category]):
        value = edge.transition.model_dump(mode="json")
        result.append(Spec(index, value["action"], edge.source, edge.target, tuple(value["allowed_roles"]),
            tuple(value["guards"]), tuple(value["timers"]), value["letter"], value["reason_codes_required"], value, value["emits_event"]))
    return tuple(result)


SPECS = {category: specifications(category) for category in RAW["routes"]}


def core_input(category: str, source: str, action: str):
    canonical = ALIASES.get(action, action)
    candidates = [spec for spec in SPECS[category] if spec.source == source and spec.action == canonical]
    chosen = candidates[0] if candidates else None
    application_id = uuid5(NAMESPACE_URL, f"DEMO:matrix:{category}:{source}:{action}")
    role = Role(chosen.roles[0]) if chosen else Role.BUREAU_OFFICER
    actor = Principal(DEMO_REF, role, institution_id=INSTITUTION)
    letter = LetterPayload(type=chosen.letter["type"], academic_year="2027-28", issue_date=date(2026, 7, 1),
        issue_date_source="PORTAL_EVENT", lists_deficiencies=chosen.letter["lists_deficiencies"]) if chosen and chosen.letter else None
    payload = Payload(dsc_present=True, target_stage=Stage(chosen.target) if chosen and canonical == "revert" else None,
                      item_refs=(DEMO_REF,), response_ref=DEMO_REF, decision_ref=DECISION_REF, letter=letter)
    command = Command(application_id=application_id, action=action, expected_version=1, reason_code="DEMO_ACCEPTANCE", payload=payload, actor=actor)
    status = ApplicationStatus(source) if source in {"DRAFT", *RAW["terminal_states"]} else ApplicationStatus.IN_PROCESS
    state = State(application_id, category, R1, source if status == ApplicationStatus.IN_PROCESS else None, status, 1)
    facts = GuardFacts(evc_request_status="PUBLISHED", missing_item_keys=(), dsc_present=True, dsc_required=True, checklist_complete=True,
        open_item_count=0, has_assignment=True, reason_codes=frozenset({"DEMO_ACCEPTANCE"}),
        item_refs=frozenset({DEMO_REF}), response_refs=frozenset({DEMO_REF}), decision_refs=frozenset({DECISION_REF}),
        confirmed_letter=letter, applicability={"SHC": source == "SHC" or bool(chosen and chosen.target == "SHC")},
        live_clock_rules=frozenset({"AICTE_PROCESSING"}), second_approval_required=False)
    route = tuple((stage.stage.value, stage.when) for stage in ROUTES[category].stages)
    context = CaseContext(state, ResourceRef("application", application_id, INSTITUTION), route, SPECS[category],
                          frozenset(stage for stage, _ in route), facts)
    return context, command, bool(candidates)


def matrix_counts() -> dict[str, int]:
    valid = sum(raw_pair_allowed(*pair) for pair in MATRIX)
    return {"routes": len(RAW["routes"]), "stages": len(STAGES), "actions": len(ACTIONS),
            "total": len(MATRIX), "valid": valid, "invalid": len(MATRIX) - valid}
