"""Read models rebuilt purely from events. They feed the dashboards and the replay consistency check.

Only what today's events can reconstruct is projected and compared. When new events arrive (stage transitions,
deadline closure, obligations), their owners extend or add projectors - see docs/AUDIT.md.

The `live` readers are read-only SELECTs on the owning module's tables, used only to check that projection and
live state agree. Nothing here writes to another module's schema.
"""
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.platform.replay import EventRecord

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


class DeadlinesProjection:
    name = "deadlines"
    owner = "Person 2 events, projection in analytics"
    handles = frozenset({("dl.deadline_opened", 1)})
    # status (MET, BREACHED, ...) is not compared: no event reports it yet
    compared_fields = ("subject_type", "subject_id", "rule_id", "clock_kind", "clock_owner", "due_date")

    def apply(self, state: dict[str, dict], ev: EventRecord) -> None:
        p = ev.payload
        state[str(p["deadline_id"])] = {k: str(p[k]) for k in ("subject_type", "subject_id", "rule_id", "clock_kind",
                                                               "clock_owner", "due_date", "ruleset_rev")}

    def live(self, session: Session) -> dict[str, dict]:
        rows = session.execute(text(
            "SELECT id::text, subject_type, subject_id::text, rule_id, clock_kind, clock_owner, due_date::text "
            "FROM dl.deadline")).all()
        return {r[0]: dict(zip(self.compared_fields, r[1:])) for r in rows}


ALL = (ApplicationsProjection(), DeadlinesProjection())
