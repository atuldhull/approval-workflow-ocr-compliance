"""Messages about recorded events (not alerts), configured per ruleset in notifications.yaml, and the context every
message is rendered with.

The notifier reads the event log in order from a cursor (plat.notify_cursor) and queues one outbox row per event,
recipient group and channel. A unique constraint on (source_event_id, recipient_ref, channel) and the cursor moving
in the same transaction make this idempotent: re-reading an event queues nothing new. Ledger appends are serialised
until commit, so every event at or below the highest visible seq is already committed and none is skipped.

Recipients are role groups resolved for the case's institution and region, exactly as alerts are. A vacant group
is skipped: nobody holds the post, and an event message has no ladder to climb.

Context (case reference, rule in words, due date, links) is read when a message is delivered, from the alert and
its deadline or from the event, so the message describes the record it points to. Only ids, kinds and dates are
used - never names, addresses or free text.
"""
import logging
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import UUID

import yaml
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.platform.models import NotifyCursor, Outbox
from app.platform.providers import TEMPLATES
from app.platform.recipients import directory
from app.platform.registry import port
from app.platform.settings import settings
from contracts.enums import Role
from contracts.errors import NotFound, ValidationFailed
from contracts.ports import CasePort, RulesetPort
from contracts.types import OutboundMessage, ResourceRef

log = logging.getLogger("notifier.events")
CURSOR = "event-notifications"
OWNER = "owner"
CHANNELS = frozenset({"in_app", "email", "sms"})
ADDRESSABLE = frozenset(r.value for r in Role) - {Role.SYSTEM.value, Role.AUDITOR.value}
LIVE = ("RUNNING", "PAUSED", "BREACHED")


@dataclass(frozen=True)
class EventNotice:
    template: str | dict          # a template, or {field: <payload field>, <value>: <template>, ...}
    to: tuple[str, ...]           # roles, or OWNER for the role that owns the deadline in the event
    rule: str | None              # deadline rule whose live clock on the case gives the due date
    channels: tuple[str, ...]

    def template_for(self, payload: dict) -> str | None:
        if isinstance(self.template, str):
            return self.template
        return self.template.get(str(payload.get(self.template["field"])))


@dataclass(frozen=True)
class NoticeConfig:
    source_status: str
    events: dict[str, EventNotice]
    rule_names: dict[str, str]

    def rule_name(self, rule_id: str | None) -> str | None:
        if not rule_id:
            return None
        return self.rule_names.get(rule_id) or rule_id.replace("_", " ").lower()


def parse(raw: dict) -> NoticeConfig:
    if not isinstance(raw, dict):
        raise ValidationFailed("notifications.yaml must be a mapping")
    channels = tuple(raw.get("channels") or ())
    if not channels or not set(channels) <= CHANNELS:
        raise ValidationFailed(f"notifications: channels must be a non-empty subset of {sorted(CHANNELS)}")
    events: dict[str, EventNotice] = {}
    for event_type, item in (raw.get("events") or {}).items():
        ctx = f"notifications: {event_type}"
        if not isinstance(item, dict):
            raise ValidationFailed(f"{ctx}: must be a mapping")
        template = item.get("template")
        names = [template] if isinstance(template, str) else (
            [v for k, v in template.items() if k != "field"] if isinstance(template, dict) and "field" in template
            else [None])
        if not names or any(n not in TEMPLATES for n in names):
            raise ValidationFailed(f"{ctx}: template must be one of {sorted(TEMPLATES)} (or keyed by a field)")
        to = tuple(item.get("to") or ())
        if not to or any(r != OWNER and r not in ADDRESSABLE for r in to):
            raise ValidationFailed(f"{ctx}: 'to' must list '{OWNER}' or roles from {sorted(ADDRESSABLE)}")
        own = tuple(item.get("channels") or channels)
        if not set(own) <= CHANNELS:
            raise ValidationFailed(f"{ctx}: unknown channel")
        events[event_type] = EventNotice(template, to, item.get("rule"), own)
    names = raw.get("rule_names") or {}
    if not isinstance(names, dict) or any(not isinstance(v, str) for v in names.values()):
        raise ValidationFailed("notifications: rule_names maps rule ids to words")
    return NoticeConfig(str((raw.get("source") or {}).get("status", "unknown")), events, dict(names))


_cache: dict[Path, tuple[float, NoticeConfig]] = {}
_cache_lock = threading.Lock()


def _folder(key: str) -> Path | None:
    """The folder holding notifications.yaml for a ruleset key; an overlay uses the ruleset it extends."""
    for _ in range(5):
        name, _, revision = key.partition("@")
        folder = settings.rulesets_dir / name / revision
        if (folder / "notifications.yaml").is_file():
            return folder
        overlay = folder / "overlay.yaml"
        if not overlay.is_file():
            return None
        key = (yaml.safe_load(overlay.read_text(encoding="utf-8")) or {}).get("extends") or ""
    return None


def config_for(ruleset_key: str | None) -> NoticeConfig | None:
    """The notification map of a ruleset (the default ruleset when the event names none); None if it has none."""
    folder = _folder(ruleset_key or settings.default_ruleset) or _folder(settings.default_ruleset)
    if folder is None:
        return None
    path = folder / "notifications.yaml"
    mtime = path.stat().st_mtime
    with _cache_lock:
        hit = _cache.get(path)
        if hit and hit[0] == mtime:
            return hit[1]
    config = parse(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    with _cache_lock:
        _cache[path] = (mtime, config)
    return config


def queue(session: Session, msg: OutboundMessage, now: datetime) -> bool:
    """Inserts one outbox row unless it is already queued. True when a row was written."""
    target = ["source_event_id", "recipient_ref", "channel"] if msg.source_event_id else ["alert_id", "channel"]
    row = session.execute(insert(Outbox).values(
        created_at=now, alert_id=msg.alert_id, source_event_id=msg.source_event_id, channel=msg.channel,
        template=msg.template, recipient_ref=msg.recipient_ref, status="PENDING", attempts=0,
    ).on_conflict_do_nothing(index_elements=target).returning(Outbox.id)).first()
    return row is not None


# --- which case a record belongs to --------------------------------------------------------------------------------

def application_of(session: Session, subject_type: str, subject_id) -> str | None:
    """The application a deadline subject belongs to: itself, or through its obligation, letter or document."""
    sql = {
        "application": None,
        "obligation": "SELECT application_id FROM cmp.obligation WHERE id = :id",
        "approval_letter": "SELECT application_id FROM cmp.approval_letter WHERE id = :id",
        "document": "SELECT application_id FROM doc.document WHERE document_id = :id",
        "document_version": "SELECT application_id FROM doc.document_version WHERE document_version_id = :id",
    }
    if subject_type not in sql:
        return None
    if sql[subject_type] is None:
        return str(subject_id)
    found = session.execute(text(sql[subject_type]), {"id": str(subject_id)}).scalar()
    return str(found) if found else None


def document_name(session: Session, subject_type: str, subject_id) -> str | None:
    """The checklist item a document deadline is about, in words (its doc_type), never the file name. A document
    validity obligation names the document it tracks."""
    if subject_type == "document":
        sql = "SELECT doc_type FROM doc.document WHERE document_id = :id"
    elif subject_type == "obligation":
        sql = "SELECT doc_type FROM cmp.obligation WHERE id = :id"
    elif subject_type == "document_version":
        sql = ("SELECT d.doc_type FROM doc.document_version v JOIN doc.document d ON d.document_id = v.document_id "
               "WHERE v.document_version_id = :id")
    else:
        return None
    found = session.execute(text(sql), {"id": str(subject_id)}).scalar()
    return found.replace("_", " ").lower() if found else None


# --- turning events into outbox rows -------------------------------------------------------------------------------

def _owner_role(ruleset_rev: str | None, clock_owner: str) -> Role | None:
    try:
        alerts = getattr(port(RulesetPort).get(ruleset_rev or settings.default_ruleset).deadline_rules, "alerts", None)
    except Exception:  # noqa: BLE001 - an unreadable ruleset leaves the owner unknown; the event is skipped
        return None
    return alerts.owner_roles.get(str(clock_owner)) if alerts is not None else None


def _alerted_at_breach(ruleset_rev: str | None, rule_id: str | None, clock_owner: str) -> set[Role]:
    """Roles the rule's alert ladder already tells at the due time; a breach notice to them would say it twice."""
    try:
        rules = port(RulesetPort).get(ruleset_rev or settings.default_ruleset).deadline_rules
        alerts, rule = getattr(rules, "alerts", None), rules.get(rule_id) if rule_id else None
        if alerts is None or rule is None:
            return set()
        return {alerts.role_for(step, clock_owner) for step in alerts.ladder(rule) if step.offset == timedelta(0)}
    except Exception:  # noqa: BLE001 - an unreadable ruleset suppresses nothing
        return set()


def messages_for(session: Session, event_id: UUID, event_type: str, payload: dict,
                 ruleset_rev: str | None) -> list[OutboundMessage]:
    """The messages one event calls for under its ruleset's notification map; [] when none, or no one to tell."""
    config = config_for(ruleset_rev)
    notice = config.events.get(event_type) if config else None
    template = notice.template_for(payload) if notice else None
    if template is None:
        return []
    app_id = payload.get("application_id") or application_of(session, payload.get("subject_type", ""),
                                                               payload.get("subject_id"))
    if app_id is None:
        log.info("event %s (%s) has no case to address; no message", event_id, event_type)
        return []
    try:
        case = port(CasePort).lookup(session, UUID(str(app_id)))
    except NotFound:
        log.info("event %s (%s) names a case with no record; no message", event_id, event_type)
        return []
    resource = ResourceRef("application", case.application_id, owner_institution_id=case.institution_id,
                           region=case.region)
    refs: list[UUID] = []
    skip = (_alerted_at_breach(ruleset_rev, payload.get("rule_id"), payload.get("clock_owner", ""))
            if event_type == "dl.deadline_breached" else set())
    for to in notice.to:
        role = _owner_role(ruleset_rev, payload.get("clock_owner", "")) if to == OWNER else Role(to)
        if role is None or role in skip:
            continue
        ref = directory.resolve(role, resource)
        if ref not in refs and directory.has_members(session, ref):
            refs.append(ref)
    return [OutboundMessage(None, channel, template, ref, source_event_id=event_id)
            for ref in refs for channel in notice.channels]


def dispatch(session: Session, now: datetime, limit: int = 500) -> int:
    """Queues messages for events recorded since the cursor; returns how many rows were written. The caller commits.

    The cursor row is locked first, so two workers never read the same stretch of the log at once."""
    session.execute(insert(NotifyCursor).values(name=CURSOR, seq=0, updated_at=now)
                    .on_conflict_do_nothing(index_elements=["name"]))
    after = session.execute(text("SELECT seq FROM plat.notify_cursor WHERE name = :n FOR UPDATE"),
                            {"n": CURSOR}).scalar_one()
    upto = session.execute(text("SELECT coalesce(max(seq), 0) FROM plat.domain_event")).scalar_one()
    config = config_for(None)
    types = sorted(config.events) if config else []
    rows = session.execute(text(
        "SELECT seq, id, event_type, payload, ruleset_rev FROM plat.domain_event "
        "WHERE seq > :after AND seq <= :upto AND event_type = ANY(:types) ORDER BY seq LIMIT :limit"),
        {"after": after, "upto": upto, "types": types, "limit": limit}).all() if types and upto > after else []
    written = 0
    for r in rows:
        for msg in messages_for(session, r.id, r.event_type, r.payload, r.ruleset_rev):
            written += queue(session, msg, now)
    reached = rows[-1].seq if len(rows) == limit else upto
    if reached != after:
        session.execute(text("UPDATE plat.notify_cursor SET seq = :seq, updated_at = :now WHERE name = :n"),
                        {"seq": reached, "now": now, "n": CURSOR})
    return written


# --- what a message is about ---------------------------------------------------------------------------------------

def _day(value) -> str:
    d = value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
    return d.strftime("%d %b %Y")


def _words(code: str | None) -> str | None:
    return code.replace("_", " ").lower() if code else None


LETTERS = {"LOA": "the Letter of Approval", "EOA": "the Extension of Approval", "LOD": "the Letter of Deficiency",
           "LOR": "the Letter of Rejection", "CORRIGENDUM": "the corrigendum"}
SLOTS = {"AM": "morning", "PM": "afternoon"}
CHANGES = {"wf.application_submitted": "the application was submitted",
           "wf.transition_applied": "the case moved on its route",
           "wf.deficiency_recorded": "deficiencies were recorded",
           "evc.request_created": "an expert visit was requested",
           "cmp.letter_registered": "a letter was registered",
           "dl.deadline_opened": "a deadline clock started"}


def _live_due(session: Session, app_id: str, rule_id: str) -> date | None:
    return session.execute(text(
        "SELECT due_date FROM dl.deadline WHERE subject_type = 'application' AND subject_id = :app "
        "AND rule_id = :rule AND status = ANY(:live) ORDER BY due_date DESC LIMIT 1"),
        {"app": app_id, "rule": rule_id, "live": list(LIVE)}).scalar()


def _case(app_id: str | None) -> dict:
    return {"case": app_id[:8], "application_id": app_id} if app_id else {}


def _alert_context(session: Session, alert_id: UUID) -> dict | None:
    row = session.execute(text(
        "SELECT a.subject_type, a.subject_id, a.level, d.rule_id, d.due_date, d.ruleset, d.revision "
        "FROM dl.alert a JOIN dl.deadline d ON d.id = a.deadline_id WHERE a.id = :id"), {"id": str(alert_id)}).first()
    if row is None:
        return None
    config = config_for(f"{row.ruleset}@{row.revision}")
    app_id = application_of(session, row.subject_type, row.subject_id)
    ctx = {**_case(app_id), "rule_id": row.rule_id, "due_date": row.due_date.isoformat(), "due": _day(row.due_date),
           "rule": config.rule_name(row.rule_id) if config else _words(row.rule_id), "level": row.level}
    if row.subject_type == "obligation":
        kind = session.execute(text("SELECT kind FROM cmp.obligation WHERE id = :id"),
                               {"id": str(row.subject_id)}).scalar()
        ctx.update(obligation_id=str(row.subject_id), obligation=_words(kind))
    if (doc := document_name(session, row.subject_type, row.subject_id)) is not None:
        ctx["document"] = doc
    return ctx


def _event_context(session: Session, event_id: UUID) -> dict | None:
    row = session.execute(text("SELECT event_type, payload, ruleset_rev FROM plat.domain_event WHERE id = :id"),
                          {"id": str(event_id)}).first()
    if row is None:
        return None
    p, kind = row.payload, row.event_type
    config = config_for(row.ruleset_rev)
    notice = config.events.get(kind) if config else None
    app_id = p.get("application_id") or application_of(session, p.get("subject_type", ""), p.get("subject_id"))
    ctx = {**_case(app_id), "event_type": kind, "change": CHANGES.get(kind) or _words(kind.partition(".")[2])}
    rule_id = p.get("rule_id") or (notice.rule if notice else None)
    if rule_id:
        ctx.update(rule_id=rule_id, rule=config.rule_name(rule_id) if config else _words(rule_id))
    if kind == "wf.deficiency_recorded":
        ctx.update(items=len(p["items"]), round=p["round_no"])
        due = _live_due(session, app_id, rule_id) if rule_id else None
        if due:
            ctx.update(due=_day(due), due_date=due.isoformat())
    elif kind == "evc.assignment_published":
        ctx.update(visit=_day(p["date"]), visit_date=p["date"], slot=SLOTS.get(p["slot_part"], p["slot_part"]),
                   evc_request_id=str(p["request_id"]), due=_day(p["due_by"]), due_date=p["due_by"])
    elif kind == "cmp.evidence_verified":
        ob = session.execute(text("SELECT kind, due_date FROM cmp.obligation WHERE id = :id"),
                             {"id": str(p["obligation_id"])}).first()
        ctx.update(obligation_id=str(p["obligation_id"]), decision=p["decision"],
                   reason=_words(p.get("reason_code")) or "no reason code")
        if ob is not None:
            ctx["obligation"] = _words(ob.kind)
            if ob.due_date:
                ctx.update(due=_day(ob.due_date), due_date=ob.due_date.isoformat())
    elif kind == "cmp.letter_registered":
        ctx.update(letter=LETTERS.get(p["letter_type"], _words(p["letter_type"])), issued=_day(p["issue_date"]),
                   letter_id=str(p["letter_id"]))
    elif kind.startswith("dl.") and p.get("due_date"):
        ctx.update(due=_day(p["due_date"]), due_date=str(p["due_date"]))
        if p.get("subject_type") == "obligation":
            ctx["obligation_id"] = str(p["subject_id"])
        if (doc := document_name(session, p.get("subject_type", ""), p.get("subject_id"))) is not None:
            ctx["document"] = doc
    return ctx


def context_for(session: Session, alert_id: UUID | None, source_event_id: UUID | None) -> dict | None:
    """What a message is about, for its wording and its links; None when the record cannot be found."""
    if alert_id is not None:
        return _alert_context(session, alert_id)
    if source_event_id is not None:
        return _event_context(session, source_event_id)
    return None
