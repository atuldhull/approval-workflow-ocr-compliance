"""Deadline alerts: raise the configured ladder level, escalate, acknowledge.

An alert is addressed to a role group (an opaque recipient_ref), never to a person. The alert row, its ledger
event(s) and its outbox messages are written in one unit of work, so they commit or roll back together. Delivery
and its retries belong to the platform notifier; nothing here runs again because a message failed.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.deadlines.escalation import AlertConfig, LadderStep
from app.deadlines.models import Alert, Deadline
from app.platform.recipients import directory
from app.platform.registry import port
from contracts.enums import DeadlineStatus, Role
from contracts.errors import Conflict, Forbidden, NotFound, ValidationFailed
from contracts.ports import AuthzPort, CasePort, ClockPort, LedgerPort, OutboxPort, RulesetPort, UnitOfWork
from contracts.types import EventIn, OutboundMessage, ResourceRef

OPEN, VACANT, ESCALATED, ACKNOWLEDGED = "OPEN", "VACANT", "ESCALATED", "ACKNOWLEDGED"
VACANCY, WINDOW_ELAPSED = "VACANCY", "WINDOW_ELAPSED"


class Recipients(Protocol):
    """What the alert engine needs from the recipient directory (the proposed RecipientPort)."""

    def resolve(self, role: Role, resource: ResourceRef) -> UUID: ...
    def has_members(self, session: Session, recipient_ref: UUID) -> bool: ...


class ResolverUnavailable(Exception):
    """The directory could not answer. Never read as a vacancy: the timer retries later."""


class ScopeUnresolved(Exception):
    """The deadline's institution/region cannot be established, so no role group can be chosen safely."""


@dataclass(frozen=True)
class Scope:
    institution_id: UUID | None
    region: str | None


@dataclass(frozen=True)
class Advance:
    outcome: str          # SCHEDULED | ALERTED | ACKNOWLEDGED | LADDER_DONE | NOT_RUNNING | FAILED
    raised: int
    next_fire_at: datetime | None
    detail: str | None = None


def alert_config(d: Deadline) -> tuple[AlertConfig | None, tuple[LadderStep, ...]]:
    rules = port(RulesetPort).get(f"{d.ruleset}@{d.revision}").deadline_rules
    config = getattr(rules, "alerts", None)
    rule = rules.get(d.rule_id)
    if config is None or rule is None:
        return None, ()
    return config, config.ladder(rule)


def first_fire_at(rules, rule, due_at: datetime) -> datetime | None:
    config = getattr(rules, "alerts", None)
    ladder = config.ladder(rule) if config is not None else ()
    return AlertConfig.fire_at(ladder[0], due_at) if ladder else None


def subject_scope(session: Session, d: Deadline) -> Scope:
    return scope_of(session, d.subject_type, d.subject_id)


def scope_of(session: Session, subject_type: str, subject_id) -> Scope:
    """Institution and region a deadline subject belongs to; ScopeUnresolved rather than a guess."""
    if subject_type in ("obligation", "approval_letter"):
        # compliance rows record the institution and region of the case they were created for
        from app.compliance.models import ApprovalLetter, Obligation

        row = session.get(Obligation if subject_type == "obligation" else ApprovalLetter, subject_id)
        if row is None:
            raise ScopeUnresolved("deadline subject not found")
        return Scope(row.institution_id, row.region)
    if subject_type != "application":
        raise ScopeUnresolved(f"no scope lookup for {subject_type} deadlines")
    try:
        case = port(CasePort).lookup(session, subject_id)
    except NotFound:
        raise ScopeUnresolved("deadline subject not found") from None
    return Scope(case.institution_id, case.region)


def is_acknowledged(session: Session, deadline_id: UUID, due_version: int) -> bool:
    return bool(session.scalar(select(exists().where(
        Alert.deadline_id == deadline_id, Alert.due_version == due_version, Alert.status == ACKNOWLEDGED))))


class AlertEngine:
    def __init__(self, recipients: Recipients = directory):
        self.recipients = recipients

    def advance(self, uow: UnitOfWork, d: Deadline, now: datetime) -> Advance:
        """Raise every ladder level that is due for the deadline's current due_version (catching up after
        downtime), and return when the next one is due. The caller holds the deadline row locked."""
        session = uow.session
        # a breached clock keeps escalating; paused and closed ones do not fire
        if d.status not in (DeadlineStatus.RUNNING, DeadlineStatus.BREACHED):
            return Advance("NOT_RUNNING", 0, None)
        config, ladder = alert_config(d)
        if not ladder:
            return Advance("LADDER_DONE", 0, None)
        if is_acknowledged(session, d.id, d.due_version):
            return Advance("ACKNOWLEDGED", 0, None)
        scope: Scope | None = None
        raised = 0
        while d.alert_level < len(ladder):
            step = ladder[d.alert_level]
            previous = self._alert(session, d.id, d.alert_level - 1, d.due_version) if d.alert_level else None
            vacancy = previous is not None and previous.status == VACANT
            fire_at = config.fire_at(step, d.due_at)
            if not vacancy and fire_at > now:
                return Advance("ALERTED" if raised else "SCHEDULED", raised, fire_at)
            reason = None if step.level == 0 else (VACANCY if vacancy else WINDOW_ELAPSED)
            try:
                scope = scope or subject_scope(session, d)
                self.raise_level(uow, d, step, config, scope, previous, reason, now)
            except ScopeUnresolved:
                # needs a person: keep what was raised, stop firing rather than guess a recipient
                return Advance("FAILED", raised, None, "SCOPE_UNRESOLVED")
            raised += 1
            d.alert_level += 1
        return Advance("ALERTED" if raised else "LADDER_DONE", raised, None)

    def raise_level(self, uow: UnitOfWork, d: Deadline, step: LadderStep, config: AlertConfig, scope: Scope,
                    previous: Alert | None, reason: str | None, now: datetime) -> Alert:
        """Create the alert for (deadline, level, due_version) once. A duplicate attempt - a concurrent worker,
        a retried command - finds the existing row and writes no event and no message."""
        session = uow.session
        role = config.role_for(step, d.clock_owner)
        if role == Role.INSTITUTION and scope.institution_id is None:
            raise ScopeUnresolved("institution alert without an institution")
        if role == Role.RO_OFFICER and not scope.region:
            raise ScopeUnresolved("regional alert without a region")
        resource = ResourceRef(d.subject_type, d.subject_id, owner_institution_id=scope.institution_id,
                               region=scope.region)
        try:
            ref = self.recipients.resolve(role, resource)
            vacant = not self.recipients.has_members(session, ref)
        except Exception as e:  # noqa: BLE001 - any directory failure is an outage, never a vacancy
            raise ResolverUnavailable(type(e).__name__) from e

        new_id = uuid4()
        inserted = session.execute(insert(Alert).values(
            id=new_id, deadline_id=d.id, level=step.level, due_version=d.due_version, role=role.value,
            recipient_ref=ref, subject_type=d.subject_type, subject_id=d.subject_id,
            institution_id=scope.institution_id, region=scope.region, template=step.template,
            status=VACANT if vacant else OPEN, reason=reason, from_alert_id=previous.id if previous else None,
            raised_at=now,
        ).on_conflict_do_nothing(constraint="uq_dl_alert_level").returning(Alert.id)).first()
        if inserted is None:
            return self._alert(session, d.id, step.level, d.due_version)

        ledger = port(LedgerPort)
        ledger.append(uow, EventIn(
            aggregate_type="deadline", aggregate_id=d.id, event_type="dl.alert_raised",
            ruleset_rev=f"{d.ruleset}@{d.revision}",
            payload={"alert_id": new_id, "deadline_id": d.id, "level": step.level, "role": role.value,
                     "due_version": d.due_version, "status": VACANT if vacant else OPEN},
        ))
        if previous is not None:
            if previous.status == OPEN:
                previous.status = ESCALATED
            previous.escalated_at = now
            ledger.append(uow, EventIn(
                aggregate_type="deadline", aggregate_id=d.id, event_type="dl.alert_escalated",
                ruleset_rev=f"{d.ruleset}@{d.revision}", reason_code=reason,
                payload={"alert_id": new_id, "from_alert_id": previous.id, "deadline_id": d.id,
                         "from_level": previous.level, "to_level": step.level, "role": role.value,
                         "due_version": d.due_version, "reason": reason},
            ))
        if not vacant:
            outbox = port(OutboxPort)
            for channel in config.channels:
                outbox.enqueue(uow, OutboundMessage(new_id, channel, step.template, ref))
        session.flush()
        return self._alert(session, d.id, step.level, d.due_version)

    def acknowledge(self, uow: UnitOfWork, alert_id: UUID) -> Alert:
        session, principal = uow.session, uow.principal
        found = session.get(Alert, alert_id)
        if found is None:
            raise NotFound("alert not found")
        port(AuthzPort).check(principal, "alert.ack", ResourceRef(
            "alert", found.id, owner_institution_id=found.institution_id, region=found.region))
        if principal.role != found.role:
            raise Forbidden("only the role an alert is addressed to may acknowledge it")
        # lock order: deadline, then alert - the same order the timer worker uses
        d = session.scalar(select(Deadline).where(Deadline.id == found.deadline_id).with_for_update())
        a = session.scalar(select(Alert).where(Alert.id == alert_id).with_for_update()
                           .execution_options(populate_existing=True))
        if a.status == ACKNOWLEDGED:
            return a
        if a.status == VACANT:
            raise Conflict("a vacant alert was never delivered and cannot be acknowledged")
        now = port(ClockPort).now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValidationFailed("clock must return a timezone-aware datetime")
        a.status, a.acknowledged_at, a.acknowledged_by = ACKNOWLEDGED, now, principal.user_id
        port(LedgerPort).append(uow, EventIn(
            aggregate_type="deadline", aggregate_id=d.id, event_type="dl.alert_acknowledged",
            ruleset_rev=f"{d.ruleset}@{d.revision}",
            payload={"alert_id": a.id, "deadline_id": d.id, "level": a.level, "role": a.role,
                     "due_version": a.due_version},
        ))
        if d.due_version == a.due_version:
            d.next_fire_at = None   # nothing further for this due_version
        session.flush()
        return a

    @staticmethod
    def _alert(session: Session, deadline_id: UUID, level: int, due_version: int) -> Alert | None:
        return session.scalar(select(Alert).where(Alert.deadline_id == deadline_id, Alert.level == level,
                                                  Alert.due_version == due_version)
                              .execution_options(populate_existing=True))


engine = AlertEngine()
