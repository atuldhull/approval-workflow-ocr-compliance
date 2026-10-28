from uuid import UUID

from sqlalchemy import select

from app.deadlines.alerts import first_fire_at
from app.deadlines.calendars import load_calendar
from app.deadlines.models import Deadline
from app.deadlines.rules import IST, DeadlineRule, due_date, end_of_day
from app.platform.registry import port
from contracts.enums import ClockKind, DeadlineStatus
from contracts.errors import Conflict, NotFound, ValidationFailed
from contracts.ports import ClockPort, LedgerPort, RulesetPort, UnitOfWork
from contracts.types import Anchor, EventIn, SubjectRef

# a BREACHED clock is still live: it keeps alerting and is closed (late) or paused like a running one
LIVE = (DeadlineStatus.RUNNING, DeadlineStatus.PAUSED, DeadlineStatus.BREACHED)


def explain(rule: DeadlineRule, anchor: Anchor, due) -> str:
    source = f"clause {rule.clause}" if rule.clause else rule.source_status.replace("_", " ")
    d = rule.duration
    count_note = ""
    if d.unit == "working_days":
        count_note = (f" using calendar {rule.calendar_id}; anchor day "
                      f"{'counts' if rule.count_anchor_day else 'does not count'}")
    return (f"{rule.id} ({source}): {d.value} {d.unit.replace('_', ' ')}{count_note} from "
            f"{rule.anchor or 'anchor'} on {anchor.at.astimezone(IST).date().isoformat()}, due {due.isoformat()}; "
            f"{rule.clock_kind} clock owned by {rule.clock_owner}")


def _record(uow: UnitOfWork, row: Deadline, event_type: str, **extra) -> None:
    """Ledger event for a lifecycle change, in the caller's unit of work; due_date/due_version are the row's now."""
    port(LedgerPort).append(uow, EventIn(
        aggregate_type="deadline", aggregate_id=row.id, event_type=event_type,
        ruleset_rev=f"{row.ruleset}@{row.revision}",
        payload={"deadline_id": row.id, "subject_type": row.subject_type, "subject_id": row.subject_id,
                 "rule_id": row.rule_id, **extra, "due_date": row.due_date.isoformat(),
                 "due_version": row.due_version},
    ))


class DeadlineEngine:
    def open(self, uow: UnitOfWork, subject: SubjectRef, rule_id: str, anchor: Anchor, ruleset_key: str) -> UUID:
        rules = port(RulesetPort).get(ruleset_key).deadline_rules
        rule = rules.get(rule_id)
        if rule is None:
            raise ValidationFailed(f"no deadline rule {rule_id} in {ruleset_key}")
        if rule.duration is None:
            raise ValidationFailed(f"{rule_id} is computed and cannot be opened from an anchor alone")
        if self._live(uow, subject, rule_id) is not None:
            raise Conflict(f"{rule_id} is already running for this {subject.type}")

        calendar = None
        if rule.duration.unit == "working_days":
            if not rule.calendar_id or rule.count_anchor_day is None:
                raise ValidationFailed(f"{rule_id} needs a versioned calendar and anchor-day convention")
            calendar = load_calendar(uow.session, rule.calendar_id)
        due = due_date(anchor.at, rule.duration, calendar=calendar, count_anchor_day=rule.count_anchor_day)
        ruleset, _, revision = ruleset_key.partition("@")
        row = Deadline(
            subject_type=subject.type, subject_id=subject.id, rule_id=rule_id, ruleset=ruleset, revision=revision,
            clause=rule.clause, source_status=rule.source_status, anchor_event_seq=anchor.event_seq,
            anchor_at=anchor.at, duration_value=rule.duration.value, duration_unit=rule.duration.unit,
            clock_kind=rule.clock_kind, clock_owner=rule.clock_owner, status=DeadlineStatus.RUNNING,
            calendar_id=rule.calendar_id, count_anchor_day=rule.count_anchor_day,
            due_at=end_of_day(due), due_date=due, due_version=1, explanation=explain(rule, anchor, due),
            next_fire_at=first_fire_at(rules, rule, end_of_day(due)), alert_level=0,
        )
        uow.session.add(row)
        uow.session.flush()
        port(LedgerPort).append(uow, EventIn(
            aggregate_type="deadline", aggregate_id=row.id, event_type="dl.deadline_opened", ruleset_rev=ruleset_key,
            payload={"deadline_id": row.id, "subject_type": subject.type, "subject_id": subject.id,
                     "rule_id": rule_id, "clock_kind": row.clock_kind, "clock_owner": row.clock_owner,
                     "due_date": due.isoformat(), "ruleset_rev": ruleset_key},
        ))
        return row.id

    def close(self, uow: UnitOfWork, subject: SubjectRef, rule_id: str, outcome: str) -> None:
        if outcome not in (DeadlineStatus.MET, DeadlineStatus.WAIVED):
            raise ValidationFailed("a deadline closes as MET or WAIVED")
        row = self._require_live(uow, subject, rule_id)
        from_status = row.status
        late = from_status == DeadlineStatus.BREACHED or port(ClockPort).now() > row.due_at
        row.status = outcome
        row.next_fire_at = None
        _record(uow, row, "dl.deadline_closed", outcome=str(outcome), from_status=str(from_status), late=late)

    def pause_internal(self, uow: UnitOfWork, subject: SubjectRef, rule_id: str) -> None:
        row = self._require_live(uow, subject, rule_id)
        if row.clock_kind != ClockKind.INTERNAL:
            raise Conflict("legal clocks are never paused by workflow actions")
        if row.status == DeadlineStatus.PAUSED:
            return
        now = port(ClockPort).now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValidationFailed("clock must return a timezone-aware datetime")
        from_status = row.status
        row.status = DeadlineStatus.PAUSED
        row.paused_at = now
        _record(uow, row, "dl.deadline_paused", from_status=str(from_status))

    def resume_internal(self, uow: UnitOfWork, subject: SubjectRef, rule_id: str) -> None:
        row = self._require_live(uow, subject, rule_id)
        if row.status != DeadlineStatus.PAUSED:
            return
        if row.paused_at is None:
            raise Conflict("paused internal deadline is missing paused_at")
        now = port(ClockPort).now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValidationFailed("clock must return a timezone-aware datetime")
        held = now - row.paused_at
        if held.total_seconds() < 0:
            raise Conflict("clock cannot resume an internal deadline before it was paused")
        row.due_at += held
        row.due_date = row.due_at.astimezone(IST).date()
        row.due_version += 1
        row.status = DeadlineStatus.RUNNING
        row.paused_at = None
        # a new due_version starts its alert ladder again; due now, so the timer worker works out the schedule
        row.alert_level = 0
        row.next_fire_at = now
        _record(uow, row, "dl.deadline_resumed", held_seconds=int(held.total_seconds()))

    def breach(self, uow: UnitOfWork, row: Deadline) -> bool:
        """Mark a running clock past its due time BREACHED, once per due_version. The caller holds the row locked.
        Its alert ladder carries on; closing it later (as MET) records that it closed late."""
        if row.status != DeadlineStatus.RUNNING:
            return False
        row.status = DeadlineStatus.BREACHED
        _record(uow, row, "dl.deadline_breached", clock_kind=row.clock_kind, clock_owner=row.clock_owner)
        return True

    def _live(self, uow: UnitOfWork, subject: SubjectRef, rule_id: str) -> Deadline | None:
        return uow.session.scalar(select(Deadline).where(
            Deadline.subject_type == subject.type, Deadline.subject_id == subject.id,
            Deadline.rule_id == rule_id, Deadline.status.in_(LIVE)).with_for_update())

    def _require_live(self, uow: UnitOfWork, subject: SubjectRef, rule_id: str) -> Deadline:
        row = self._live(uow, subject, rule_id)
        if row is None:
            raise NotFound(f"no running {rule_id} for this {subject.type}")
        return row
