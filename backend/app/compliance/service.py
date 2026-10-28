"""Letter registration, obligations and evidence verification. Every command runs in the caller's unit of work."""
import re
from datetime import date, datetime, time
from hashlib import sha256
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.compliance.models import ApprovalLetter, Evidence, Obligation
from app.compliance.rules import LETTER_VALIDITY_RULES, RECORDED_DUE_DATE_RULE, obligations_for
from app.compliance.vocab import Decision, ObligationStatus, RejectionReason, StateOrigin
from app.deadlines.models import Deadline
from app.documents.models import DocumentVersion, Fact
from app.platform.models import CaseNote
from app.platform.registry import port
from contracts.enums import DeadlineStatus, FactState, LetterType, ObligationKind, Role
from contracts.errors import Conflict, Forbidden, NotFound, ValidationFailed
from contracts.ports import AuthzPort, CasePort, ClockPort, DeadlinePort, LedgerPort, NotesPort, RulesetPort, UnitOfWork
from contracts.types import Anchor, CaseRef, EventIn, LetterIn, Principal, ResourceRef, SubjectRef

IST = ZoneInfo("Asia/Kolkata")
ISSUE_DATE_SOURCES = frozenset({"PORTAL_EVENT", "CONFIRMED_FACT"})
ACADEMIC_YEAR = re.compile(r"^[0-9]{4}-[0-9]{2}$")
MAX_F_NO = 100
MAX_NOTE = 4000

# Document versions that may be offered as evidence: only a version the scanner found CLEAN, which the documents
# module marks AVAILABLE (the same gate its OCR uses).
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
    return add_obligation(uow, Obligation(
        application_id=letter.application_id, institution_id=letter.institution_id, region=letter.region,
        kind=kind, source_letter_id=letter.id, source_clause=clause, source_status=source_status,
        state_origin=origin, rule_id=rule_id, status=ObligationStatus.OPEN, created_at=port(ClockPort).now(),
    ), anchor, key)


def add_obligation(uow: UnitOfWork, ob: Obligation, anchor: Anchor, key: str) -> Obligation:
    """Stores a new obligation, opens the clock of its rule from `anchor` and records cmp.obligation_created v2
    (v1 schemas stay for events written before the document and validity fields existed)."""
    uow.session.add(ob)
    uow.session.flush()
    ob.deadline_id, ob.due_date = _open_clock(uow, SubjectRef("obligation", ob.id), ob.rule_id, anchor, key)
    uow.session.flush()
    port(LedgerPort).append(uow, EventIn(
        aggregate_type="obligation", aggregate_id=ob.id, event_type="cmp.obligation_created", event_version=2,
        ruleset_rev=key,
        payload={"obligation_id": ob.id, "application_id": ob.application_id, "institution_id": ob.institution_id,
                 "kind": ob.kind, "source_letter_id": ob.source_letter_id, "source_clause": ob.source_clause,
                 "source_status": ob.source_status, "state_origin": ob.state_origin, "rule_id": ob.rule_id,
                 "deadline_id": ob.deadline_id, "due_date": ob.due_date.isoformat() if ob.due_date else None,
                 "document_id": ob.document_id, "document_version_id": ob.document_version_id,
                 "doc_type": ob.doc_type, "valid_until": ob.valid_until.isoformat() if ob.valid_until else None,
                 "validity_basis": ob.validity_basis, "eoa_stop_year": ob.eoa_stop_year,
                 "live_lease_ok": ob.live_lease_ok},
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
    if ob.kind == ObligationKind.DOCUMENT_VALIDITY:
        # a renewal is a newer version of the same document; its expiry is read and confirmed like any fact
        if version.document_id != ob.document_id or version.document_version_id == ob.document_version_id:
            raise ValidationFailed("a renewal must be a new version of the same document")
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
    if decision == Decision.ACCEPTED and ob.kind == ObligationKind.DOCUMENT_VALIDITY:
        from app.compliance import validity  # validity builds on this module

        # the accepted renewal opens the next validity record from its own confirmed expiry date
        validity.renewal_accepted(uow, ev.document_version_id)
    return ev


# ---- reading a verification note ----

class NoteIntegrityError(Conflict):
    """The stored note text no longer matches the hash recorded with the decision."""


def read_evidence_note(session, principal: Principal, evidence_id: UUID) -> tuple[Evidence, str | None, bool]:
    """The note an officer left on a verification: (evidence, text or None, redacted).

    Officers who may verify this obligation's evidence and the owning institution may read it. Everyone else
    (auditors included) is refused here; they see only that a note exists (EvidenceOut.has_note). The text lives in
    the platform note store; contracts' NotesPort has no read method yet, so it is read by its reference here and
    checked against the hash the decision recorded. Events never carry the text.
    """
    ev = session.get(Evidence, evidence_id)
    if ev is None:
        raise NotFound("evidence not found")
    ob = session.get(Obligation, ev.obligation_id)
    action = "compliance.read" if principal.role == Role.INSTITUTION else "compliance.evidence.verify"
    port(AuthzPort).check(principal, action, resource(ob))
    if ev.note_ref is None:
        return ev, None, False
    note = session.get(CaseNote, ev.note_ref)
    if note is None or note.redacted_at is not None or note.body is None:
        return ev, None, True
    if sha256(note.body.encode("utf-8")).hexdigest() != ev.note_hash:
        raise NoteIntegrityError("the stored note does not match the decision's record, so it is not shown")
    return ev, note.body, False


def _close_clock(uow: UnitOfWork, ob: Obligation) -> None:
    if ob.rule_id is None:
        return
    live = uow.session.scalar(select(Deadline.id).where(
        Deadline.id == ob.deadline_id,
        Deadline.status.in_((DeadlineStatus.RUNNING, DeadlineStatus.PAUSED, DeadlineStatus.BREACHED))))
    # a clock that already ran out closes as MET late: dl.deadline_closed says so (late, from BREACHED) and the
    # dl.deadline_breached event stays in the ledger; closing it also stops its escalation
    if live is not None:
        port(DeadlinePort).close(uow, SubjectRef("obligation", ob.id), ob.rule_id, DeadlineStatus.MET)


# ---- obligations an officer records ----

CLAUSE = re.compile(r"^[0-9A-Za-z.()/ -]{1,32}$")
MAX_TITLE, MAX_EVIDENCE_REQUIRED = 200, 500
RECORDABLE_KINDS = frozenset(ObligationKind) - {ObligationKind.DOCUMENT_VALIDITY}


def record_obligation(uow: UnitOfWork, application_id: UUID, kind: str, title: str, evidence_required: str,
                      source_clause: str | None = None, due_date: date | None = None, rule_id: str | None = None,
                      anchor_date: date | None = None) -> Obligation:
    """An authorised officer records an undertaking (or another obligation) for a case: the clause it comes from,
    what it asks, the evidence that meets it, and either the due date it states or a recordable rule that times it
    from `anchor_date` (default today). Document validity is recorded against a document version instead."""
    session = uow.session
    case: CaseRef = port(CasePort).lookup(session, application_id)
    port(AuthzPort).check(uow.principal, "compliance.obligation.record",
                          ResourceRef("compliance", owner_institution_id=case.institution_id, region=case.region))
    try:
        kind = ObligationKind(kind)
    except ValueError:
        raise ValidationFailed(f"unknown obligation kind {kind}") from None
    if kind not in RECORDABLE_KINDS:
        raise ValidationFailed("document validity is recorded against a document version, not here")
    title, evidence_required = (title or "").strip(), (evidence_required or "").strip()
    if not title or len(title) > MAX_TITLE:
        raise ValidationFailed(f"title is required, up to {MAX_TITLE} characters")
    if not evidence_required or len(evidence_required) > MAX_EVIDENCE_REQUIRED:
        raise ValidationFailed(f"evidence_required is required, up to {MAX_EVIDENCE_REQUIRED} characters")
    if (due_date is None) == (rule_id is None):
        raise ValidationFailed("give exactly one of due_date or rule_id")

    key = port(RulesetPort).default_key()
    rules = port(RulesetPort).get(key).deadline_rules
    today = _today()
    if rule_id is not None:
        rule = rules.get(rule_id)
        if rule is None or not rule.extra.get("recordable") or rule.duration is None:
            recordable = sorted(r.id for r in rules.values() if r.extra.get("recordable"))
            raise ValidationFailed(f"rule_id must be one of the recordable rules {recordable}")
        anchor_day = anchor_date or today
        if anchor_day > today:
            raise ValidationFailed("anchor_date is in the future")
    else:
        rule = rules.get(RECORDED_DUE_DATE_RULE)
        if rule is None:
            raise ValidationFailed(f"no deadline rule {RECORDED_DUE_DATE_RULE} in {key}")
        if anchor_date is not None:
            raise ValidationFailed("anchor_date goes with rule_id; a stated due date is its own anchor")
        if due_date < today:
            raise ValidationFailed("due_date is in the past")
        anchor_day = due_date
    clause = (source_clause or "").strip() or rule.clause
    if not clause or not CLAUSE.match(clause):
        raise ValidationFailed("source_clause is required: up to 32 letters, digits, spaces and . ( ) / -")

    return add_obligation(uow, Obligation(
        application_id=case.application_id, institution_id=case.institution_id, region=case.region, kind=kind,
        source_clause=clause, source_status=rule.source_status, state_origin=StateOrigin.OFFICER_CONFIRMED,
        rule_id=rule.id, status=ObligationStatus.OPEN, created_at=port(ClockPort).now(), title=title,
        evidence_required=evidence_required, recorded_by=uow.principal.user_id,
    ), _anchor(anchor_day, None), key)


def penalty_notes(rule) -> list[str]:
    """APH penalty tiers a rule lists, as notes for the competent authority. The system never applies them."""
    tiers = (rule.extra.get("penalty_tiers") or []) if rule is not None else []
    if not tiers:
        return []
    month = {f"{m:02d}": n for m, n in enumerate(
        ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
         "November", "December"), start=1)}

    def day(md: str) -> str:
        return f"{int(md[3:])} {month.get(md[:2], md[:2])}"

    clause = f" (cl. {rule.clause})" if rule.clause else ""
    notes = [f"If late: {t['pct']}% penalty up to {day(str(t['until']))}{clause}" for t in tiers]
    if rule.extra.get("beyond_last_tier") == "approval_withdrawn":
        notes.append(f"After {day(str(tiers[-1]['until']))} the approval is withdrawn{clause}")
    notes.append("For the competent authority to decide; this system does not apply penalties")
    return notes
