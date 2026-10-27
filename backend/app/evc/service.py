"""Transactional EVC lifecycle behind the shared port; no commits or P2 writes."""
from datetime import timedelta
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select

from app.evc.models import Assignment, EvcRequest
from app.platform.registry import port
from contracts.errors import Conflict, ValidationFailed
from contracts.ports import AuthzPort, CasePort, ClockPort, DeadlinePort, LedgerPort, RulesetPort
from contracts.types import EventIn, ResourceRef, SubjectRef

ACTIVE = ("QUEUED", "PROPOSED", "PUBLISHED")
IST = ZoneInfo("Asia/Kolkata")


def scope(uow, case, action):
    actual = port(CasePort).lookup(uow.session, case.application_id)
    port(AuthzPort).check(uow.principal, f"case.{action}", ResourceRef("application", actual.application_id,
        actual.institution_id, actual.region))
    if actual != case:
        raise Conflict("EVC_CASE_REFERENCE_CHANGED")


def duration(ruleset_key, rule_id):
    rules = port(RulesetPort).get(ruleset_key)
    if rules.key != ruleset_key:
        raise ValidationFailed("EVC_RULESET_PIN_MISMATCH")
    rule = rules.deadline_rules.get(rule_id)
    get = lambda obj, key: obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)
    value = get(rule, "duration")
    source = get(rule, "source_status") or (get(rule, "source") or {}).get("status")
    if (get(rule, "clock_kind") != "INTERNAL" or get(rule, "clock_owner") != "COMMITTEE"
        or get(value, "unit") != "calendar_days" or type(get(value, "value")) is not int
        or get(value, "value") <= 0 or source != "demo_assumption"):
        raise ValidationFailed("EVC_DEADLINE_CONFIG_INVALID")
    return get(value, "value")


def active(session, application_id, *, lock=False):
    query = select(EvcRequest).where(EvcRequest.application_id == application_id, EvcRequest.status.in_(ACTIVE))
    if lock:
        query = query.with_for_update()
    return session.scalar(query)


class EvcService:
    def status(self, session, application_id):
        """Latest request status for workflow guards. PUBLISHED means a published panel/date exists."""
        row = active(session, application_id)
        if row is None:
            row = session.scalar(select(EvcRequest).where(EvcRequest.application_id == application_id)
                                 .order_by(EvcRequest.entry_no.desc().nulls_last(), EvcRequest.requested_at.desc(), EvcRequest.id.desc()).limit(1))
        return row.status if row else None

    def enter(self, uow, case, *, category, ruleset_key, stage_visit_id, rule_id, action, anchor):
        scope(uow, case, action)
        if action not in {"submit", "advance", "advance_to_evc", "revert"}:
            raise ValidationFailed("EVC_ACTION_INVALID")
        existing = uow.session.scalar(select(EvcRequest).where(EvcRequest.stage_visit_ref == stage_visit_id))
        if existing:
            if (existing.application_id, existing.ruleset_key, existing.rule_id) != (case.application_id, ruleset_key, rule_id):
                raise Conflict("EVC_VISIT_REFERENCE_CHANGED")
            return existing.id
        if active(uow.session, case.application_id, lock=True):
            raise Conflict("EVC_REQUEST_ALREADY_ACTIVE")
        if anchor.at.tzinfo is None or anchor.at.utcoffset() is None:
            raise ValidationFailed("EVC_CLOCK_MUST_BE_AWARE")
        days = duration(ruleset_key, rule_id)
        request_id = uuid5(NAMESPACE_URL, f"sih26262:evc:request:{stage_visit_id}")
        start = anchor.at.astimezone(IST).date()
        entry_no = (uow.session.scalar(select(func.max(EvcRequest.entry_no))
                    .where(EvcRequest.application_id == case.application_id)) or 0) + 1
        row = EvcRequest(id=request_id, application_id=case.application_id, institution_ref=case.institution_id,
            region=case.region, category=category, requested_at=anchor.at, earliest_date=start,
            due_by=start + timedelta(days=days), status="QUEUED", priority_key=f"{start.isoformat()}:{request_id}",
            stage_visit_ref=stage_visit_id, ruleset_key=ruleset_key, rule_id=rule_id, entry_no=entry_no)
        uow.session.add(row)
        uow.session.flush()
        row.deadline_ref = port(DeadlinePort).open(uow, SubjectRef("application", case.application_id), rule_id, anchor, ruleset_key)
        uow.session.flush()
        port(LedgerPort).append(uow, EventIn(aggregate_type="application", aggregate_id=case.application_id,
            event_type="evc.request_created", ruleset_rev=ruleset_key, payload=dict(application_id=case.application_id,
                request_id=request_id, institution_ref=case.institution_id, stage_visit_id=stage_visit_id,
                ruleset_key=ruleset_key, rule_id=rule_id, deadline_ref=row.deadline_ref,
                earliest_date=row.earliest_date.isoformat(), due_by=row.due_by.isoformat(),
                source_status="DEMO_ASSUMPTION", assumption_code="EVC_DURATION_UNCONFIRMED")))
        return request_id

    def _finish(self, uow, case, *, ruleset_key, rule_id, action, cancelled=False, reason_code=None):
        scope(uow, case, action)
        allowed = {"reject", "withdraw", "revert"} if cancelled else {
            "complete_evc", "advance", "advance_to_shc", "issue_loa", "issue_eoa", "issue_lod"}
        if action not in allowed:
            raise ValidationFailed("EVC_ACTION_INVALID")
        if cancelled and not reason_code:
            raise ValidationFailed("EVC_CANCELLATION_REASON_REQUIRED")
        row = active(uow.session, case.application_id, lock=True)
        if row is None:
            raise ValidationFailed("EVC_REQUEST_NOT_ACTIVE")
        if (row.ruleset_key, row.rule_id) != (ruleset_key, rule_id) or row.deadline_ref is None:
            raise Conflict("EVC_REQUEST_PIN_MISMATCH")
        if cancelled:
            # Unpublished proposals reserve nothing and are withdrawn with the request; a published
            # assignment still fails closed until an unpublication lifecycle exists.
            if row.status not in ("QUEUED", "PROPOSED") or uow.session.scalar(select(Assignment.id).where(
                    Assignment.evc_request_id == row.id, Assignment.published.is_(True)).limit(1)) is not None:
                raise Conflict("EVC_SCHEDULE_CANCELLATION_REQUIRED")
            uow.session.execute(delete(Assignment).where(Assignment.evc_request_id == row.id, Assignment.published.is_(False)))
        now = port(ClockPort).now()
        if now.tzinfo is None or now.utcoffset() is None or now < row.requested_at:
            raise Conflict("EVC_CLOCK_BEFORE_REQUEST")
        outcome = "WAIVED" if cancelled else "MET"
        row.status = "CANCELLED" if cancelled else "DONE"
        row.closed_at = now
        port(DeadlinePort).close(uow, SubjectRef("application", case.application_id), rule_id, outcome)
        uow.session.flush()
        payload = dict(application_id=case.application_id, request_id=row.id, ruleset_key=ruleset_key,
                       rule_id=rule_id, deadline_ref=row.deadline_ref, outcome=outcome)
        if cancelled:
            payload["reason_code"] = reason_code
        port(LedgerPort).append(uow, EventIn(aggregate_type="application", aggregate_id=case.application_id,
            event_type="evc.request_cancelled" if cancelled else "evc.request_completed", ruleset_rev=ruleset_key,
            reason_code=reason_code, payload=payload))
        return row.id

    def complete(self, uow, case, *, ruleset_key, rule_id, action):
        return self._finish(uow, case, ruleset_key=ruleset_key, rule_id=rule_id, action=action)

    def cancel(self, uow, case, *, ruleset_key, rule_id, action, reason_code):
        return self._finish(uow, case, ruleset_key=ruleset_key, rule_id=rule_id, action=action,
                            cancelled=True, reason_code=reason_code)
