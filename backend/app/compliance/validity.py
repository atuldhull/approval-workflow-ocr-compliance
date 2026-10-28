"""Document validity (APH cl. 6.17): a DOCUMENT_VALIDITY obligation that falls due on a document's expiry date.

A record opens when two officers have confirmed the date a tracked document is valid until (four-eyes fact review)
or when an authorised officer records it. Renewal is a new version of the same document: the institution offers
it as evidence, its expiry is read and confirmed like any fact, and an officer's acceptance meets the old record
(closing its clock) and opens the next one from the new date. Old and new versions and records all stay.
"""
from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import select

from app.compliance.models import Evidence, Obligation
from app.compliance.rules import (ISSUE_DATE_FIELD, LEASE_END_FIELD, LEASE_STOP_RULE, VALID_UNTIL_FIELD,
                                  VALIDITY_DOCUMENTS, VALIDITY_RULE, ValidityDocument)
from app.compliance.service import IST, _anchor, _today, add_obligation
from app.compliance.vocab import ObligationStatus, StateOrigin
from app.deadlines.escalation import rule_reminders
from app.deadlines.rules import covers, due_date, lease_eoa_stop_year
from app.documents.models import Document, DocumentVersion, Fact
from app.platform.registry import port
from contracts.enums import ObligationKind
from contracts.errors import Conflict, NotFound, ValidationFailed
from contracts.ports import AuthzPort, CasePort, ClockPort, RulesetPort, UnitOfWork
from contracts.types import ResourceRef

FACT_BASIS, OFFICER_BASIS, PERIOD_BASIS = "DOCUMENT_FACT", "OFFICER_RECORDED", "APH_PERIOD"
REVIEWED_STATES = ("CONFIRMED", "CORRECTED")


@dataclass(frozen=True)
class ValidUntil:
    day: date
    basis: str
    fact_id: UUID | None = None


def _rules():
    key = port(RulesetPort).default_key()
    return key, port(RulesetPort).get(key).deadline_rules


def _period_end(issue: date, rule_id: str) -> date:
    _, rules = _rules()
    rule = rules.get(rule_id)
    if rule is None or rule.duration is None:
        raise ValidationFailed(f"no validity period rule {rule_id}")
    return due_date(datetime.combine(issue, datetime.min.time(), IST), rule.duration)


def _iso_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def valid_until_from_fact(spec: ValidityDocument, fact: Fact) -> ValidUntil | None:
    """The expiry a confirmed fact gives for a document of this kind, or None if the fact does not give one."""
    day = _iso_date(fact.reviewed_value)
    if day is None:
        return None  # a corrected value that is not a calendar date; an officer can record the date instead
    if fact.field_key == VALID_UNTIL_FIELD or (fact.field_key == LEASE_END_FIELD and spec.lease):
        return ValidUntil(day, FACT_BASIS, fact.fact_id)
    if fact.field_key == ISSUE_DATE_FIELD and spec.period_rule:
        return ValidUntil(_period_end(day, spec.period_rule), PERIOD_BASIS, fact.fact_id)
    return None


def _confirmed_valid_until(session, spec: ValidityDocument, version_id: UUID) -> ValidUntil | None:
    """The latest confirmed expiry on a version: a date printed on it before one counted from its issue date."""
    facts = session.scalars(select(Fact).where(
        Fact.document_version_id == version_id, Fact.confirmed_at.is_not(None),
        Fact.state.in_(REVIEWED_STATES)).order_by(Fact.confirmed_at.desc())).all()
    found = [v for v in (valid_until_from_fact(spec, f) for f in facts) if v is not None]
    return next((v for v in found if v.basis == FACT_BASIS), found[0] if found else None)


def _record_for_version(session, version_id: UUID) -> Obligation | None:
    return session.scalar(select(Obligation).where(Obligation.kind == ObligationKind.DOCUMENT_VALIDITY,
                                                   Obligation.document_version_id == version_id))


def _live_record(session, application_id: UUID, doc_type: str) -> Obligation | None:
    return session.scalar(select(Obligation).where(
        Obligation.kind == ObligationKind.DOCUMENT_VALIDITY, Obligation.application_id == application_id,
        Obligation.doc_type == doc_type, Obligation.status != ObligationStatus.MET).with_for_update())


def _lease_figures(session, application_id: UUID, lease_end: date, years: int | None) -> tuple[str | None, bool]:
    """(first academic year an EoA is blocked, whether the live lease covered the longest course at submission)."""
    from app.intake.models import Application  # the submission date; intake owns it

    _, rules = _rules()
    stop = rules.get(LEASE_STOP_RULE)
    years = years or (stop.extra.get("max_course_duration_years") if stop else None) or 4
    stop_year = lease_eoa_stop_year(lease_end, years, rules.academic_year) if rules.academic_year else None
    app = session.get(Application, application_id)
    at = app.submitted_at.astimezone(IST).date() if app is not None and app.submitted_at else _today()
    return stop_year, covers(at, years, lease_end)


def open_record(uow: UnitOfWork, version: DocumentVersion, document: Document, valid: ValidUntil,
                max_course_duration_years: int | None = None) -> Obligation:
    """Opens the DOCUMENT_VALIDITY obligation for one document version; its clock falls due on the expiry date."""
    session = uow.session
    spec = VALIDITY_DOCUMENTS[document.doc_type]
    case = port(CasePort).lookup(session, version.application_id)
    key, rules = _rules()
    rule = rules.get(VALIDITY_RULE)
    if rule is None:
        raise ValidationFailed(f"no deadline rule {VALIDITY_RULE} in {key}")
    stop_year = live_ok = None
    if spec.lease:
        stop_year, live_ok = _lease_figures(session, version.application_id, valid.day, max_course_duration_years)
    ob = Obligation(
        application_id=case.application_id, institution_id=case.institution_id, region=case.region,
        kind=ObligationKind.DOCUMENT_VALIDITY, source_clause=spec.clause, source_status=rule.source_status,
        # a human confirmed the date: two officers (fact review) or the officer recording it
        state_origin=StateOrigin.OFFICER_CONFIRMED, rule_id=VALIDITY_RULE, status=ObligationStatus.OPEN,
        created_at=port(ClockPort).now(), document_id=document.document_id,
        document_version_id=version.document_version_id, doc_type=document.doc_type, valid_until=valid.day,
        validity_basis=valid.basis, validity_fact_id=valid.fact_id, eoa_stop_year=stop_year, live_lease_ok=live_ok,
        recorded_by=uow.principal.user_id if valid.basis == OFFICER_BASIS else None,
    )
    return add_obligation(uow, ob, _anchor(valid.day, None), key)


def on_fact_confirmed(uow: UnitOfWork, fact: Fact, version: DocumentVersion) -> None:
    """documents hook: a confirmed expiry (or issue date) on a tracked document opens its validity record.

    While the document still has a record that is not met, a newer version's date waits: it opens the next record
    when an officer accepts that version as the renewal.
    """
    session = uow.session
    document = session.get(Document, version.document_id)
    spec = VALIDITY_DOCUMENTS.get(document.doc_type) if document else None
    valid = valid_until_from_fact(spec, fact) if spec else None
    if valid is None or _record_for_version(session, version.document_version_id) is not None:
        return
    if _live_record(session, version.application_id, document.doc_type) is not None:
        return
    newer = session.scalar(select(Obligation.id).join(
        DocumentVersion, DocumentVersion.document_version_id == Obligation.document_version_id).where(
        Obligation.kind == ObligationKind.DOCUMENT_VALIDITY, Obligation.document_id == document.document_id,
        DocumentVersion.version_no > version.version_no).limit(1))
    if newer is not None:
        return  # an older version's date never reopens a document that a later version has renewed
    open_record(uow, version, document, valid)


def renewal_accepted(uow: UnitOfWork, version_id: UUID) -> Obligation | None:
    """The accepted renewal's own confirmed expiry opens the next record. Without one yet, the next record opens
    when that date is confirmed or recorded."""
    session = uow.session
    version = session.get(DocumentVersion, version_id)
    document = session.get(Document, version.document_id)
    spec = VALIDITY_DOCUMENTS.get(document.doc_type)
    valid = _confirmed_valid_until(session, spec, version_id) if spec else None
    if valid is None or _record_for_version(session, version_id) is not None:
        return None
    return open_record(uow, version, document, valid)


def record_validity(uow: UnitOfWork, document_version_id: UUID, valid_until: date | None = None,
                    issue_date: date | None = None, max_course_duration_years: int | None = None) -> Obligation:
    """An authorised officer records the date a document version is valid until (or, for a document the APH gives
    a period, its issue date)."""
    session = uow.session
    version = session.get(DocumentVersion, document_version_id)
    if version is None:
        raise NotFound("document version not found")
    case = port(CasePort).lookup(session, version.application_id)
    port(AuthzPort).check(uow.principal, "compliance.validity.record", ResourceRef(
        "compliance", owner_institution_id=case.institution_id, region=case.region))
    document = session.get(Document, version.document_id)
    spec = VALIDITY_DOCUMENTS.get(document.doc_type) if document else None
    if spec is None:
        raise ValidationFailed(f"validity is tracked only for {sorted(VALIDITY_DOCUMENTS)}")
    if version.status != "AVAILABLE":
        raise ValidationFailed("only a version that passed the malware scan can carry a validity record")
    if (valid_until is None) == (issue_date is None):
        raise ValidationFailed("give exactly one of valid_until or issue_date")
    if issue_date is not None and not spec.period_rule:
        raise ValidationFailed("this document has no APH validity period; record the date it is valid until")
    if issue_date is not None and issue_date > _today():
        raise ValidationFailed("issue_date is in the future")
    if max_course_duration_years is not None and not spec.lease:
        raise ValidationFailed("max_course_duration_years applies only to a land lease")
    if _record_for_version(session, version.document_version_id) is not None:
        raise Conflict("this document version already has a validity record")
    live = _live_record(session, version.application_id, document.doc_type)
    if live is not None:
        pending = session.scalar(select(Evidence.id).where(
            Evidence.obligation_id == live.id, Evidence.document_version_id == version.document_version_id))
        raise Conflict("decide the renewal first: accepting it records this version's date" if pending else
                       "this document still has an open validity record; submit the new version as its renewal")
    valid = (ValidUntil(valid_until, OFFICER_BASIS) if valid_until is not None
             else ValidUntil(_period_end(issue_date, spec.period_rule), PERIOD_BASIS))
    return open_record(uow, version, document, valid, max_course_duration_years)


# ---- how a record reads ----

def expiring_window_days() -> int:
    """A record is 'expiring soon' from its earliest advance reminder on (DOCUMENT_EXPIRY reminders)."""
    _, rules = _rules()
    rule = rules.get(VALIDITY_RULE)
    reminders = rule_reminders(rule) if rule else ()
    return max((-r.days for r in reminders), default=0)


def validity_state(ob: Obligation, today: date, window: int) -> str:
    """VALID | EXPIRING_SOON | EXPIRED | RENEWAL_UNDER_REVIEW | RENEWED (met: a renewal was accepted)."""
    if ob.status == ObligationStatus.MET:
        return "RENEWED"
    if ob.status == ObligationStatus.EVIDENCE_SUBMITTED:
        return "RENEWAL_UNDER_REVIEW"
    if today > ob.valid_until:
        return "EXPIRED"
    return "EXPIRING_SOON" if (ob.valid_until - today).days <= window else "VALID"
