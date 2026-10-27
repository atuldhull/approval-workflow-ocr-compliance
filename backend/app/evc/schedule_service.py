"""Transactional EVC scheduling commands: propose a run, publish a run.

Loads EVC-owned facts into the pure scheduler, persists proposals in the
caller's unit of work and rechecks everything again at publication. Panels come
only from the SIMULATED authorised selector (stand-in). No commits here.
"""
from collections import Counter
from dataclasses import replace
from datetime import timedelta
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError

from app.evc.eligibility import AvailabilityFact, EligibilityRequest, ExpertCandidate, eligible_experts
from app.evc.models import Assignment, AssignmentExpert, Availability, Coi, EvcRequest, Expert, ScheduleRun, Slot
from app.evc.pool import policy, same_region
from app.evc.scheduler import Calendar, ScheduleItem, SchedulerParameters, schedule
from app.evc.selector import SELECTOR_LABEL, AssignmentFact, SelectorPolicy, SelectorRequest
from app.platform.registry import port
from contracts.enums import Role
from contracts.errors import Conflict, Forbidden, NotFound, ValidationFailed
from contracts.ports import AuthzPort, CasePort, ClockPort, LedgerPort, UnitOfWork
from contracts.types import EventIn, ResourceRef

PANEL_ROLE = "EVC_PANEL"
SCHEDULABLE = ("QUEUED", "PROPOSED")
LABELS = dict(selector_label=SELECTOR_LABEL, simulation_status="SIMULATED", source_status="DEMO_ASSUMPTION",
              assumption_code="EVC_SCHEDULING_POLICY_UNCONFIRMED")
# Serializes proposal runs so run numbering and draft supersession never interleave.
PROPOSE_LOCK = 26262_0035


def slot_id(day, part) -> UUID:
    """One canonical calendar slot per date/part; capacity lives on that row."""
    return uuid5(NAMESPACE_URL, f"sih26262:evc:slot:{day.isoformat()}:{part}")


def scope_region(principal, region: str | None) -> str | None:
    """RO users schedule only their own region; global roles may name one or none."""
    if principal.role == Role.RO_OFFICER:
        if not principal.region or (region is not None and not same_region(principal.region, region)):
            raise Forbidden("EVC_SCHEDULE_REGION_FORBIDDEN")
        region = principal.region
    port(AuthzPort).check(principal, "evc.schedule.propose", ResourceRef("evc", region=region))
    return region


def _now():
    now = port(ClockPort).now()
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValidationFailed("EVC_CLOCK_MUST_BE_AWARE")
    return now


def _case(session, row, principal):
    case = port(CasePort).lookup(session, row.application_id)
    port(AuthzPort).check(principal, "case.timeline", ResourceRef("application", case.application_id,
                          case.institution_id, case.region))
    if not row.ruleset_key or row.region != case.region or row.institution_ref != case.institution_id:
        raise Conflict("EVC_REQUEST_METADATA_UNAVAILABLE" if not row.ruleset_key else "EVC_CASE_REFERENCE_CHANGED")
    return case


def _policies(row, cache):
    if row.ruleset_key not in cache:
        rules, expert_policy = policy(row.ruleset_key)
        cache[row.ruleset_key] = (rules, expert_policy, SelectorPolicy.from_mapping(rules.expert_pool.get("selector")))
    rules, expert_policy, selector_policy = cache[row.ruleset_key]
    if row.category not in rules.routes:
        raise ValidationFailed("SELECTOR_CATEGORY_UNKNOWN")
    return expert_policy, selector_policy


def _memberships(session, *, exclude_requests=(), published_only=False):
    query = select(AssignmentExpert, Assignment.evc_request_id).join(Assignment, Assignment.id == AssignmentExpert.assignment_id)
    if published_only:
        query = query.where(AssignmentExpert.published.is_(True))
    rows = [(member, request_id) for member, request_id in session.execute(query.order_by(
        AssignmentExpert.assignment_id, AssignmentExpert.expert_id))]
    # Drafts being replaced by this run must not hold time against their own replacement.
    return [m for m, request_id in rows if m.published or request_id not in exclude_requests]


def _snapshot(session, rows, params, *, published_only=False):
    """Immutable inputs for every request, availability covering due_by + lateness allowance."""
    cache = {}
    experts = tuple(ExpertCandidate(e.id, e.user_ref, e.region, tuple(sorted(e.expertise_tags)), e.active)
                    for e in session.scalars(select(Expert).order_by(Expert.id)))
    first = min(r.earliest_date for r in rows)
    last = max(r.due_by for r in rows) + timedelta(days=params.max_lateness_days)
    availability = [AvailabilityFact(a.expert_id, a.date, a.slot_part, a.available) for a in session.scalars(
        select(Availability).where(Availability.date.between(first, last)).order_by(Availability.expert_id, Availability.date, Availability.slot_part))]
    coi = {}
    for c in session.scalars(select(Coi).where(Coi.institution_ref.in_({r.institution_ref for r in rows}))):
        coi.setdefault(c.institution_ref, set()).add((c.expert_id, c.institution_ref))
    members = _memberships(session, exclude_requests={r.id for r in rows}, published_only=published_only)
    history = tuple(AssignmentFact(m.assignment_id, m.expert_id, m.date, m.slot_part) for m in members)
    reservations = frozenset((m.expert_id, m.date, m.slot_part) for m in members)
    items = []
    for row in rows:
        expert_policy, selector_policy = _policies(row, cache)
        end = row.due_by + timedelta(days=params.max_lateness_days)
        eligibility = EligibilityRequest(row.id, row.institution_ref, row.region, row.ruleset_key, row.earliest_date, row.due_by,
            expert_policy, experts, tuple(a for a in availability if row.earliest_date <= a.date <= end),
            frozenset(coi.get(row.institution_ref, ())), frozenset(r for r in reservations if row.earliest_date <= r[1] <= end))
        items.append(ScheduleItem(SelectorRequest(eligibility, row.category, selector_policy, history), row.priority_key))
    return items, _calendar(session, members, first, last)


def _calendar(session, members, first, last) -> Calendar:
    capacity = {(s.date, s.slot_part): s.capacity for s in session.scalars(
        select(Slot).where(Slot.date.between(first, last))) if s.id == slot_id(s.date, s.slot_part)}
    used = Counter()
    for assignment_id, day, part in {(m.assignment_id, m.date, m.slot_part) for m in members}:
        used[(day, part)] += 1
    load = Counter((m.expert_id, m.date) for m in members)
    return Calendar(tuple(sorted(capacity.items())), tuple(sorted(used.items())),
                    tuple(sorted(load.items(), key=lambda row: (str(row[0][0]), row[0][1]))))


def propose(uow: UnitOfWork, *, algorithm: str, region: str | None, params: SchedulerParameters) -> dict:
    session, principal = uow.session, uow.principal
    region = scope_region(principal, region)
    now = _now()
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": PROPOSE_LOCK})
    query = (select(EvcRequest).where(EvcRequest.status.in_(SCHEDULABLE))
             .order_by(EvcRequest.due_by, EvcRequest.priority_key, EvcRequest.requested_at, EvcRequest.id).with_for_update())
    rows = []
    for row in session.scalars(query):
        if region is not None and not same_region(row.region, region):
            continue
        case = _case(session, row, principal)
        if region is not None and not same_region(case.region, region):
            continue
        rows.append(row)
    run_no = (session.scalar(select(func.count()).select_from(ScheduleRun)) or 0) + 1
    run_id = uuid5(NAMESPACE_URL, f"sih26262:evc:run:{now.isoformat()}:{run_no}")
    if rows:
        items, calendar = _snapshot(session, rows, params)
        result = schedule(algorithm, items, calendar, params)
    else:
        result = schedule(algorithm, [], Calendar(), params)
    # Supersede earlier drafts of the requests this run reconsidered; runs left empty are superseded.
    considered = [row.id for row in rows]
    if considered:
        previous = set(session.scalars(select(Assignment.schedule_run_id).where(
            Assignment.evc_request_id.in_(considered), Assignment.published.is_(False))))
        session.execute(delete(Assignment).where(Assignment.evc_request_id.in_(considered), Assignment.published.is_(False)))
        for old in sorted(previous, key=str):
            if session.scalar(select(Assignment.id).where(Assignment.schedule_run_id == old).limit(1)) is None:
                session.execute(update(ScheduleRun).where(ScheduleRun.run_id == old, ScheduleRun.status == "PROPOSED")
                                .values(status="SUPERSEDED"))
    session.add(ScheduleRun(run_id=run_id, algorithm=algorithm, parameters=params.numeric(), created_at=now,
                            status="PROPOSED", metrics=result.metrics))
    session.flush()
    for day, part in sorted({(p.date, p.slot_part) for p in result.proposals}):
        session.execute(text("INSERT INTO evc.slot (id, date, slot_part, capacity) VALUES (:id, :date, :part, :capacity) "
                             "ON CONFLICT (id) DO NOTHING"), dict(id=slot_id(day, part), date=day, part=part,
                                                                 capacity=params.default_slot_capacity))
    proposals = []
    for p in result.proposals:
        assignment_id = uuid5(NAMESPACE_URL, f"sih26262:evc:assignment:{run_id}:{p.request_id}")
        session.add(Assignment(id=assignment_id, evc_request_id=p.request_id, slot_id=slot_id(p.date, p.slot_part),
                               expert_ids=list(p.panel), panel_role=PANEL_ROLE, published=False, schedule_run_id=run_id))
        proposals.append(dict(request_id=p.request_id, assignment_id=assignment_id, slot_id=slot_id(p.date, p.slot_part),
                              date=p.date, slot_part=p.slot_part, expert_ids=list(p.panel), due_by=p.due_by,
                              lateness_days=p.lateness_days))
    proposed = {p.request_id for p in result.proposals}
    for row in rows:
        row.status = "PROPOSED" if row.id in proposed else "QUEUED"
    session.flush()
    unscheduled = [dict(request_id=e.request_id, reason_code=e.reason_code, slots_considered=e.slots_considered,
                        best_qualified_count=e.best_qualified_count, panel_size=e.panel_size,
                        slot_reasons=dict(e.slot_reasons)) for e in result.unscheduled]
    region_code = region.upper() if region else None
    port(LedgerPort).append(uow, EventIn(aggregate_type="evc_schedule_run", aggregate_id=run_id,
        event_type="evc.schedule_proposed", payload=dict(run_id=run_id, algorithm=algorithm, region_scope=region_code,
            proposals=[{k: v.isoformat() if k == "date" else v for k, v in p.items() if k != "due_by"} for p in proposals],
            unscheduled=[dict(request_id=u["request_id"], reason_code=u["reason_code"]) for u in unscheduled],
            scheduled_count=len(proposals), unscheduled_count=len(unscheduled),
            total_lateness_days=result.metrics["total_lateness_days"], **LABELS)))
    return dict(run_id=run_id, algorithm=algorithm, status="PROPOSED", region_scope=region_code, created_at=now,
                parameters=params.numeric(), metrics=result.metrics, proposals=proposals, unscheduled=unscheduled, **LABELS)


def publish(uow: UnitOfWork, run_id: UUID) -> dict:
    """Atomically publish every draft of one run after rechecking it; any failure publishes nothing."""
    session, principal = uow.session, uow.principal
    port(AuthzPort).check(principal, "evc.schedule.publish", ResourceRef("evc", run_id))
    _now()
    run = session.get(ScheduleRun, run_id, with_for_update=True)
    if run is None:
        raise NotFound("EVC_RUN_NOT_FOUND")
    if run.status != "PROPOSED":
        raise Conflict("EVC_RUN_NOT_PUBLISHABLE")
    drafts = list(session.scalars(select(Assignment).where(Assignment.schedule_run_id == run_id,
                                                           Assignment.published.is_(False)).order_by(Assignment.id)))
    if not drafts:
        raise Conflict("EVC_RUN_EMPTY")
    slots = {s.id: s for s in session.scalars(select(Slot).where(Slot.id.in_({a.slot_id for a in drafts}))
                                              .order_by(Slot.id).with_for_update())}
    rows = {r.id: r for r in session.scalars(select(EvcRequest).where(EvcRequest.id.in_({a.evc_request_id for a in drafts}))
                                             .order_by(EvcRequest.id).with_for_update())}
    params = SchedulerParameters(**{k: v for k, v in run.parameters.items()})
    for row in rows.values():
        if row.status != "PROPOSED":
            raise Conflict("EVC_REQUEST_NOT_PROPOSED")
        _case(session, row, principal)
    items, _ = _snapshot(session, list(rows.values()), params, published_only=True)
    items = {item.id: item for item in items}
    published = _memberships(session, published_only=True)
    taken = {(m.expert_id, m.date, m.slot_part) for m in published}
    slot_use = Counter()
    for assignment_id, day, part in {(m.assignment_id, m.date, m.slot_part) for m in published}:
        slot_use[(day, part)] += 1
    day_load = Counter((m.expert_id, m.date) for m in published)
    for draft in drafts:
        slot = slots[draft.slot_id]
        item = items[draft.evc_request_id]
        if len(draft.expert_ids) != item.selector.policy.panel_size:
            raise Conflict("EVC_PUBLISH_RECHECK_FAILED")
        if any((expert, slot.date, slot.slot_part) in taken for expert in draft.expert_ids):
            raise Conflict("EVC_EXPERT_DOUBLE_BOOKED")
        eligibility = item.selector.eligibility
        widened = replace(eligibility, due_by=eligibility.due_by + timedelta(days=params.max_lateness_days))
        tags = set(item.selector.policy.tags_for(item.selector.category))
        allowed = {e.id for e in eligible_experts(widened, slot.date, slot.slot_part)
                   if len(tags & set(e.expertise_tags)) >= item.selector.policy.minimum_expertise_matches}
        if not set(draft.expert_ids) <= allowed:
            raise Conflict("EVC_PUBLISH_RECHECK_FAILED")
        slot_use[(slot.date, slot.slot_part)] += 1
        if slot_use[(slot.date, slot.slot_part)] > slot.capacity:
            raise Conflict("EVC_SLOT_CAPACITY_EXHAUSTED")
        for expert in draft.expert_ids:
            taken.add((expert, slot.date, slot.slot_part))
            day_load[(expert, slot.date)] += 1
            if day_load[(expert, slot.date)] > params.expert_daily_capacity:
                raise Conflict("EVC_EXPERT_CAPACITY_EXHAUSTED")
    try:
        session.execute(update(Assignment).where(Assignment.id.in_([d.id for d in drafts])).values(published=True))
        session.flush()
    except IntegrityError as exc:
        if getattr(getattr(exc.orig, "diag", None), "constraint_name", None) == "uq_evc_published_expert_time":
            raise Conflict("EVC_EXPERT_DOUBLE_BOOKED") from None
        raise
    for row in rows.values():
        row.status = "PUBLISHED"
    run.status = "PUBLISHED"
    session.flush()
    result = []
    for draft in drafts:
        slot, row = slots[draft.slot_id], rows[draft.evc_request_id]
        entry = dict(run_id=run_id, algorithm=run.algorithm, application_id=row.application_id, request_id=row.id,
                     assignment_id=draft.id, slot_id=slot.id, date=slot.date.isoformat(), slot_part=slot.slot_part,
                     due_by=row.due_by.isoformat(), lateness_days=max((slot.date - row.due_by).days, 0),
                     expert_ids=list(draft.expert_ids), panel_role=draft.panel_role, **LABELS)
        port(LedgerPort).append(uow, EventIn(aggregate_type="application", aggregate_id=row.application_id,
            event_type="evc.assignment_published", ruleset_rev=row.ruleset_key, payload=entry))
        result.append(entry)
    return dict(run_id=run_id, algorithm=run.algorithm, status="PUBLISHED", published_count=len(result),
                assignments=result, **LABELS)
