"""Dashboards built from replayable projections, scoped to what the caller may see.

Every number comes from events (or the platform's own delivery tables). A section whose figures cannot be worked
out is returned as NOT_AVAILABLE with the reason, never as zeros or estimates.
"""
import threading
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from statistics import median
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.analytics.projections import ALL
from app.compliance.validity import expiring_window_days
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
        states, _, unhandled, skipped, unreadable = project(stored_events(s), {p.name: p for p in ALL})
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


OPEN_CLOCK = ("RUNNING", "PAUSED", "BREACHED")
OPEN_EVC = ("QUEUED", "PROPOSED", "PUBLISHED")
TOP_OFFICERS = 10
TOP_INSTITUTIONS = 10


def _regional_delivery(region: str, now: datetime) -> dict:
    """Delivery of the messages queued for alerts raised in one region. Alerts record their region, so the outbox is
    joined to them; messages with no alert in this region are not counted."""
    since = now - timedelta(hours=24)
    with new_session() as s:
        s.execute(text("SET TRANSACTION READ ONLY"))
        by_status = dict(s.execute(text(
            "SELECT o.status, count(*) FROM plat.outbox o JOIN dl.alert a ON a.id = o.alert_id "
            "WHERE a.region = :region GROUP BY o.status"), {"region": region}).all())
        first = s.execute(text("""
            SELECT outcome, count(*) FROM (
                SELECT DISTINCT ON (d.outbox_id) d.outcome, d.finished_at
                  FROM plat.delivery_attempt d
                  JOIN plat.outbox o ON o.id = d.outbox_id JOIN dl.alert a ON a.id = o.alert_id
                 WHERE a.region = :region ORDER BY d.outbox_id, d.finished_at) f
             WHERE finished_at >= :since GROUP BY outcome"""), {"region": region, "since": since}).all()
        s.rollback()
    first_tries = sum(n for _, n in first)
    first_ok = sum(n for o, n in first if o == "DELIVERED")
    return {"by_status": {k: by_status.get(k, 0) for k in ("PENDING", "SENDING", "DELIVERED", "DEAD")},
            "first_tries_24h": first_tries,
            "first_try_success_rate_24h": round(first_ok / first_tries, 3) if first_tries else None}


def _alerts_raised(region: str | None) -> dict:
    """Deadline alerts by status and by the role they are addressed to (dl.alert carries the region)."""
    with new_session() as s:
        s.execute(text("SET TRANSACTION READ ONLY"))
        rows = s.execute(text(
            "SELECT status, role, count(*) FROM dl.alert WHERE CAST(:region AS text) IS NULL OR region = :region "
            "GROUP BY status, role"), {"region": region}).all()
        s.rollback()
    by_status, by_role = Counter(), Counter()
    for status, role, n in rows:
        by_status[status] += n
        if status in ("OPEN", "ESCALATED"):
            by_role[role] += n
    return {"by_status": dict(by_status), "open_by_role": dict(by_role)}


def _by_institution(apps: dict, deadlines: dict, case_of, overdue) -> dict:
    rows: dict[str, Counter] = defaultdict(Counter)
    for a in apps.values():
        row = rows[a["institution_id"]]
        row["cases"] += 1
        row["in_process"] += a["status"] == "IN_PROCESS"
    for d in deadlines.values():
        if d["status"] in OPEN_CLOCK and overdue(d):
            rows[apps[case_of(d["subject_type"], d["subject_id"])]["institution_id"]]["overdue"] += 1
    ordered = sorted(rows.items(), key=lambda kv: (-kv[1]["overdue"], -kv[1]["in_process"], kv[0]))
    return {"institutions": len(rows),
            "rows": [{"institution_id": k, "cases": c["cases"], "in_process": c["in_process"],
                      "overdue": c["overdue"]} for k, c in ordered[:TOP_INSTITUTIONS]]}


def _validity_states(records: list[dict], deadlines: dict[str, dict], today: date, overdue) -> dict:
    """Document validity records by state, as the Compliance screen reads them (app.compliance.validity): renewed
    when met, under review while a renewal waits for an officer, expired once its clock has run out, expiring soon
    from the earliest advance reminder."""
    window = expiring_window_days() if records else 0
    counts = Counter()
    for o in records:
        if o["status"] == "MET":
            counts["renewed"] += 1
        elif o["status"] == "EVIDENCE_SUBMITTED":
            counts["renewal_under_review"] += 1
        elif overdue(deadlines.get(o["deadline_id"]) if o["deadline_id"] else None):
            counts["expired"] += 1
        elif o["due_date"] and (date.fromisoformat(o["due_date"]) - today).days <= window:
            counts["expiring_soon"] += 1
        else:
            counts["valid"] += 1
    return {"records": len(records), **{k: counts[k] for k in
                                        ("valid", "expiring_soon", "expired", "renewal_under_review", "renewed")}}


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
    records = states["compliance"]

    def case_of(subject_type: str, subject_id: str) -> str | None:
        """The application a deadline belongs to: directly, or through its obligation or approval letter."""
        if subject_type == "application":
            return subject_id
        found = records.get(subject_id) if subject_type in ("obligation", "approval_letter") else None
        return found["application_id"] if found else None

    deadlines = {k: v for k, v in states["deadlines"].items() if case_of(v["subject_type"], v["subject_id"]) in apps}

    def overdue(d: dict | None) -> bool:
        return d is not None and (d["status"] == "BREACHED" or (
            d["status"] == "RUNNING" and date.fromisoformat(d["due_date"]) < today))

    in_process = [a for a in apps.values() if a["status"] == "IN_PROCESS" and a["submitted_at"]]
    ageing = Counter(_bucket((now - datetime.fromisoformat(a["submitted_at"])).days) for a in in_process)

    def coverage(section: dict, prefix: str, *projections: str) -> dict:
        """Marks a section PARTIAL when stored events of its module were not understood by its projections."""
        missed = {k: v for k, v in unhandled.items() if k.startswith(prefix)}
        for projection in projections:
            missed |= skipped[projection]
            if unreadable[projection]:
                missed |= {f"unreadable ({projection})": unreadable[projection]}
        if "applications" in projections and orphans and region is None:
            missed = missed | {"without a case record": orphans}
        if missed:
            section["status"] = "PARTIAL"
            section["note"] = (section.get("note", "") + " Not reflected: " + ", ".join(
                f"{n} {k} event(s)" for k, n in sorted(missed.items())) + ". Figures may be out of date.").strip()
        return section

    # time in the current stage, from wf.stage_entered; a case with no recorded entry is counted, not guessed
    in_stage: dict[str, list[int]] = defaultdict(list)
    unrecorded_entry = 0
    for a in in_process:
        if a["current_stage"] is None:
            continue
        if a["stage_since"]:
            in_stage[a["current_stage"]].append((now - datetime.fromisoformat(a["stage_since"])).days)
        else:
            unrecorded_entry += 1
    stage_rows = [{"stage": st, "cases": len(days), "median_days": median(days), "max_days": max(days)}
                  for st, days in in_stage.items()]
    stage_age = Counter(_bucket(d) for days in in_stage.values() for d in days)
    most = max(stage_rows, key=lambda r: (r["cases"], r["median_days"]), default=None)
    slowest = max(stage_rows, key=lambda r: (r["median_days"], r["cases"]), default=None)

    # deadlines: every clock of a case in scope, including those of its obligations and letters
    clock_status = Counter(d["status"] for d in deadlines.values())
    open_clocks = [d for d in deadlines.values() if d["status"] in OPEN_CLOCK]

    # workload: committees and their tasks on cases still in process
    committees = {k: c for k, c in states["committees"].items()
                  if c["kind"] == "committee" and c["application_id"] in apps
                  and apps[c["application_id"]]["status"] == "IN_PROCESS"}
    tasks = [t for t in states["committees"].values() if t["kind"] == "task" and t["committee_id"] in committees]
    officers: dict[str, dict] = {}
    for c in committees.values():
        for user in c["members"]:
            officers.setdefault(user, {"user_ref": user, "open_tasks": 0, "committees": 0})["committees"] += 1
    for t in tasks:
        officers.setdefault(t["assignee"], {"user_ref": t["assignee"], "open_tasks": 0, "committees": 0})[
            "open_tasks"] += 1
    by_committee: dict[str, dict] = {}
    for c in committees.values():
        by_committee.setdefault(c["type"], {"committees": 0, "open_tasks": 0, "cases": set()})
        by_committee[c["type"]]["committees"] += 1
        by_committee[c["type"]]["cases"].add(c["application_id"])
    for t in tasks:
        by_committee[committees[t["committee_id"]]["type"]]["open_tasks"] += 1

    # EVC queue
    evc = {k: r for k, r in states["evc"].items() if r["application_id"] in apps}
    open_evc = [r for r in evc.values() if r["status"] in OPEN_EVC]
    published_runs = {r["run_id"] for r in evc.values() if r["status"] in ("PUBLISHED", "DONE") and r["run_id"]}

    # compliance
    obligations = [o for o in records.values() if o["kind"] == "obligation" and o["application_id"] in apps]
    evidence = [e for e in records.values() if e["kind"] == "evidence" and e["application_id"] in apps]
    letters = [x for x in records.values() if x["kind"] == "letter" and x["application_id"] in apps]
    validity = _validity_states([o for o in obligations if o["type"] == "DOCUMENT_VALIDITY"], deadlines, today,
                                overdue)

    sections = [
        coverage({"key": "applications", "title": "Applications", "status": "AVAILABLE",
         "source": "Replayed from workflow events",
         "data": {"total": len(apps),
                  "by_status": dict(Counter(a["status"] for a in apps.values())),
                  "by_stage": dict(Counter(a["current_stage"] for a in apps.values() if a["current_stage"])),
                  "by_region": dict(Counter(region_of[k] or "Unknown (no case record)" for k in apps))}},
                 "wf.", "applications", "deficiencies", "committees"),
        {"key": "ageing", "title": "Time since submission (applications in process)", "status": "AVAILABLE",
         "source": "Replayed from workflow events",
         "data": {"buckets": {label: ageing.get(label, 0) for _, label in AGE_BUCKETS}}},
        coverage({"key": "flow", "title": "Time in current stage and bottlenecks", "status": "AVAILABLE",
         "source": "Replayed from workflow stage events",
         "note": "Days since each case in process entered its current stage. The bottleneck is the stage holding the "
                 "most cases; the slowest is the stage with the longest median time."
                 + (f" {unrecorded_entry} case(s) have no recorded stage entry and are not timed." if unrecorded_entry
                    else ""),
         "data": {"buckets": {label: stage_age.get(label, 0) for _, label in AGE_BUCKETS},
                  "by_stage": sorted(stage_rows, key=lambda r: (-r["cases"], r["stage"])),
                  "bottleneck": most and most["stage"], "slowest": slowest and slowest["stage"],
                  "not_timed": unrecorded_entry}}, "wf.", "applications"),
        coverage({"key": "institutions", "title": "By institution", "status": "AVAILABLE",
         "source": "Replayed from workflow and deadline events",
         "note": "Institutions are shown by reference. Overdue: open clocks of the institution's cases that are "
                 f"breached or past their due date. {IST_OFFSET_NOTE}",
         "data": _by_institution(apps, deadlines, case_of, overdue)}, "wf.", "applications"),
        coverage({"key": "deadlines", "title": "Deadlines", "status": "AVAILABLE",
         "source": "Replayed from deadline events",
         "note": f"Overdue counts running clocks past their due date and clocks marked breached. {IST_OFFSET_NOTE}",
         "data": {"opened": len(deadlines), "open": len(open_clocks),
                  "overdue": sum(1 for d in open_clocks if overdue(d)),
                  "met": clock_status.get("MET", 0),
                  "met_late": sum(1 for d in deadlines.values() if d["status"] == "MET" and d["late"]),
                  "by_status": dict(clock_status),
                  "by_rule": dict(Counter(d["rule_id"] for d in open_clocks))}}, "dl.", "deadlines"),
        coverage({"key": "workload", "title": "Officer workload", "status": "AVAILABLE",
         "source": "Replayed from committee events",
         "note": "Committees and tasks on cases still in process. A task counts as open until its case is decided; "
                 "tasks are not closed one by one.",
         "data": {"committees": len(committees), "open_tasks": len(tasks), "officers": len(officers),
                  "by_officer": sorted(officers.values(), key=lambda o: (-o["open_tasks"], -o["committees"],
                                                                          o["user_ref"]))[:TOP_OFFICERS],
                  "by_committee": {k: {"committees": v["committees"], "open_tasks": v["open_tasks"],
                                       "cases": len(v["cases"])} for k, v in sorted(by_committee.items())}}},
                 "wf.", "committees"),
        coverage({"key": "evc", "title": "EVC queue", "status": "AVAILABLE", "source": "Replayed from EVC events",
         "note": "Overdue: an open request whose EVC clock is breached or past its due date. Visit slots are "
                 "simulated.",
         "data": {"requests": len(evc), "open": len(open_evc),
                  "by_status": dict(Counter(r["status"] for r in evc.values())),
                  "overdue": sum(1 for r in open_evc if overdue(deadlines.get(r["deadline_id"]))),
                  "published_schedules": len(published_runs),
                  "upcoming_visits": sum(1 for r in evc.values() if r["status"] == "PUBLISHED" and r["visit_date"]
                                         and date.fromisoformat(r["visit_date"]) >= today)}}, "evc.", "evc"),
        coverage({"key": "compliance", "title": "Compliance and obligations", "status": "AVAILABLE",
         "source": "Replayed from compliance and deadline events",
         "note": "Overdue: not met and its clock is breached or past its due date. Document validity records count "
                 "as obligations too; an expired document is an overdue one.",
         "data": {"obligations": len(obligations),
                  "by_status": dict(Counter(o["status"] for o in obligations)),
                  "by_kind": dict(Counter(o["type"] for o in obligations)),
                  "overdue": sum(1 for o in obligations if o["status"] != "MET" and overdue(
                      deadlines.get(o["deadline_id"]) if o["deadline_id"] else None)),
                  "awaiting_verification": sum(1 for e in evidence if e["status"] == "SUBMITTED"),
                  "letters": dict(Counter(x["type"] for x in letters)),
                  "document_validity": validity}}, "cmp.", "compliance"),
    ]
    raised = _alerts_raised(region)
    if region is None:
        sections.append({"key": "alerts", "title": "Alert delivery", "status": "AVAILABLE",
                         "source": "Notification outbox, delivery attempts and deadline alerts",
                         "data": {**notifier.health(now), "alerts": raised}})
    else:
        sections.append({"key": "alerts", "title": "Alert delivery", "status": "AVAILABLE",
                         "source": f"Notification outbox joined to the deadline alerts raised in {region}",
                         "data": {**_regional_delivery(region, now), "alerts": raised}})
    return {"scope": {"region": region, "as_of": now.isoformat()}, "sections": sections}
