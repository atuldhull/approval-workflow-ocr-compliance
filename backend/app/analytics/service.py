"""Dashboards built from replayable projections, scoped to what the caller may see.

Every number comes from events (or the platform's own delivery tables). Sections whose data does not exist yet
are returned as NOT_AVAILABLE with the dependency, never as zeros or estimates.
"""
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


def dashboard(region: str | None) -> dict:
    now: datetime = port(ClockPort).now()
    today: date = now.astimezone(ZoneInfo("Asia/Kolkata")).date()
    apps_p, dl_p = ApplicationsProjection(), DeadlinesProjection()

    with new_session() as s:
        s.execute(text("SET TRANSACTION READ ONLY"))
        states, _, unhandled, skipped = project(stored_events(s), {"applications": apps_p, "deadlines": dl_p})
        region_of: dict[str, str] = {}
        cases = port(CasePort)
        for app_id in states["applications"]:
            region_of[app_id] = cases.lookup(s, UUID(app_id)).region
        s.rollback()

    apps = {k: v for k, v in states["applications"].items() if region is None or region_of.get(k) == region}
    deadlines = {k: v for k, v in states["deadlines"].items()
                 if v["subject_type"] == "application" and v["subject_id"] in apps}

    in_process = [a for a in apps.values() if a["status"] == "IN_PROCESS" and a["submitted_at"]]
    ageing = Counter(_bucket((now - datetime.fromisoformat(a["submitted_at"])).days) for a in in_process)

    def coverage(section: dict, prefix: str, projection: str) -> dict:
        """Marks a section PARTIAL when stored events of its module were not understood by the projection."""
        missed = {k: v for k, v in unhandled.items() if k.startswith(prefix)} | skipped[projection]
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
                  "by_region": dict(Counter(region_of[k] for k in apps))},
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
