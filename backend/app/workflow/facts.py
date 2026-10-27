"""Trusted server-side guard facts for the running app.

Every value comes from persisted records owned by the workflow (committee workspace, stage visits, pinned
transition definitions, the application row) or from a port (EvcPort, ClockPort). The command payload is never a
source of truth here: where a payload value is echoed into a fact (letter references), the guard and the
receiving module validate it independently. Facts with no record yet either use a pinned, labelled DEMO
ASSUMPTION from routes.yaml (guard_facts) or stay unknown so the guard refuses with a precise reason code.
See docs/p1/ASSUMPTIONS.md, GF-001..GF-006.
"""
from collections import Counter
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.intake.models import Application
from app.platform.registry import port
from app.workflow.commands import Command, GuardFacts, LetterPayload, WorkflowValidationFailed
from app.workflow.models import (
    CaseState, Committee, CommitteeMember, ReportVersion, RouteDefinition, Ruleset, TransitionDefinition,
)
from app.workflow.storage import visits
from contracts.ports import ClockPort, UnitOfWork

IST = ZoneInfo("Asia/Kolkata")

# GF-001 (DEMO ASSUMPTION): which committee workspace types staff each stage. RESCRUTINY/DEFICIENT are auxiliary
# stages of SCRUTINY, so the scrutiny committee keeps its assignment there. SELF_DISCLOSURE has no committee type
# of its own in the workspace vocabulary; its review is staffed by a SCRUTINY workspace.
COMMITTEE_TYPES = {
    "SCRUTINY": ("SCRUTINY",), "DEFICIENT": ("SCRUTINY", "RESCRUTINY"), "RESCRUTINY": ("RESCRUTINY", "SCRUTINY"),
    "SELF_DISCLOSURE": ("SCRUTINY",), "EVC": ("EVC",), "SHC": ("SHC",), "EC": ("EC",), "COUNCIL": ("COUNCIL",),
}


def _committees(session, case: CaseState) -> list[Committee]:
    return list(session.scalars(select(Committee).where(Committee.application_id == case.application_id)
                                .order_by(Committee.id)))


def has_assignment(session, case: CaseState, command: Command, committees: list[Committee]) -> bool:
    """GF-001: the actor is a member of an ACTIVE committee of a type that staffs the case's current stage."""
    types = COMMITTEE_TYPES.get(case.current_stage or "", ())
    candidates = [c.id for c in committees if c.status == "ACTIVE" and c.type in types]
    if not candidates:
        return False
    return session.scalar(select(CommitteeMember.user_ref).where(
        CommitteeMember.committee_id.in_(candidates), CommitteeMember.user_ref == command.actor.user_id).limit(1)) is not None


def applicability(session, case: CaseState, committees: list[Committee]) -> dict[str, bool]:
    """GF-002: an as_applicable stage applies once a committee workspace of that type was formed for the case."""
    route = session.scalar(select(RouteDefinition).where(RouteDefinition.ruleset_key == case.ruleset_key,
                                                         RouteDefinition.route_id == case.route_id))
    if route is None:
        return {}
    formed = {c.type for c in committees}
    return {s["stage"]: s["stage"] in formed for s in route.stage_list if s.get("when") == "as_applicable"}


def decision_refs(session, case: CaseState, committees: list[Committee]) -> frozenset:
    """GF-003: the head report version of each ACTIVE committee staffing the current stage is a citable decision."""
    types = COMMITTEE_TYPES.get(case.current_stage or "", ())
    refs = set()
    for committee in committees:
        if committee.status != "ACTIVE" or committee.type not in types:
            continue
        head = session.scalar(select(ReportVersion.id).where(ReportVersion.committee_id == committee.id)
                              .order_by(ReportVersion.version_no.desc()).limit(1))
        if head is not None:
            refs.add(head)
    return frozenset(refs)


def confirmed_letter(session, case: CaseState, command: Command) -> LetterPayload | None:
    """GF-004: academic year comes from the application; a PORTAL_EVENT issue date is today's IST date from
    ClockPort (no back- or forward-dating). Type/lists_deficiencies are checked against the transition by
    letter_type_matches_decision; f_no and CONFIRMED_FACT provenance are validated by CompliancePort."""
    letter = command.payload.letter
    if letter is None:
        return None
    application = session.get(Application, case.application_id)
    if application is None:
        return None
    issue_date = letter.issue_date
    if letter.issue_date_source == "PORTAL_EVENT":
        now = port(ClockPort).now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise WorkflowValidationFailed("CLOCK_MUST_BE_AWARE")
        issue_date = now.astimezone(IST).date()
    return letter.model_copy(update={"academic_year": application.academic_year, "issue_date": issue_date})


def live_clock_rules(session, case: CaseState) -> frozenset[str]:
    """GF-005: clocks this workflow opened and has not closed, replayed from its own stage visits and the
    pinned transition timers (P2's deadline tables are not read: TG-004)."""
    if case.status == "DRAFT":
        return frozenset()
    route = session.scalar(select(RouteDefinition).where(RouteDefinition.ruleset_key == case.ruleset_key,
                                                         RouteDefinition.route_id == case.route_id))
    if route is None:
        raise WorkflowValidationFailed("CLOCK_CONTEXT_UNAVAILABLE")
    timers: dict[tuple[str, str], list] = {}
    for row in session.scalars(select(TransitionDefinition).where(TransitionDefinition.route_def_id == route.id)):
        known = timers.setdefault((row.from_stage, row.action), row.timers)
        if known != row.timers:
            raise WorkflowValidationFailed("CLOCK_CONTEXT_UNAVAILABLE")
    applied = [("DRAFT", "submit")] + [(stage, (outcome or "").lower()) for stage, outcome in session.execute(
        select(visits.c.stage, visits.c.outcome).where(visits.c.application_id == case.application_id,
                                                       visits.c.exited_at.is_not(None)))]
    balance: Counter[str] = Counter()
    for key in applied:
        if key not in timers:
            raise WorkflowValidationFailed("CLOCK_CONTEXT_UNAVAILABLE")
        for timer in timers[key]:
            if timer["op"] == "open":
                balance[timer["rule_id"]] += 1
            elif timer["op"] == "close" and balance[timer["rule_id"]] > 0:
                balance[timer["rule_id"]] -= 1
    return frozenset(rule for rule, count in balance.items() if count > 0)


def second_approval_required(session, case: CaseState) -> bool | None:
    """GF-006: pinned DEMO ASSUMPTION policy; unknown (refuse) for rulesets pinned without it."""
    metadata = session.scalar(select(Ruleset.source_metadata).where(Ruleset.key == case.ruleset_key))
    policy = (metadata or {}).get("guard_facts")
    return None if policy is None else policy["revert_second_approval_required"]


def load(uow: UnitOfWork, case: CaseState, command: Command) -> GuardFacts:
    """Default trusted loader. Checklist/DSC, deficiency and EVC facts are added by guards.read_facts."""
    session = uow.session
    committees = _committees(session, case)
    return GuardFacts(
        has_assignment=has_assignment(session, case, command, committees),
        applicability=applicability(session, case, committees),
        decision_refs=decision_refs(session, case, committees),
        confirmed_letter=confirmed_letter(session, case, command),
        live_clock_rules=live_clock_rules(session, case),
        second_approval_required=second_approval_required(session, case),
        # GF-006: no approver directory exists (P3 user master has no lookup port), so a required second
        # approval stays unknown and the guard refuses with APPROVAL_CONTEXT_UNAVAILABLE.
        second_approver_refs=None,
    )
