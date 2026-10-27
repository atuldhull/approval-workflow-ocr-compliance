"""Replay projector for deadline alerts: rebuilds alert status from dl.alert_* events.

Replay runs read-only and only folds events into a dict, so it can never raise an alert or queue a message.
"""
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.platform.replay import EventRecord


class AlertsProjection:
    name = "alerts"
    owner = "Person 2 (deadlines)"
    handles = frozenset({("dl.alert_raised", 1), ("dl.alert_escalated", 1), ("dl.alert_acknowledged", 1)})
    compared_fields = ("deadline_id", "level", "role", "due_version", "status")

    def apply(self, state: dict[str, dict], ev: EventRecord) -> None:
        p = ev.payload
        if ev.event_type == "dl.alert_raised":
            state[str(p["alert_id"])] = {"deadline_id": str(p["deadline_id"]), "level": p["level"],
                                         "role": p["role"], "due_version": p["due_version"], "status": p["status"]}
        elif ev.event_type == "dl.alert_escalated":
            previous = state.get(str(p["from_alert_id"]))
            if previous is not None and previous["status"] == "OPEN":
                previous["status"] = "ESCALATED"
        elif ev.event_type == "dl.alert_acknowledged":
            alert = state.get(str(p["alert_id"]))
            if alert is not None:
                alert["status"] = "ACKNOWLEDGED"

    def live(self, session: Session) -> dict[str, dict]:
        rows = session.execute(text(
            "SELECT id::text, deadline_id::text, level, role, due_version, status FROM dl.alert")).all()
        return {r[0]: dict(zip(self.compared_fields, r[1:])) for r in rows}
