"""Replay: rebuild read models from the event store and compare them with the live ones.

Each module owner registers projectors for their own events (in their wiring.py). A projector folds events into a
plain dict keyed by record id, and may say how to read the matching live model. Replay runs in a READ ONLY
transaction, so it cannot write, queue notifications or change anything - a projector that tries fails.

The report says honestly what was and was not covered: event types no projector handles, versions a projector does
not understand, and projectors with no live model to compare against.
"""
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.platform.db import new_session
from app.platform.models import DomainEvent
from app.platform.settings import settings

MAX_DIFFS = 100


@dataclass(frozen=True)
class EventRecord:
    seq: int
    at: datetime
    aggregate_type: str
    aggregate_id: UUID
    event_type: str
    event_version: int
    payload: dict[str, Any]
    ruleset_rev: str | None = None


class Projector(Protocol):
    name: str
    owner: str
    handles: frozenset[tuple[str, int]]          # (event_type, version)
    compared_fields: tuple[str, ...]

    def apply(self, state: dict[str, dict], event: EventRecord) -> None: ...
    def live(self, session: Session) -> dict[str, dict] | None: ...   # None: no live model to compare


_projectors: dict[str, Projector] = {}


def register(projector: Projector) -> None:
    _projectors[projector.name] = projector


def projectors() -> dict[str, Projector]:
    return dict(_projectors)


@dataclass
class ProjectionResult:
    name: str
    owner: str
    status: str                       # MATCH | MISMATCH | NO_LIVE_MODEL | INCOMPLETE
    events_applied: int
    records: int
    compared_fields: tuple[str, ...]
    differences: list[dict] = field(default_factory=list)
    skipped_versions: dict[str, int] = field(default_factory=dict)


def stored_events(session: Session) -> Iterable[EventRecord]:
    for e in session.scalars(select(DomainEvent).order_by(DomainEvent.seq)).yield_per(500):
        yield EventRecord(e.seq, e.at, e.aggregate_type, e.aggregate_id, e.event_type, e.event_version,
                          e.payload, e.ruleset_rev)


def diff(replayed: dict[str, dict], live: dict[str, dict], fields: tuple[str, ...]) -> list[dict]:
    out = []
    for key in sorted(set(replayed) | set(live)):
        if key not in live:
            out.append({"key": key, "problem": "missing_in_live"})
        elif key not in replayed:
            out.append({"key": key, "problem": "missing_in_replay"})
        else:
            for f in fields:
                a, b = replayed[key].get(f), live[key].get(f)
                if a != b:
                    out.append({"key": key, "field": f, "replayed": a, "live": b})
        if len(out) >= MAX_DIFFS:
            break
    return out


def project(events: Iterable[EventRecord], selected: dict[str, Projector]) -> tuple[dict, dict, Counter, Counter, list]:
    """Pure fold over events. Deterministic: same events in, same state out.

    An event a projector cannot read (missing or wrongly typed fields - tampering, or a schema the projector
    misreads) is recorded in `unreadable` and skipped, so one bad row cannot take down every report.
    """
    states = {n: {} for n in selected}
    applied: Counter = Counter()
    unhandled: Counter = Counter()
    skipped: dict[str, Counter] = {n: Counter() for n in selected}
    unreadable: list[dict] = []
    known_types = {t for p in selected.values() for t, _ in p.handles}
    for ev in events:
        handled = False
        for name, p in selected.items():
            if (ev.event_type, ev.event_version) in p.handles:
                try:
                    p.apply(states[name], ev)
                except (KeyError, TypeError, ValueError, AttributeError) as e:
                    unreadable.append({"seq": ev.seq, "event_type": ev.event_type, "projection": name,
                                       "error": type(e).__name__})
                    handled = True
                    continue
                applied[name] += 1
                handled = True
            elif ev.event_type in {t for t, _ in p.handles}:
                skipped[name][f"{ev.event_type}.v{ev.event_version}"] += 1
        if not handled and ev.event_type not in known_types:
            unhandled[ev.event_type] += 1
    return states, applied, unhandled, skipped, unreadable


def replay(names: list[str] | None = None, events: Iterable[EventRecord] | None = None) -> dict:
    selected = {n: p for n, p in _projectors.items() if names is None or n in names}
    unknown = sorted(set(names or ()) - set(_projectors))
    with new_session() as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        try:
            states, applied, unhandled, skipped, unreadable = project(events if events is not None else stored_events(session), selected)
            results = []
            for name, p in selected.items():
                live = p.live(session)
                r = ProjectionResult(name, p.owner, "NO_LIVE_MODEL", applied[name], len(states[name]),
                                     p.compared_fields, skipped_versions=dict(skipped[name]))
                if live is not None:
                    r.differences = diff(states[name], live, p.compared_fields)
                    r.status = "MISMATCH" if r.differences else "MATCH"
                if r.skipped_versions:
                    r.status = "INCOMPLETE" if r.status == "MATCH" else r.status
                results.append(r)
        finally:
            session.rollback()
    return summarise(results, unhandled, selected, unknown, unreadable)


def known_schemas() -> set[tuple[str, int]]:
    """(event_type, version) pairs defined in contracts/events - read-only input."""
    found = set()
    for f in (settings.contracts_dir / "events").rglob("*.v*.json"):
        name, _, version = f.name.removesuffix(".json").rpartition(".v")
        found.add((f"{f.parent.name}.{name}", int(version)))
    return found


def summarise(results: list[ProjectionResult], unhandled: Counter, selected: dict[str, Projector],
              unknown: list[str] = (), unreadable: list[dict] = ()) -> dict:
    """Never reports partial coverage as complete.

    verdict: VERIFIED_COMPLETE - every stored event was projected and every projection matched a live model;
             CONSISTENT_SUBSET - nothing disagreed, but some events, versions or projections were not checked;
             MISMATCH          - a projection disagrees with its live model, or a stored event cannot be read.
    """
    gaps = [{"kind": "UNHANDLED_EVENT_TYPE", "event_type": et, "events": n} for et, n in sorted(unhandled.items())]
    # nothing checked is not the same as everything verified
    if not selected:
        gaps.append({"kind": "NO_PROJECTORS"})
    gaps += [{"kind": "UNKNOWN_PROJECTOR", "projection": n} for n in unknown]
    for r in results:
        if not r.compared_fields and r.status != "NO_LIVE_MODEL":
            gaps.append({"kind": "NO_FIELDS_COMPARED", "projection": r.name})
        gaps += [{"kind": "UNKNOWN_EVENT_VERSION", "projection": r.name, "event": ev, "events": n}
                 for ev, n in sorted(r.skipped_versions.items())]
        if r.status == "NO_LIVE_MODEL":
            gaps.append({"kind": "NO_LIVE_MODEL", "projection": r.name})
    handled = {h for p in selected.values() for h in p.handles}
    without_projector = sorted(f"{et}.v{v}" for et, v in known_schemas() - handled)
    gaps += [{"kind": "UNREADABLE_EVENT", **u} for u in unreadable[:MAX_DIFFS]]
    # a stored event a projector cannot read is an integrity-level finding, never a pass
    if unreadable or any(r.status == "MISMATCH" for r in results):
        verdict = "MISMATCH"
    elif gaps:
        verdict = "CONSISTENT_SUBSET"
    else:
        verdict = "VERIFIED_COMPLETE"
    return {
        "ok": verdict == "VERIFIED_COMPLETE",
        "verdict": verdict,
        "projections": [r.__dict__ for r in results],
        "unhandled_event_types": dict(unhandled),
        "gaps": gaps,
        # informational: schemas no projector covers yet; no stored events of these types means nothing is missed today
        "schemas_without_projector": without_projector,
    }
