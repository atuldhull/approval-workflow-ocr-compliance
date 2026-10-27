"""Dashboards built from replayable projections, scoped to what the caller may see.

Every number comes from events (or the platform's own delivery tables). Sections whose data does not exist yet
are returned as NOT_AVAILABLE with the dependency, never as zeros or estimates.
"""
import threading
import time
from collections import Counter
from datetime import date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.analytics.projections import ApplicationsProjection, DeadlinesProjection
from app.platform import notifier
from app.platform.db import new_session
from app.platform.registry import port
from app.platform.replay import stored_events, project
from contracts.errors import NotFound
from contracts.ports import CasePort, ClockPort

IST_OFFSET_NOTE = "Dates are compared in Indian Standard Time."
AGE_BUCKETS = ((7, "0-7 days"), (30, "8-30 days"), (60, "31-60 days"), (None, "over 60 days"))


def _bucket(days: int) -> str:
    for limit, label in AGE_BUCKETS:
        if limit is None or days <= limit:
            return label
    return AGE_BUCKETS[-1][1]


def _not_available(key: str, title: str, depends_on: str) -> dict:
    return {"key": key, "title": title, "status": "NOT_AVAILABLE", "depends_on": depends_on}


_cache: dict = {}
_cache_lock = threading.Lock()


def _projected() -> dict:
    """Event projections, rebuilt only when the event log changed. Per process.

    Only what events determine is cached. Regions are NOT cached: they come from the workflow module and can change
    without any event, and a stale region would show a case to the wrong regional office (see _regions).
    The snapshot is REPEATABLE READ, so the cache marker and the events it covers come from one database state.
    """
    with new_session() as s:
        s.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        marker = tuple(s.execute(text(
            "SELECT max(seq), count(*), (SELECT id FROM plat.domain_event ORDER BY seq DESC LIMIT 1) "
            "FROM plat.domain_event")).one())   # the newest event id makes a reset-and-refilled log differ
        with _cache_lock:
            if _cache.get("marker") == marker:
                s.rollback()
                return _cache["data"]
        states, _, unhandled, skipped, unreadable = project(
            stored_events(s), {"applications": ApplicationsProjection(), "deadlines": DeadlinesProjection()})
        cases = port(CasePort)
        known: set[str] = set()   # applications the workflow module has a case record for
        for app_id in states["applications"]:
            try:
                cases.lookup(s, UUID(app_id))
                known.add(app_id)
            except (NotFound, ValueError):
                pass              # events exist but the workflow module has no such case
        s.rollback()
    data = {"states": states, "unhandled": unhandled, "skipped": skipped, "unreadable": unreadable, "known": known}
    with _cache_lock:
        _cache.update(marker=marker, data=data)
    return data


def _regions(apps: dict[str, dict], known: set[str]) -> dict[str, str | None]:
    """Current region of every application, read now through CasePort: one lookup per institution (all of an
    institution's cases share its regional office), so a change in the workflow module shows up immediately."""
    by_institution: dict[str, list[str]] = {}
    for app_id, a in apps.items():
        if app_id in known:
            by_institution.setdefault(a["institution_id"], []).append(app_id)
    region_of: dict[str, str | None] = dict.fromkeys(apps)
    cases = port(CasePort)
    with new_session() as s:
        s.execute(text("SET TRANSACTION READ ONLY"))
        for app_ids in by_institution.values():
            region = None
            for app_id in app_ids:          # normally the first one answers
                try:
                    region = cases.lookup(s, UUID(app_id)).region
                    break
                except NotFound:
                    continue
            for app_id in app_ids:
                region_of[app_id] = region
        s.rollback()
    return region_of


def dashboard(region: str | None) -> dict:
    now: datetime = port(ClockPort).now()
    today: date = now.astimezone(ZoneInfo("Asia/Kolkata")).date()
    p = _projected()
    states, unhandled, skipped = p["states"], p["unhandled"], p["skipped"]
    region_of = _regions(states["applications"], p["known"])
    orphans = sum(1 for r in region_of.values() if r is None)
    unreadable = Counter(u["projection"] for u in p["unreadable"])

    # a regional view only counts cases whose region is known to be that region
    apps = {k: v for k, v in states["applications"].items() if region is None or region_of.get(k) == region}
    deadlines = {k: v for k, v in states["deadlines"].items()
                 if v["subject_type"] == "application" and v["subject_id"] in apps}

    in_process = [a for a in apps.values() if a["status"] == "IN_PROCESS" and a["submitted_at"]]
    ageing = Counter(_bucket((now - datetime.fromisoformat(a["submitted_at"])).days) for a in in_process)

    def coverage(section: dict, prefix: str, projection: str) -> dict:
        """Marks a section PARTIAL when stored events of its module were not understood by the projection."""
        missed = {k: v for k, v in unhandled.items() if k.startswith(prefix)} | skipped[projection]
        if unreadable[projection]:
            missed = missed | {"unreadable": unreadable[projection]}
        if projection == "applications" and orphans and region is None:
            missed = missed | {"without a case record": orphans}
        if missed:
            section["status"] = "PARTIAL"
            section["note"] = (section.get("note", "") + " Not reflected: " + ", ".join(
                f"{n} {k} event(s)" for k, n in sorted(missed.items())) + ". Figures may be out of date.").strip()
        return section

    sections = [
        coverage({"key": "applications", "title": "Applications", "status": "AVAILABLE",
         "source": "Replayed from workflow events",
         "data": {"total": len(apps),
                  "by_status": dict(Counter(a["status"] for a in apps.values())),
                  "by_stage": dict(Counter(a["current_stage"] for a in apps.values() if a["current_stage"])),
                  "by_region": dict(Counter(region_of[k] or "Unknown (no case record)" for k in apps))},
         "note": "Stage is the stage entered at submission; later transitions appear once they are recorded as events."},
                 "wf.", "applications"),
        {"key": "ageing", "title": "Time since submission (applications in process)", "status": "AVAILABLE",
         "source": "Replayed from workflow events",
         "data": {"buckets": {label: ageing.get(label, 0) for _, label in AGE_BUCKETS}}},
        coverage({"key": "deadlines", "title": "Deadlines", "status": "PARTIAL", "source": "Replayed from deadline events",
         "note": "Whether a deadline was met is not reported by events yet, so 'due date passed' may include "
                 f"deadlines that were met. {IST_OFFSET_NOTE}",
         "depends_on": "Person 2: events for deadline closure (met / breached / extended)",
         "data": {"opened": len(deadlines),
                  "due_date_passed": sum(1 for d in deadlines.values() if date.fromisoformat(d["due_date"]) < today),
                  "by_rule": dict(Counter(d["rule_id"] for d in deadlines.values()))}}, "dl.", "deadlines"),
        _not_available("workload", "Officer workload", "Person 1: case assignment data and assignment events"),
        _not_available("evc", "EVC queue", "Person 1: EVC request and slot events"),
        _not_available("compliance", "Compliance and obligations", "Person 2: obligation and evidence events"),
    ]
    if region is None:
        sections.append({"key": "alerts", "title": "Alert delivery", "status": "AVAILABLE",
                         "source": "Notification outbox and delivery attempts", "data": notifier.health(now)})
    else:
        sections.append(_not_available("alerts", "Alert delivery",
                                       "Alerts are not tagged with a region yet (Person 2 alert records)"))
    return {"scope": {"region": region, "as_of": now.isoformat()}, "sections": sections}
