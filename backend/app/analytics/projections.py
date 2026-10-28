"""Read models rebuilt purely from events. They feed the dashboards and the replay consistency check.

Only what the events can reconstruct is projected and compared - see docs/AUDIT.md.

The `live` readers are read-only SELECTs on the owning module's tables, used only to check that projection and
live state agree. Nothing here writes to another module's schema.
"""
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.platform.replay import UNRECORDED, EventRecord

# transition targets that are stages; the others (APPROVED, REJECTED, WITHDRAWN) end the route
STAGES = frozenset({"SELF_DISCLOSURE", "SCRUTINY", "RESCRUTINY", "DEFICIENT", "EVC", "SHC", "EC", "COUNCIL"})


class ApplicationsProjection:
    name = "applications"
    owner = "Person 1 events, projection in analytics"
    # submitted v2 adds dsc_present and provided_item_keys; neither is projected, so both versions apply alike
    handles = frozenset({("wf.application_created", 1), ("wf.application_submitted", 1),
                         ("wf.application_submitted", 2), ("wf.transition_applied", 1)})
    compared_fields = ("institution_id", "category", "academic_year", "status", "current_stage", "ruleset_rev")

    def apply(self, state: dict[str, dict], ev: EventRecord) -> None:
        p = ev.payload
        key = str(p["application_id"])
        if ev.event_type == "wf.application_created":
            state[key] = {"institution_id": str(p["institution_id"]), "category": p["category"],
                          "academic_year": p["academic_year"], "status": "DRAFT", "current_stage": None,
                          "ruleset_rev": None, "created_at": ev.at.isoformat(), "submitted_at": None}
        elif ev.event_type == "wf.application_submitted" and key in state:
            state[key].update(status="IN_PROCESS", current_stage=p["first_stage"], ruleset_rev=p["ruleset_rev"],
                              submitted_at=ev.at.isoformat())
        elif ev.event_type == "wf.transition_applied" and key in state:
            stage = p["to_state"] if p["to_state"] in STAGES else None
            state[key].update(status=p["to_status"], current_stage=stage, ruleset_rev=p["ruleset_rev"])
            if p["action"] == "submit":
                state[key]["submitted_at"] = state[key]["submitted_at"] or ev.at.isoformat()

    def live(self, session: Session) -> dict[str, dict]:
        rows = session.execute(text(
            "SELECT id::text, institution_id::text, category, academic_year, status, current_stage, ruleset_rev "
            "FROM wf.application")).all()
        return {r[0]: dict(zip(("institution_id", "category", "academic_year", "status", "current_stage",
                                "ruleset_rev"), r[1:])) for r in rows}


LIFECYCLE = ("dl.deadline_closed", "dl.deadline_paused", "dl.deadline_resumed", "dl.deadline_breached")


class DeadlinesProjection:
    name = "deadlines"
    owner = "Deadline events, projection in analytics"
    handles = frozenset({("dl.deadline_opened", 1)} | {(t, 1) for t in LIFECYCLE})
    compared_fields = ("subject_type", "subject_id", "rule_id", "clock_kind", "clock_owner", "due_date",
                       "due_version", "status")

    def apply(self, state: dict[str, dict], ev: EventRecord) -> None:
        p = ev.payload
        key = str(p["deadline_id"])
        if ev.event_type == "dl.deadline_opened":
            state[key] = {k: str(p[k]) for k in ("subject_type", "subject_id", "rule_id", "clock_kind",
                                                   "clock_owner", "due_date", "ruleset_rev")}
            state[key].update(due_version=1, status="RUNNING", late=False)
            return
        d = state.get(key)
        if d is None:
            return
        # every lifecycle event carries the clock's due date and version as they are after the change
        d.update(due_date=str(p["due_date"]), due_version=p["due_version"])
        if ev.event_type == "dl.deadline_closed":
            d.update(status=p["outcome"], late=p["late"])
        elif ev.event_type == "dl.deadline_paused":
            d["status"] = "PAUSED"
        elif ev.event_type == "dl.deadline_resumed":
            d["status"] = "RUNNING"
        elif ev.event_type == "dl.deadline_breached":
            d.update(status="BREACHED", late=True)

    def live(self, session: Session) -> dict[str, dict]:
        rows = session.execute(text(
            "SELECT id::text, subject_type, subject_id::text, rule_id, clock_kind, clock_owner, due_date::text, "
            "due_version, status FROM dl.deadline")).all()
        live = {r[0]: dict(zip(self.compared_fields, r[1:])) for r in rows}
        # Clocks closed, paused or resumed before these changes were recorded as events: their status and moved due
        # date are reported as changed without an event rather than as a mismatch.
        recorded = dict(session.execute(text(
            "SELECT aggregate_id::text, count(*) FROM plat.domain_event "
            "WHERE aggregate_type = 'deadline' AND event_type = ANY(:types) GROUP BY aggregate_id"),
            {"types": list(LIFECYCLE)}).all())
        for key, d in live.items():
            if key in recorded:
                continue
            if d["status"] != "RUNNING":
                d["status"] = UNRECORDED
            if d["due_version"] > 1:
                d["due_date"] = d["due_version"] = UNRECORDED
        return live


ALL = (ApplicationsProjection(), DeadlinesProjection())
