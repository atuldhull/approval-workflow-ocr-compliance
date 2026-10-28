"""Reproducible reports and event-log exports.

A report states the ledger head it was computed from, and its snapshot hash covers the report body plus that head.
Recomputing at the same ledger state gives the same hash; any new event changes it. Reports that age something
(days overdue, time in stage) also state the IST date they were computed for, and the hash covers that date, so the
same ledger on the same day gives the same hash.

Every report is registered in REPORTS with its title, columns and source. A new report type is one builder
function plus one `Report(...)` entry; the endpoint, the CSV download and the screen pick it up from the registry.
"""
import csv
import hashlib
import io
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from statistics import mean, median
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.analytics.service import OPEN_EVC, _projected, _regions
from app.platform.db import new_session
from app.platform.ledger import canonical
from app.platform.registry import port
from contracts.ports import ClockPort, RulesetPort

UNKNOWN_REGION = "Unknown (no case record)"
IST = ZoneInfo("Asia/Kolkata")


def _ledger_head(session) -> dict:
    row = session.execute(text(
        "SELECT e.seq, l.entry_hash FROM plat.domain_event e JOIN plat.ledger_entry l ON l.seq = e.seq "
        "ORDER BY e.seq DESC LIMIT 1")).first()
    return {"seq": row[0], "entry_hash": row[1]} if row else {"seq": 0, "entry_hash": None}


def _snapshot(body: dict, head: dict) -> str:
    return hashlib.sha256(canonical({"report": body, "ledger_head": head}).encode()).hexdigest()


def _sealed(body: dict) -> dict:
    with new_session() as s:
        head = _ledger_head(s)
    return {**body, "ledger_head": head, "snapshot_hash": _snapshot(body, head)}


def _coverage(p: dict, *projections: str, note: str) -> dict:
    return {"unhandled_event_types": dict(p["unhandled"]),
            "skipped_versions": {k: n for name in projections for k, n in p["skipped"][name].items()},
            "note": note}


@dataclass(frozen=True)
class Scope:
    """What every report reads: the projections, each case's region, and the clocks of the cases in scope."""
    p: dict
    apps: dict[str, dict]           # applications in scope
    region_of: dict[str, str]
    deadlines: dict[str, dict]      # clocks of those applications, including their obligations' and letters'
    case_of_deadline: dict[str, str | None]
    today: date
    region: str | None


def _scope(region: str | None) -> Scope:
    p = _projected()
    states = p["states"]
    region_of = {k: r or UNKNOWN_REGION for k, r in _regions(states["applications"], p["known"]).items()}
    apps = {k: v for k, v in states["applications"].items() if region is None or region_of.get(k) == region}
    records = states["compliance"]

    def case_of(subject_type: str, subject_id: str) -> str | None:
        if subject_type == "application":
            return subject_id
        found = records.get(subject_id) if subject_type in ("obligation", "approval_letter") else None
        return found["application_id"] if found else None

    case_of_deadline = {k: case_of(d["subject_type"], d["subject_id"]) for k, d in states["deadlines"].items()}
    deadlines = {k: d for k, d in states["deadlines"].items() if case_of_deadline[k] in apps}
    today = port(ClockPort).now().astimezone(IST).date()
    return Scope(p, apps, region_of, deadlines, case_of_deadline, today, region)


def _days_overdue(d: dict | None, today: date) -> int | None:
    """Whole days past the due date for an open clock that is breached or past due; None when it is not overdue."""
    if d is None or d["status"] not in ("RUNNING", "BREACHED"):
        return None
    late = (today - date.fromisoformat(d["due_date"])).days
    if d["status"] == "BREACHED":
        return max(late, 0)
    return late if late > 0 else None


def _ist_date(iso: str) -> date:
    return datetime.fromisoformat(iso).astimezone(IST).date()


def pendency(region: str | None) -> dict:
    """Applications in process, by regional office and current stage (replayed from workflow events)."""
    p = _projected()
    apps = p["states"]["applications"]
    region_of = _regions(apps, p["known"])
    grid: dict[str, Counter] = defaultdict(Counter)
    for app_id, a in apps.items():
        r = region_of.get(app_id) or UNKNOWN_REGION
        if a["status"] != "IN_PROCESS" or (region is not None and r != region):
            continue
        grid[r][a["current_stage"] or "UNKNOWN"] += 1
    body = {
        "type": "pendency",
        "scope": {"region": region},
        "rows": [{"region": r, "stage": st, "count": n}
                 for r in sorted(grid) for st, n in sorted(grid[r].items())],
        "total": sum(sum(c.values()) for c in grid.values()),
        "coverage": {"unhandled_event_types": dict(p["unhandled"]),
                     "skipped_versions": dict(p["skipped"]["applications"]),
                     "note": "Stage is the stage recorded by workflow events this projection understands."},
    }
    return _sealed(body)


def evc_status(region: str | None) -> dict:
    """EVC requests per region: where each stands in the queue, how many are overdue, and how many were completed."""
    sc = _scope(region)
    rows: dict[str, Counter] = defaultdict(Counter)
    for r in sc.p["states"]["evc"].values():
        if r["application_id"] not in sc.apps:
            continue
        row = rows[sc.region_of[r["application_id"]]]
        row["requests"] += 1
        row[r["status"].lower()] += 1
        if r["status"] in OPEN_EVC and _days_overdue(sc.deadlines.get(r["deadline_id"]), sc.today) is not None:
            row["overdue"] += 1
        if r["status"] == "PUBLISHED" and r["visit_date"] and date.fromisoformat(r["visit_date"]) >= sc.today:
            row["upcoming_visits"] += 1

    def completion(c: Counter) -> float | None:
        decided = c["requests"] - c["cancelled"]
        return round(c["done"] / decided, 3) if decided else None

    keys = ("requests", "queued", "proposed", "published", "done", "cancelled", "overdue", "upcoming_visits")
    out = [{"region": reg, **{k: c[k] for k in keys}, "completion_rate": completion(c)}
           for reg, c in sorted(rows.items())]
    total = sum(rows.values(), Counter())
    return {"rows": out, "total": {**{k: total[k] for k in keys}, "completion_rate": completion(total)},
            "coverage": _coverage(sc.p, "evc", "deadlines", note=(
                "Proposed: on a schedule not yet published. Published: the visit is fixed. Completion: done out of "
                "requests not cancelled. Overdue: an open request whose EVC clock is breached or past its due date. "
                "Visit slots are simulated."))}


def undertakings(region: str | None) -> dict:
    """Obligations by kind, status and region: overdue, evidence waiting for an officer, and those met late."""
    sc = _scope(region)
    records = sc.p["states"]["compliance"]
    obligations = {k: o for k, o in records.items() if o["kind"] == "obligation" and o["application_id"] in sc.apps}
    awaiting = Counter(e["obligation_id"] for e in records.values()
                       if e["kind"] == "evidence" and e["status"] == "SUBMITTED" and e["obligation_id"] in obligations)
    rows: dict[tuple, Counter] = defaultdict(Counter)
    for key, o in obligations.items():
        d = sc.deadlines.get(o["deadline_id"]) if o["deadline_id"] else None
        row = rows[(sc.region_of[o["application_id"]], o["type"], o["status"])]
        row["obligations"] += 1
        row["overdue"] += int(o["status"] != "MET" and _days_overdue(d, sc.today) is not None)
        row["awaiting_verification"] += awaiting[key]
        row["met_late"] += int(o["status"] == "MET" and d is not None and d["status"] == "MET" and d["late"])
    keys = ("obligations", "overdue", "awaiting_verification", "met_late")
    out = [{"region": r, "kind": k, "status": s, **{x: c[x] for x in keys}} for (r, k, s), c in sorted(rows.items())]
    return {"rows": out, "total": {x: sum(c[x] for c in rows.values()) for x in keys},
            "coverage": _coverage(sc.p, "compliance", "deadlines", note=(
                "Overdue: not met and its clock is breached or past its due date. Met late: met after its clock had "
                "passed its due date. Awaiting verification: evidence submitted that no officer has decided yet."))}


def _owner_roles(ruleset_rev: str) -> dict:
    try:
        alerts = getattr(port(RulesetPort).get(ruleset_rev).deadline_rules, "alerts", None)
    except Exception:  # noqa: BLE001 - a retired or unreadable ruleset leaves the role blank, not the report broken
        return {}
    return {k: str(v) for k, v in alerts.owner_roles.items()} if alerts is not None else {}


def overdue(region: str | None) -> dict:
    """Every open clock that is breached or past its due date, across all rules, with its escalation level."""
    sc = _scope(region)
    late = {k: (d, n) for k, d in sc.deadlines.items() if (n := _days_overdue(d, sc.today)) is not None}
    levels: dict[str, int] = {}
    if late:
        with new_session() as s:
            s.execute(text("SET TRANSACTION READ ONLY"))
            levels = {str(k): v for k, v in s.execute(text(
                "SELECT a.deadline_id, max(a.level) FROM dl.alert a JOIN dl.deadline d ON d.id = a.deadline_id "
                "WHERE a.deadline_id = ANY(CAST(:ids AS uuid[])) AND a.due_version = d.due_version "
                "GROUP BY a.deadline_id"), {"ids": list(late)}).all()}
            s.rollback()
    roles: dict[str, dict] = {}
    rows = []
    for key, (d, days) in late.items():
        app_id = sc.case_of_deadline[key]
        owners = roles.setdefault(d["ruleset_rev"], _owner_roles(d["ruleset_rev"]))
        rows.append({"application_id": app_id, "case_ref": app_id[:8], "region": sc.region_of[app_id],
                     "rule_id": d["rule_id"], "subject_type": d["subject_type"], "clock_owner": d["clock_owner"],
                     "owner_role": owners.get(d["clock_owner"]), "due_date": d["due_date"], "status": d["status"],
                     "days_overdue": days, "escalation_level": levels.get(key)})
    rows.sort(key=lambda r: (-r["days_overdue"], r["region"], r["rule_id"], r["application_id"]))
    return {"rows": rows, "total": {"overdue": len(rows), "breached": sum(r["status"] == "BREACHED" for r in rows)},
            "coverage": _coverage(sc.p, "deadlines", note=(
                "A clock is overdue when it is marked breached, or still running past its due date (the timer has "
                "not reached it yet). Paused clocks are not overdue. Escalation level: the highest alert level "
                "raised for the clock's current due date; blank when no alert has been raised."))}


def _alerts_on_time(region: str | None) -> dict[str, tuple[int, int]]:
    """Per region: (alerts acknowledged before they were escalated, alerts that reached someone)."""
    with new_session() as s:
        s.execute(text("SET TRANSACTION READ ONLY"))
        rows = s.execute(text(
            "SELECT region, count(*) FILTER (WHERE acknowledged_at IS NOT NULL AND "
            "(escalated_at IS NULL OR acknowledged_at <= escalated_at)), count(*) FROM dl.alert "
            "WHERE status <> 'VACANT' AND region IS NOT NULL AND (CAST(:region AS text) IS NULL OR region = :region) "
            "GROUP BY region"), {"region": region}).all()
        s.rollback()
    return {r: (on_time, n) for r, on_time, n in rows}


def region_performance(region: str | None) -> dict:
    """Per region: cases in process, their age and time in the current stage, overdue clocks, alert acknowledgement."""
    sc = _scope(region)
    ages: dict[str, list[int]] = defaultdict(list)
    in_stage: dict[str, list[int]] = defaultdict(list)
    for app_id, a in sc.apps.items():
        if a["status"] != "IN_PROCESS" or not a["submitted_at"]:
            continue
        r = sc.region_of[app_id]
        ages[r].append((sc.today - _ist_date(a["submitted_at"])).days)
        if a["stage_since"]:
            in_stage[r].append((sc.today - _ist_date(a["stage_since"])).days)
    late = Counter(sc.region_of[sc.case_of_deadline[k]] for k, d in sc.deadlines.items()
                   if _days_overdue(d, sc.today) is not None)
    acks = _alerts_on_time(region)

    def stat(values: list[int], f: Callable) -> float | None:
        return round(float(f(values)), 1) if values else None

    def on_time(r: str) -> float | None:
        acked, raised = acks.get(r, (0, 0))
        return round(acked / raised, 3) if raised else None

    rows = [{"region": r, "in_process": len(ages[r]),
             "median_age_days": stat(ages[r], median), "average_age_days": stat(ages[r], mean),
             "median_days_in_stage": stat(in_stage[r], median), "overdue_clocks": late[r],
             "alerts": acks.get(r, (0, 0))[1], "alerts_acknowledged_on_time": on_time(r)}
            for r in sorted(set(ages) | set(late) | set(acks))]
    return {"rows": rows, "total": {"in_process": sum(len(v) for v in ages.values()),
                                    "overdue_clocks": sum(late.values())},
            "coverage": _coverage(sc.p, "applications", "deadlines", note=(
                "Age: days since submission. Time in stage: days since the case entered its current stage "
                "(cases with no recorded stage entry are left out of that median). Acknowledged on time: alerts "
                "acknowledged before the next level was raised, out of alerts that reached someone. Days are "
                "counted in Indian Standard Time."))}


@dataclass(frozen=True)
class Report:
    title: str
    source: str
    columns: tuple[tuple[str, str], ...]   # (row key, column heading): the table and the CSV
    build: Callable[[str | None], dict]
    dated: bool = True                      # ages something, so the IST date is part of the snapshot


REPORTS: dict[str, Report] = {
    "pendency": Report(
        "Pendency by region and stage", "Replayed from workflow events",
        (("region", "Region"), ("stage", "Stage"), ("count", "Applications")), pendency, dated=False),
    "evc_status": Report(
        "EVC status", "Replayed from EVC and deadline events",
        (("region", "Region"), ("requests", "Requests"), ("queued", "Queued"), ("proposed", "Proposed"),
         ("published", "Published"), ("upcoming_visits", "Visits ahead"), ("done", "Done"),
         ("cancelled", "Cancelled"), ("overdue", "Overdue"), ("completion_rate", "Completion")), evc_status),
    "undertakings": Report(
        "Undertakings and obligations", "Replayed from compliance and deadline events",
        (("region", "Region"), ("kind", "Kind"), ("status", "Status"), ("obligations", "Obligations"),
         ("overdue", "Overdue"), ("awaiting_verification", "Evidence awaiting an officer"),
         ("met_late", "Met late")), undertakings),
    "overdue": Report(
        "Overdue clocks", "Replayed from deadline events; escalation levels from the deadline alerts",
        (("case_ref", "Case"), ("region", "Region"), ("rule_id", "Rule"), ("owner_role", "Owner"),
         ("due_date", "Due"), ("days_overdue", "Days overdue"), ("status", "Clock"),
         ("escalation_level", "Escalation level"), ("application_id", "Case id")), overdue),
    "region_performance": Report(
        "Regional performance", "Replayed from workflow and deadline events; acknowledgement from the deadline alerts",
        (("region", "Region"), ("in_process", "In process"), ("median_age_days", "Median age (days)"),
         ("average_age_days", "Average age (days)"), ("median_days_in_stage", "Median days in stage"),
         ("overdue_clocks", "Overdue clocks"), ("alerts", "Alerts"),
         ("alerts_acknowledged_on_time", "Acknowledged on time")), region_performance),
}
REPORT_TYPES = frozenset(REPORTS)


def _columns(spec: Report) -> list[dict]:
    return [{"key": k, "label": label} for k, label in spec.columns]


def report(report_type: str, region: str | None) -> dict | None:
    spec = REPORTS.get(report_type)
    if spec is None:
        return None
    if report_type == "pendency":   # its body (and so its hash) is the one /dashboards/pendency returns
        return {**pendency(region), "title": spec.title, "source": spec.source, "columns": _columns(spec)}
    body = {"type": report_type, "title": spec.title, "source": spec.source, "columns": _columns(spec),
            "scope": {"region": region}, **spec.build(region)}
    if spec.dated:
        body["scope"]["as_of"] = port(ClockPort).now().astimezone(IST).date().isoformat()
    return _sealed(body)


def catalogue() -> list[dict]:
    """The report types a screen can offer, with what each is computed from."""
    return [{"type": k, "title": r.title, "source": r.source, "columns": _columns(r)} for k, r in REPORTS.items()]


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value   # a spreadsheet must never read a cell as a formula
    return str(value)


def to_csv(body: dict) -> str:
    """The report's rows under its column headings, followed by the provenance lines that make it checkable."""
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\r\n")
    w.writerow([c["label"] for c in body["columns"]])
    for row in body["rows"]:
        w.writerow([_cell(row.get(c["key"])) for c in body["columns"]])
    w.writerow([])
    w.writerow(["Report", body["title"]])
    w.writerow(["Source", body["source"]])
    w.writerow(["Region", _cell(body["scope"].get("region")) or "All regions"])
    if body["scope"].get("as_of"):
        w.writerow(["As of (IST)", body["scope"]["as_of"]])
    w.writerow(["Ledger entry", body["ledger_head"]["seq"]])
    w.writerow(["Snapshot hash", body["snapshot_hash"]])
    return out.getvalue()


def ocel_export() -> dict:
    """The event log as OCEL 2.0 JSON: event types, times, roles and the case each event belongs to.

    Payloads, notes and personal references are not exported; the case id is the only object.
    """
    with new_session() as s:
        s.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        head = _ledger_head(s)
        rows = s.execute(text(
            "SELECT id::text, event_type, event_version, at, role, ruleset_rev, aggregate_type, "
            "aggregate_id::text FROM plat.domain_event ORDER BY seq")).all()
        s.rollback()
    event_types = sorted({r.event_type for r in rows})
    object_types = sorted({r.aggregate_type for r in rows})
    objects = sorted({(r.aggregate_id, r.aggregate_type) for r in rows})
    body = {
        "objectTypes": [{"name": t, "attributes": []} for t in object_types],
        "eventTypes": [{"name": t, "attributes": [{"name": "role", "type": "string"},
                                                  {"name": "event_version", "type": "integer"},
                                                  {"name": "ruleset_rev", "type": "string"}]} for t in event_types],
        "objects": [{"id": oid, "type": otype} for oid, otype in objects],
        "events": [{
            "id": r.id, "type": r.event_type, "time": r.at.isoformat(),
            "attributes": [{"name": "role", "value": r.role}, {"name": "event_version", "value": r.event_version},
                           {"name": "ruleset_rev", "value": r.ruleset_rev}],
            "relationships": [{"objectId": r.aggregate_id, "qualifier": r.aggregate_type}],
        } for r in rows],
    }
    return {**body, "ledger_head": head, "snapshot_hash": _snapshot(body, head)}
