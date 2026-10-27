"""Static workflow grammar. Expands YAML templates; never executes a command."""
from dataclasses import dataclass
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from contracts.enums import ApplicationStatus, ClockKind, LetterType, Role
from contracts.errors import ValidationFailed
from contracts.types import Route

ACTIONS = frozenset({
    "submit", "advance", "record_deficiency", "submit_compliance", "start_rescrutiny",
    "advance_to_evc", "complete_evc", "advance_to_shc", "issue_loa", "issue_eoa",
    "issue_lod", "reject", "withdraw", "revert",
})
ALIASES = {"scrutinise": "advance", "complete": "advance", "authorised_revert": "revert"}
GUARDS = frozenset({
    "evc_request_open",
    "application_is_draft", "open_items_zero", "actor_has_assignment", "reason_code_present",
    "deficiency_items_present", "response_received", "at_last_applicable_stage",
    "decision_authorised", "letter_type_matches_decision", "previous_stage_visited",
    "second_approval_if_required", "checklist_complete", "dsc_required",
})
TERMINALS = frozenset({ApplicationStatus.APPROVED, ApplicationStatus.REJECTED, ApplicationStatus.WITHDRAWN})


class GrammarRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Timer(GrammarRecord):
    op: Literal["open", "close", "pause_internal", "resume_internal"]
    rule_id: str
    anchor: Literal["command.now", "letter.issue_date"] | None
    outcome: Literal["MET", "WAIVED"] | None = None
    if_live: bool = Field(default=False, strict=True)


class Letter(GrammarRecord):
    type: LetterType
    lists_deficiencies: bool = Field(strict=True)


class Transition(GrammarRecord):
    action: str
    from_stage: str | list[str]
    to_stage: str
    allowed_roles: list[Role] = Field(min_length=1)
    guards: list[str]
    reason_codes_required: bool = Field(strict=True)
    timers: list[Timer]
    emits_event: str = Field(pattern=r"^(wf|evc)\.[a-z][a-z0-9_]*$")
    letter: Letter | None
    aliases: list[str] = Field(default_factory=list)
    requires_stages: list[str] = Field(default_factory=list)
    match_to: str | None = None


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    template: str
    transition: Transition


@dataclass(frozen=True)
class WorkflowDefinition:
    terminals: tuple[str, ...]
    routes: dict[str, tuple[Edge, ...]]


def _fail(message: str) -> None:
    raise ValidationFailed(message)


def _mapping(value: Any, label: str) -> dict:
    if not isinstance(value, dict):
        _fail(f"{label}: expected mapping")
    return value


def _names(value: Any, label: str, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        _fail(f"{label}: expected list of names")
    if (not allow_empty and not value) or len(value) != len(set(value)):
        _fail(f"{label}: empty or duplicate names")
    return value


def _timer_checks(t: Transition, deadlines: dict, name: str) -> None:
    for timer in t.timers:
        if timer.rule_id not in deadlines:
            _fail(f"{name}: unknown timer rule_id {timer.rule_id}")
        rule = deadlines[timer.rule_id]
        kind = rule.get("clock_kind") if isinstance(rule, dict) else getattr(rule, "clock_kind", None)
        if timer.op in {"pause_internal", "resume_internal"} and kind != ClockKind.INTERNAL:
            _fail(f"{name}: cannot pause/resume non-INTERNAL rule {timer.rule_id}")
        if (timer.anchor is not None) != (timer.op == "open"):
            _fail(f"{name}: open needs an anchor; other timer operations require null")
        if (timer.outcome is not None) != (timer.op == "close"):
            _fail(f"{name}: close needs outcome; other timer operations forbid outcome")
        if timer.anchor == "letter.issue_date" and t.letter is None:
            _fail(f"{name}: letter anchor without letter")
        if timer.if_live and timer.op != "close":
            _fail(f"{name}: if_live is only valid for close")


def _template_checks(t: Transition, known: set[str], deadlines: dict, name: str) -> None:
    if t.action not in ACTIONS:
        _fail(f"{name}: unknown action {t.action}")
    if len(t.aliases) != len(set(t.aliases)) or any(ALIASES.get(alias) != t.action for alias in t.aliases):
        _fail(f"{name}: unknown or mismatched action alias")
    if len(t.guards) != len(set(t.guards)) or set(t.guards) - GUARDS:
        _fail(f"{name}: unknown or duplicate guard")
    sources = [t.from_stage] if isinstance(t.from_stage, str) else t.from_stage
    if not sources or len(sources) != len(set(sources)):
        _fail(f"{name}: empty or duplicate from_stage")
    for stage in sources + t.requires_stages + ([t.match_to] if t.match_to else []):
        if stage not in known | {"DRAFT", "$route", "$active", "$last"}:
            _fail(f"{name}: unknown stage {stage}")
    if t.to_stage not in known | TERMINALS | {"$first", "$next", "$previous"}:
        _fail(f"{name}: unknown stage {t.to_stage}")
    if set(t.requires_stages) - known or (t.match_to is not None and t.match_to not in known):
        _fail(f"{name}: unknown stage in template filter")
    if t.action == "submit" and (sources != ["DRAFT"] or t.to_stage != "$first"):
        _fail(f"{name}: submit must enter $first from DRAFT")
    if "DRAFT" in sources and t.action != "submit":
        _fail(f"{name}: only submit can leave DRAFT")
    if t.action == "revert":
        required = {"reason_code_present", "previous_stage_visited"}
        if not t.reason_codes_required or not required <= set(t.guards) or t.to_stage != "$previous":
            _fail(f"{name}: revert requires reason code, visit guard and $previous")
    elif t.to_stage == "$previous":
        _fail(f"{name}: $previous is reserved for revert")
    if t.action in {"record_deficiency", "reject", "withdraw"} and (
        not t.reason_codes_required or "reason_code_present" not in t.guards
    ):
        _fail(f"{name}: action requires reason code")
    if "$last" in sources and "at_last_applicable_stage" not in t.guards:
        _fail(f"{name}: $last needs at_last_applicable_stage guard")
    if t.action.startswith("issue_"):
        if t.letter is None or t.letter.type != t.action.removeprefix("issue_").upper():
            _fail(f"{name}: letter trigger has no matching letter type")
    if t.letter is not None and "letter_type_matches_decision" not in t.guards:
        _fail(f"{name}: letter requires decision guard")
    _timer_checks(t, deadlines, name)


def _next_stages(names: list[str], conditional: set[str], source: str, resume: dict) -> list[str]:
    anchor = resume.get(source, source)
    if anchor not in names:
        return []
    result = []
    for target in names[names.index(anchor) + 1:]:
        result.append(target)
        if target not in conditional:
            break
    return result


def _expand(route: Route, refs: list[str], templates: dict[str, Transition], auxiliary: dict, resume: dict) -> tuple[Edge, ...]:
    names = [s.stage.value for s in route.stages]
    conditional = {s.stage.value for s in route.stages if s.when == "as_applicable"}
    activated = {k: v for k, v in auxiliary.items() if v in names}
    active = names + list(activated)
    resumed = {k: v for k, v in resume.items() if k in activated}
    last = [s for i, s in enumerate(names) if all(n in conditional for n in names[i + 1:])]
    last += [s for s, anchor in resumed.items() if anchor in last]
    selectors = {"$route": names + list(resumed), "$active": active, "$last": last, "DRAFT": ["DRAFT"]}
    edges = []
    for ref in refs:
        t = templates[ref]
        if not set(t.requires_stages) <= set(names):
            continue
        raw_sources = [t.from_stage] if isinstance(t.from_stage, str) else t.from_stage
        for token in raw_sources:
            sources = selectors.get(token, [token])
            for source in sources:
                if t.to_stage == source and "at_last_applicable_stage" in t.guards and source not in last:
                    continue
                if source not in active + ["DRAFT"]:
                    _fail(f"{route.category}/{ref}: unknown stage {source} in this route")
                if t.to_stage == "$first":
                    targets = [names[0]]
                elif t.to_stage == "$next":
                    targets = _next_stages(names, conditional, source, resumed)
                elif t.to_stage == "$previous":
                    anchor = activated.get(source, source)
                    index = names.index(anchor)
                    targets = names[:index + (source in activated)]
                else:
                    targets = [t.to_stage]
                for target in targets:
                    if t.match_to is not None and target != t.match_to:
                        continue
                    if target not in active and target not in TERMINALS:
                        _fail(f"{route.category}/{ref}: unknown stage {target} in this route")
                    edges.append(Edge(source, target, ref, t))
    return tuple(edges)


def _reachable(start: set[str], edges: tuple[Edge, ...], reverse: bool = False) -> set[str]:
    reached = set(start)
    while True:
        expanded = reached | {
            (edge.source if reverse else edge.target) for edge in edges
            if (edge.target if reverse else edge.source) in reached
        }
        if reached == expanded:
            return reached
        reached = expanded


def validate_workflow(raw: dict, routes: dict[str, Route], deadlines: dict) -> WorkflowDefinition:
    """Reject invalid definitions before registry caching; no shared types change."""
    from contracts.enums import Stage

    if raw.get("grammar_version") != 1 or isinstance(raw.get("grammar_version"), bool):
        _fail("workflow grammar_version must be 1")
    terminal_names = _names(raw.get("terminal_states"), "terminal_states")
    if set(terminal_names) - TERMINALS:
        _fail("unknown terminal state")
    known = set(Stage.__members__)
    auxiliary = _mapping(raw.get("auxiliary_stages", {}), "auxiliary_stages")
    resume = _mapping(raw.get("resume_after", {}), "resume_after")
    for name, anchor in {**auxiliary, **resume}.items():
        if name not in known or not isinstance(anchor, str) or anchor not in known or name == anchor:
            _fail("unknown stage or self-reference in auxiliary/resume mapping")
    if any(auxiliary.get(name) != anchor for name, anchor in resume.items()):
        _fail("resume_after must match auxiliary_stages")
    if set(auxiliary.values()) & auxiliary.keys():
        _fail("auxiliary stage anchors must be plan stages, not auxiliary stages")
    templates = {}
    for name, spec in _mapping(raw.get("templates"), "templates").items():
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", name):
            _fail("invalid template name")
        try:
            templates[name] = Transition.model_validate(spec)
        except ValidationError as exc:
            _fail(f"{name}: invalid transition/letter type: {exc}")
        _template_checks(templates[name], known, deadlines, name)
    default_refs = _names(raw.get("transitions"), "transitions")
    if set(default_refs) - templates.keys():
        _fail("unknown transition template")
    on_submit = _names(raw.get("clocks", {}).get("on_submit", []), "clocks.on_submit", allow_empty=True)
    for name, t in templates.items():
        if t.action == "submit" and ([timer.rule_id for timer in t.timers if timer.op == "open"] != on_submit
                                     or any(timer.op != "open" for timer in t.timers)):
            _fail(f"{name}: submit timers must match clocks.on_submit")
    compiled = {}
    for category, route in routes.items():
        refs = _names(raw["routes"][category].get("transitions"), f"{category}.transitions")
        if set(refs) - templates.keys():
            _fail(f"{category}: unknown transition template")
        if len([ref for ref in refs if templates[ref].action == "submit"]) != 1:
            _fail(f"{category}: exactly one submit transition required")
        names = {s.stage.value for s in route.stages}
        if names & auxiliary.keys():
            _fail(f"{category}: auxiliary stage duplicates a route stage")
        declared = names | {k for k, v in auxiliary.items() if v in names}
        edges = _expand(route, refs, templates, auxiliary, resume)
        if any(e.target in TERMINALS - set(terminal_names) for e in edges):
            _fail(f"{category}: transition targets undeclared terminal")
        reached = _reachable({"DRAFT"}, edges)
        if declared - reached:
            _fail(f"{category}: unreachable stage {sorted(declared - reached)}")
        if not set(terminal_names) & reached:
            _fail(f"{category}: route has no reachable terminal")
        can_finish = _reachable(set(terminal_names), edges, reverse=True)
        if (declared | {"DRAFT"}) - can_finish:
            _fail(f"{category}: stage has no path to terminal")
        compiled[category] = edges
    return WorkflowDefinition(tuple(terminal_names), compiled)
