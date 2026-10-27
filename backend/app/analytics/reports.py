"""Reproducible reports and event-log exports.

A report states the ledger head it was computed from, and its snapshot hash covers the report body plus that head.
Recomputing at the same ledger state gives the same hash; any new event changes it. Time-dependent figures (ageing)
are left to the dashboard so that the hash depends on the ledger alone.
"""
import hashlib
from collections import Counter, defaultdict

from sqlalchemy import text

from app.analytics.service import _projected, _regions
from app.platform.db import new_session
from app.platform.ledger import canonical

REPORT_TYPES = frozenset({"pendency"})
UNKNOWN_REGION = "Unknown (no case record)"


def _ledger_head(session) -> dict:
    row = session.execute(text(
        "SELECT e.seq, l.entry_hash FROM plat.domain_event e JOIN plat.ledger_entry l ON l.seq = e.seq "
        "ORDER BY e.seq DESC LIMIT 1")).first()
    return {"seq": row[0], "entry_hash": row[1]} if row else {"seq": 0, "entry_hash": None}


def _snapshot(body: dict, head: dict) -> str:
    return hashlib.sha256(canonical({"report": body, "ledger_head": head}).encode()).hexdigest()


def pendency(region: str | None) -> dict:
    """Applications in process, by regional office and current stage (replayed from workflow events)."""
    with new_session() as s:
        head = _ledger_head(s)
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
    return {**body, "ledger_head": head, "snapshot_hash": _snapshot(body, head)}


def report(report_type: str, region: str | None) -> dict | None:
    return pendency(region) if report_type == "pendency" else None


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
