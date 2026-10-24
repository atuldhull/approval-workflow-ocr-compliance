from uuid import UUID

from sqlalchemy.orm import Session

from app.intake.models import Application, Institution, StageVisit
from app.platform.registry import port
from contracts.enums import ApplicationStatus
from contracts.errors import Conflict, NotFound
from contracts.ports import AuthzPort, ClockPort, DeadlinePort, LedgerPort, RulesetPort, UnitOfWork
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


def submit_application(uow: UnitOfWork, application_id: UUID) -> Application:
    """Pins the ruleset, enters the first stage, opens the submit clocks and records it - in one transaction."""
    session = uow.session
    app = session.get(Application, application_id, with_for_update=True)
    if app is None:
        raise NotFound("application not found")
    port(AuthzPort).check(uow.principal, "application.submit",
                          ResourceRef("application", app.id, owner_institution_id=app.institution_id))
    if app.status != ApplicationStatus.DRAFT:
        raise Conflict(f"application is already {app.status}")

    rules = port(RulesetPort)
    key = rules.default_key()
    ruleset = rules.get(key)
    route = rules.route_for(app.category, key)
    now = port(ClockPort).now()

    app.status = ApplicationStatus.IN_PROCESS
    app.ruleset_rev = key
    app.route = [{"stage": s.stage, "when": s.when} for s in route.stages]
    app.current_stage = route.stages[0].stage
    app.submitted_at = now
    session.add(StageVisit(application_id=app.id, stage=app.current_stage, entered_at=now))
    session.flush()

    seq = port(LedgerPort).append(uow, EventIn(
        aggregate_type="application", aggregate_id=app.id, event_type="wf.application_submitted",
        ruleset_rev=key,
        payload={"application_id": app.id, "institution_id": app.institution_id, "category": app.category,
                 "ruleset_rev": key, "first_stage": app.current_stage,
                 "route": [s.stage for s in route.stages]},
    ))
    for rule_id in ruleset.clocks_on_submit:
        port(DeadlinePort).open(uow, SubjectRef("application", app.id), rule_id, Anchor(at=now, event_seq=seq), key)
    return app


class Cases:
    def lookup(self, session: Session, application_id: UUID) -> CaseRef:
        row = session.get(Application, application_id)
        if row is None:
            raise NotFound("application not found")
        inst = session.get(Institution, row.institution_id)
        return CaseRef(application_id=row.id, institution_id=row.institution_id, region=inst.ro_region)
