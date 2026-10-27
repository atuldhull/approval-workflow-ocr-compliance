"""Letter registration, obligations and evidence verification. Every command runs in the caller's unit of work."""
import re
from datetime import date, datetime, time
from hashlib import sha256
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.compliance.models import ApprovalLetter, Evidence, Obligation
from app.compliance.rules import LETTER_VALIDITY_RULES, obligations_for
from app.compliance.vocab import Decision, ObligationStatus, RejectionReason
from app.deadlines.models import Deadline
from app.documents.models import DocumentVersion, Fact
from app.platform.registry import port
from contracts.enums import DeadlineStatus, FactState, LetterType, Role
from contracts.errors import Conflict, Forbidden, NotFound, ValidationFailed
from contracts.ports import AuthzPort, CasePort, ClockPort, DeadlinePort, LedgerPort, NotesPort, RulesetPort, UnitOfWork
from contracts.types import Anchor, CaseRef, EventIn, LetterIn, ResourceRef, SubjectRef

IST = ZoneInfo("Asia/Kolkata")
ISSUE_DATE_SOURCES = frozenset({"PORTAL_EVENT", "CONFIRMED_FACT"})
ACADEMIC_YEAR = re.compile(r"^[0-9]{4}-[0-9]{2}$")
MAX_F_NO = 100
MAX_NOTE = 4000

# Document versions that may be offered as evidence: only a version the scanner found CLEAN, which the documents
# module marks AVAILABLE (the same gate its OCR uses). Its schema allows only QUARANTINED and REJECTED today, so
# evidence submission stays closed until the scanner integration lands.
EVIDENCE_READY_STATUSES = frozenset({"AVAILABLE"})
REVIEWED_FACT_STATES = frozenset({FactState.CONFIRMED.value, FactState.CORRECTED.value})
NON_HUMAN_ROLES = frozenset({Role.SYSTEM})


def resource(row: ApprovalLetter | Obligation) -> ResourceRef:
    return ResourceRef("compliance", row.id, owner_institution_id=row.institution_id, region=row.region)


def _today() -> date:
    return port(ClockPort).now().astimezone(IST).date()


def _anchor(day: date, event_seq: int) -> Anchor:
    # legal dates are Indian calendar dates; any instant on the issue day anchors the same due date
    return Anchor(at=datetime.combine(day, time.min, IST), event_seq=event_seq)


def _open_clock(uow: UnitOfWork, subject: SubjectRef, rule_id: str, anchor: Anchor, key: str) -> tuple[UUID, date]:
    deadline_id = port(DeadlinePort).open(uow, subject, rule_id, anchor, key)
    return deadline_id, uow.session.get(Deadline, deadline_id).due_date


# ---- letters ----

def _check_provenance(uow: UnitOfWork, letter: LetterIn) -> str | None:
    """Validates where the letter and its issue date come from. Returns the cleaned letter number."""
    session = uow.session
    if letter.issue_date_source not in ISSUE_DATE_SOURCES:
        raise ValidationFailed(f"issue_date_source must be one of {sorted(ISSUE_DATE_SOURCES)}")
    f_no = letter.f_no.strip() if letter.f_no else None
    if f_no is not None and len(f_no) > MAX_F_NO:
        raise ValidationFailed(f"f_no is longer than {MAX_F_NO} characters")

    if letter.document_version_id is not None:
        version = session.get(DocumentVersion, letter.document_version_id)
        if version is None or version.application_id != letter.application_id:
            raise ValidationFailed("document_version_id is not a document of this application")
        if version.status == "REJECTED":
            raise ValidationFailed("the letter's document version was rejected")

    if letter.issue_date_source == "PORTAL_EVENT":
        if letter.issue_date_fact_id is not None:
            raise ValidationFailed("a PORTAL_EVENT issue date does not take issue_date_fact_id")
        if not f_no:
            raise ValidationFailed("a PORTAL_EVENT letter needs its letter number (f_no) as provenance")
        return f_no

    # CONFIRMED_FACT: the date was read off the letter and confirmed or corrected by an officer
    if letter.issue_date_fact_id is None:
        raise ValidationFailed("a CONFIRMED_FACT issue date needs issue_date_fact_id")
    fact = session.get(Fact, letter.issue_date_fact_id)
    if fact is None:
        raise ValidationFailed("issue_date_fact_id does not exist")
    if fact.state not in REVIEWED_FACT_STATES:
        raise ValidationFailed("the issue-date fact has not been confirmed by an officer")
    source = session.get(DocumentVersion, fact.document_version_id)
    if source is None or source.application_id != letter.application_id:
        raise ValidationFailed("the issue-date fact is not from a document of this application")
    if letter.document_version_id is not None and fact.document_version_id != letter.document_version_id:
        raise ValidationFailed("the issue-date fact is not from the letter's document version")
    if fact.reviewed_value != letter.issue_date.isoformat():
        raise ValidationFailed("issue_date does not match the confirmed fact")
    return f_no


def _validate_letter(letter: LetterIn) -> LetterType:
    try:
        letter_type = LetterType(letter.letter_type)
    except ValueError:
        raise ValidationFailed(f"unknown letter_type {letter.letter_type}") from None
    if not isinstance(letter.academic_year, str) or not ACADEMIC_YEAR.match(letter.academic_year):
        raise ValidationFailed("academic_year must look like 2026-27")
    if not isinstance(letter.issue_date, date) or isinstance(letter.issue_date, datetime):
        raise ValidationFailed("issue_date must be a calendar date")
    if letter.issue_date > _today():
        raise ValidationFailed("issue_date is in the future")
    if not isinstance(letter.lists_deficiencies, bool):
        raise ValidationFailed("lists_deficiencies must be true or false")
    return letter_type


class Compliance:
    """CompliancePort: the workflow (or a bureau officer through the API) records an issued letter."""

    def register_letter(self, uow: UnitOfWork, letter: LetterIn) -> UUID:
        return register_letter(uow, letter).id


def register_letter(uow: UnitOfWork, letter: LetterIn) -> ApprovalLetter:
    session = uow.session
    case: CaseRef = port(CasePort).lookup(session, letter.application_id)
    port(AuthzPort).check(uow.principal, "compliance.letter.register",
                          ResourceRef("compliance", owner_institution_id=case.institution_id, region=case.region))
    if letter.institution_id != case.institution_id:
        raise ValidationFailed("institution_id does not own this application")
    letter_type = _validate_letter(letter)
    f_no = _check_provenance(uow, letter)

    if letter_type in (LetterType.LOA, LetterType.EOA) and session.scalar(select(ApprovalLetter.id).where(
            ApprovalLetter.application_id == letter.application_id, ApprovalLetter.letter_type == letter_type,
            ApprovalLetter.academic_year == letter.academic_year)) is not None:
        raise Conflict(f"an {letter_type} for {letter.academic_year} is already registered for this application")

    key = port(RulesetPort).default_key()
    row = ApprovalLetter(
        application_id=case.application_id, institution_id=case.institution_id, region=case.region,
        letter_type=letter_type, academic_year=letter.academic_year, issue_date=letter.issue_date,
        issue_date_source=letter.issue_date_source, issue_date_fact_id=letter.issue_date_fact_id,
        document_version_id=letter.document_version_id, f_no=f_no, lists_deficiencies=letter.lists_deficiencies,
        # the registering officer is the human who confirms the letter lists deficiencies
        deficiencies_confirmed_by=uow.principal.user_id if letter.lists_deficiencies else None,
        ruleset_rev=key, registered_by=uow.principal.user_id, registered_role=str(uow.principal.role),
        registered_at=port(ClockPort).now(),
    )
    session.add(row)
    session.flush()
    seq = port(LedgerPort).append(uow, EventIn(
        aggregate_type="approval_letter", aggregate_id=row.id, event_type="cmp.letter_registered", ruleset_rev=key,
        payload={"letter_id": row.id, "application_id": row.application_id, "institution_id": row.institution_id,
                 "letter_type": row.letter_type, "academic_year": row.academic_year,
                 "issue_date": row.issue_date.isoformat(), "issue_date_source": row.issue_date_source,
                 "issue_date_fact_id": row.issue_date_fact_id, "document_version_id": row.document_version_id,
                 "f_no_sha256": sha256(f_no.encode("utf-8")).hexdigest() if f_no else None,
                 "lists_deficiencies": row.lists_deficiencies, "ruleset_rev": key},
    ))
    anchor = _anchor(row.issue_date, seq)

    validity_rule = LETTER_VALIDITY_RULES.get(letter_type)
    if validity_rule:
        row.validity_deadline_id, row.valid_until = _open_clock(
            uow, SubjectRef("approval_letter", row.id), validity_rule, anchor, key)

    rules = port(RulesetPort).get(key).deadline_rules
    for template in obligations_for(letter):
        rule = rules.get(template.rule_id)
        if rule is None:
            raise ValidationFailed(f"no deadline rule {template.rule_id} in {key}")
        _create_obligation(uow, row, template.kind, template.rule_id, rule.clause, rule.source_status,
                           template.origin, anchor, key)
    session.flush()
    return row


def _create_obligation(uow: UnitOfWork, letter: ApprovalLetter, kind: str, rule_id: str, clause: str | None,
                       source_status: str, origin: str, anchor: Anchor, key: str) -> Obligation:
    ob = Obligation(
        application_id=letter.application_id, institution_id=letter.institution_id, region=letter.region,
        kind=kind, source_letter_id=letter.id, source_clause=clause, source_status=source_status,
        state_origin=origin, rule_id=rule_id, status=ObligationStatus.OPEN, created_at=port(ClockPort).now(),
    )
    uow.session.add(ob)
    uow.session.flush()
    ob.deadline_id, ob.due_date = _open_clock(uow, SubjectRef("obligation", ob.id), rule_id, anchor, key)
    uow.session.flush()
    port(LedgerPort).append(uow, EventIn(
        aggregate_type="obligation", aggregate_id=ob.id, event_type="cmp.obligation_created", ruleset_rev=key,
        payload={"obligation_id": ob.id, "application_id": ob.application_id, "institution_id": ob.institution_id,
                 "kind": ob.kind, "source_letter_id": ob.source_letter_id, "source_clause": ob.source_clause,
                 "source_status": ob.source_status, "state_origin": ob.state_origin, "rule_id": ob.rule_id,
                 "deadline_id": ob.deadline_id, "due_date": ob.due_date.isoformat() if ob.due_date else None},
    ))
    return ob


# ---- evidence ----

def submit_evidence(uow: UnitOfWork, obligation_id: UUID, document_version_id: UUID) -> Evidence:
    session = uow.session
    ob = session.get(Obligation, obligation_id, with_for_update=True)
    if ob is None:
        raise NotFound("obligation not found")
    port(AuthzPort).check(uow.principal, "compliance.evidence.submit", resource(ob))
    if ob.status == ObligationStatus.MET:
        raise Conflict("this obligation is already met")
    if ob.status == ObligationStatus.EVIDENCE_SUBMITTED:
        raise Conflict("evidence for this obligation is already awaiting verification")

    version = session.get(DocumentVersion, document_version_id)
    if version is None or version.application_id != ob.application_id or version.institution_id != ob.institution_id:
        raise ValidationFailed("document_version_id is not a document of this obligation's application")
    if version.status not in EVIDENCE_READY_STATUSES:
        raise ValidationFailed(f"document version is {version.status}; only scanner-approved versions can be evidence")
    if session.scalar(select(Evidence.id).where(Evidence.obligation_id == ob.id,
                                                Evidence.document_version_id == version.document_version_id)):
        raise Conflict("this document version was already submitted for this obligation")

    ev = Evidence(obligation_id=ob.id, application_id=ob.application_id, institution_id=ob.institution_id,
                  document_version_id=version.document_version_id, status="SUBMITTED",
                  submitted_by=uow.principal.user_id, submitted_at=port(ClockPort).now())
    session.add(ev)
    ob.status = ObligationStatus.EVIDENCE_SUBMITTED
    session.flush()
    port(LedgerPort).append(uow, EventIn(
        aggregate_type="obligation", aggregate_id=ob.id, event_type="cmp.evidence_submitted",
        payload={"evidence_id": ev.id, "obligation_id": ob.id, "application_id": ob.application_id,
                 "institution_id": ob.institution_id, "document_version_id": ev.document_version_id,
                 "document_sha256": version.sha256},
    ))
    return ev


def verify_evidence(uow: UnitOfWork, evidence_id: UUID, decision: str, reason_code: str | None = None,
                    note: str | None = None) -> Evidence:
    """A human officer accepts or rejects one submission. Rejection needs an approved reason code."""
    session = uow.session
    if uow.principal.role in NON_HUMAN_ROLES:
        raise Forbidden("evidence is verified by a human officer, never by an automated actor")
    ev = session.get(Evidence, evidence_id, with_for_update=True)
    if ev is None:
        raise NotFound("evidence not found")
    ob = session.get(Obligation, ev.obligation_id, with_for_update=True)
    port(AuthzPort).check(uow.principal, "compliance.evidence.verify", resource(ob))
    if ev.status != "SUBMITTED":
        raise Conflict(f"this evidence was already {ev.status}")

    try:
        decision = Decision(decision)
    except ValueError:
        raise ValidationFailed("decision must be ACCEPTED or REJECTED") from None
    note = note.strip() if note else None
    if note is not None and len(note) > MAX_NOTE:
        raise ValidationFailed(f"note is longer than {MAX_NOTE} characters")
    if decision == Decision.ACCEPTED:
        if reason_code is not None:
            raise ValidationFailed("an accepted decision takes no reason code")
    else:
        if not reason_code:
            raise ValidationFailed("a rejection needs a reason code")
        try:
            reason_code = RejectionReason(reason_code)
        except ValueError:
            raise ValidationFailed(f"unknown reason code {reason_code}") from None
        if reason_code == RejectionReason.OTHER_SEE_NOTE and not note:
            raise ValidationFailed("OTHER_SEE_NOTE needs a note explaining the rejection")

    note_ref = note_hash = None
    if note:
        note_ref, note_hash = port(NotesPort).create(uow, note)

    now = port(ClockPort).now()
    ev.status = decision.value
    ev.verified_by, ev.verified_role, ev.verified_at = uow.principal.user_id, str(uow.principal.role), now
    ev.reason_code = reason_code.value if reason_code else None
    ev.note_ref, ev.note_hash = note_ref, note_hash
    if decision == Decision.ACCEPTED:
        ob.status = ObligationStatus.MET
        ob.met_evidence_id, ob.met_by, ob.met_at = ev.id, uow.principal.user_id, now
        _close_clock(uow, ob)
    else:
        ob.status = ObligationStatus.OPEN
    session.flush()
    port(LedgerPort).append(uow, EventIn(
        aggregate_type="obligation", aggregate_id=ob.id, event_type="cmp.evidence_verified",
        reason_code=ev.reason_code, note_ref=note_ref, note_hash=note_hash,
        payload={"evidence_id": ev.id, "obligation_id": ob.id, "application_id": ob.application_id,
                 "institution_id": ob.institution_id, "decision": ev.status, "reason_code": ev.reason_code,
                 "obligation_status": ob.status},
    ))
    return ev


def _close_clock(uow: UnitOfWork, ob: Obligation) -> None:
    if ob.rule_id is None:
        return
    live = uow.session.scalar(select(Deadline.id).where(
        Deadline.id == ob.deadline_id, Deadline.status.in_((DeadlineStatus.RUNNING, DeadlineStatus.PAUSED))))
    # a clock that already ran out stays BREACHED; meeting the obligation late does not rewrite it
    if live is not None:
        port(DeadlinePort).close(uow, SubjectRef("obligation", ob.id), ob.rule_id, DeadlineStatus.MET)
