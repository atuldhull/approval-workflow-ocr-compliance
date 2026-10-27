from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.intake.models import Application, ApplicationItem, Institution, StageVisit
from app.intake import rules as intake_rules
from app.intake.documents import check_document_refs
from app.intake.shapes import ApplicationChecklistOut, ItemIn, ItemOut, ItemsOut
from app.platform.registry import port
from contracts.enums import ApplicationStatus
from contracts.errors import Conflict, NotFound, ValidationFailed
from contracts.ports import AuthzPort, CasePort, ClockPort, DeadlinePort, LedgerPort, RulesetPort, UnitOfWork
from contracts.types import Anchor, CaseRef, EventIn, ResourceRef, SubjectRef


def create_application(uow: UnitOfWork, institution_id: UUID, category: str, academic_year: str) -> Application:
    port(AuthzPort).check(uow.principal, "application.create",
                          ResourceRef("application", owner_institution_id=institution_id))
    if uow.session.get(Institution, institution_id) is None:
        raise NotFound("institution not found")
    rules = port(RulesetPort)
    rules.route_for(category, rules.default_key())  # rejects categories with no route

    app = Application(institution_id=institution_id, category=category, academic_year=academic_year,
                      status=ApplicationStatus.DRAFT, created_at=port(ClockPort).now())
    uow.session.add(app)
    uow.session.flush()
    port(LedgerPort).append(uow, EventIn(
        aggregate_type="application", aggregate_id=app.id, event_type="wf.application_created",
        payload={"application_id": app.id, "institution_id": institution_id,
                 "category": category, "academic_year": academic_year},
    ))
    return app


def submit_application(uow: UnitOfWork, application_id: UUID, *, dsc_present: bool = False) -> Application:
    """Pins the ruleset, enters the first stage, opens the submit clocks and records it - in one transaction."""
    session = uow.session
    ref = port(CasePort).lookup(session, application_id)
    port(AuthzPort).check(uow.principal, "application.submit",
                          ResourceRef("application", application_id, ref.institution_id, ref.region))
    app = session.get(Application, application_id, with_for_update=True, populate_existing=True)
    if app.status != ApplicationStatus.DRAFT:
        raise Conflict(f"application is already {app.status}")

    rules = port(RulesetPort)
    key = rules.default_key()
    ruleset = rules.get(key)
    route = rules.route_for(app.category, key)
    route_plan = intake_rules.plan(session, app.category, key)
    provided = set(session.scalars(select(ApplicationItem.item_key).where(
        ApplicationItem.application_id == app.id, ApplicationItem.state == "PROVIDED")))
    intake_rules.ensure_complete(route_plan.checklist, provided, dsc_present)
    now = port(ClockPort).now()

    app.status = ApplicationStatus.IN_PROCESS
    app.ruleset_rev = key
    app.route = [{"stage": s.stage, "when": s.when} for s in route.stages]
    app.current_stage = route.stages[0].stage
    app.submitted_at = now
    app.dsc_present = dsc_present
    session.add(StageVisit(application_id=app.id, stage=app.current_stage, entered_at=now))
    session.flush()

    seq = port(LedgerPort).append(uow, EventIn(
        aggregate_type="application", aggregate_id=app.id, event_type="wf.application_submitted", event_version=2,
        ruleset_rev=key,
        payload={"application_id": app.id, "institution_id": app.institution_id, "category": app.category,
                 "ruleset_rev": key, "first_stage": app.current_stage,
                 "route": [s.stage for s in route.stages], "dsc_present": dsc_present,
                 "provided_item_keys": sorted(provided)},
    ))
    for rule_id in ruleset.clocks_on_submit:
        port(DeadlinePort).open(uow, SubjectRef("application", app.id), rule_id, Anchor(at=now, event_seq=seq), key)
    return app


def mark_items(uow: UnitOfWork, application_id: UUID, items: list[ItemIn]) -> ItemsOut:
    ref = port(CasePort).lookup(uow.session, application_id)
    port(AuthzPort).check(uow.principal, "application.submit",
                          ResourceRef("application", application_id, ref.institution_id, ref.region))
    app = uow.session.get(Application, application_id, with_for_update=True, populate_existing=True)
    if app.status != ApplicationStatus.DRAFT:
        raise Conflict("ITEMS_LOCKED_AFTER_SUBMIT")
    key = port(RulesetPort).default_key()
    config = intake_rules.plan(uow.session, app.category, key)
    known = {item["item_key"]: item for item in config.checklist["items"]}
    keys = [item.item_key for item in items]
    if len(keys) != len(set(keys)) or set(keys) - known.keys():
        raise ValidationFailed("INVALID_APPLICATION_ITEMS")
    check_document_refs(uow.session, application_id, [item.document_ref for item in items if item.document_ref is not None])
    for item in sorted(items, key=lambda item: item.item_key):
        row = uow.session.get(ApplicationItem, (application_id, item.item_key))
        if row is None and item.state == "MISSING":
            continue
        if row is not None and (row.state, row.document_ref) == (item.state, item.document_ref):
            continue
        if row is None:
            row = ApplicationItem(application_id=application_id, item_key=item.item_key)
            uow.session.add(row)
        row.state, row.document_ref = item.state, item.document_ref
        uow.session.flush()
        port(LedgerPort).append(uow, EventIn(aggregate_type="application", aggregate_id=application_id,
            event_type="wf.application_item_updated", ruleset_rev=None,
            payload={"application_id": application_id, "item_key": item.item_key,
                     "state": item.state, "document_ref": item.document_ref}))
    rows = {item.item_key: item for item in uow.session.scalars(select(ApplicationItem).where(
        ApplicationItem.application_id == application_id))}
    return ItemsOut(application_id=application_id, dsc_required=config.checklist["dsc_required"], assumptions=config.assumptions,
        items=[ItemOut(item_key=k, mandatory=known[k]["mandatory"], state=rows[k].state if k in rows else "MISSING",
                       document_ref=rows[k].document_ref if k in rows else None) for k in sorted(known)])


class Cases:
    def lookup(self, session: Session, application_id: UUID) -> CaseRef:
        row = session.get(Application, application_id)
        if row is None:
            raise NotFound("application not found")
        inst = session.get(Institution, row.institution_id)
        return CaseRef(application_id=row.id, institution_id=row.institution_id, region=inst.ro_region)


def checklist(session: Session, principal, application_id: UUID) -> ApplicationChecklistOut:
    """Read-only per-item state against the pinned ruleset (the default ruleset while still a draft)."""
    ref = port(CasePort).lookup(session, application_id)
    port(AuthzPort).check(principal, "application.read",
                          ResourceRef("application", application_id, ref.institution_id, ref.region))
    app = session.get(Application, application_id)
    key = app.ruleset_rev or port(RulesetPort).default_key()
    config = intake_rules.plan(session, app.category, key)
    known = {item["item_key"]: item for item in config.checklist["items"]}
    rows = {item.item_key: item for item in session.scalars(select(ApplicationItem).where(
        ApplicationItem.application_id == application_id))}
    items = [ItemOut(item_key=k, mandatory=known[k]["mandatory"], state=rows[k].state if k in rows else "MISSING",
                     document_ref=rows[k].document_ref if k in rows else None) for k in sorted(known)]
    missing = [i.item_key for i in items if i.mandatory and i.state != "PROVIDED"]
    return ApplicationChecklistOut(
        application_id=application_id, category=app.category, ruleset_key=key, pinned=app.ruleset_rev is not None,
        status=config.checklist["status"], label=config.checklist["label"], assumptions=list(config.assumptions),
        dsc_required=config.checklist["dsc_required"], dsc_present=app.dsc_present, items=items,
        missing_mandatory_item_keys=missing, mandatory_items_complete=not missing)
