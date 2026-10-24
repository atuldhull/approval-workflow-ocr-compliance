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


def _events(session: Session) -> Iterable[EventRecord]:
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


def project(events: Iterable[EventRecord], selected: dict[str, Projector]) -> tuple[dict, dict, Counter, Counter]:
    """Pure fold over events. Deterministic: same events in, same state out."""
    states = {n: {} for n in selected}
    applied: Counter = Counter()
    unhandled: Counter = Counter()
    skipped: dict[str, Counter] = {n: Counter() for n in selected}
    known_types = {t for p in selected.values() for t, _ in p.handles}
    for ev in events:
        handled = False
        for name, p in selected.items():
            if (ev.event_type, ev.event_version) in p.handles:
                p.apply(states[name], ev)
                applied[name] += 1
                handled = True
            elif ev.event_type in {t for t, _ in p.handles}:
                skipped[name][f"{ev.event_type}.v{ev.event_version}"] += 1
        if not handled and ev.event_type not in known_types:
            unhandled[ev.event_type] += 1
    return states, applied, unhandled, skipped


def replay(names: list[str] | None = None, events: Iterable[EventRecord] | None = None) -> dict:
    selected = {n: p for n, p in _projectors.items() if names is None or n in names}
    with new_session() as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        try:
            states, applied, unhandled, skipped = project(events if events is not None else _events(session), selected)
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
    return {
        "ok": all(r.status in ("MATCH", "NO_LIVE_MODEL") for r in results),
        "projections": [r.__dict__ for r in results],
        "unhandled_event_types": dict(unhandled),
    }
