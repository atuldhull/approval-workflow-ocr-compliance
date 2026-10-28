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
    owner = "Workflow events, projection in analytics"
    # submitted v2 adds dsc_present and provided_item_keys; neither is projected, so both versions apply alike.
    # The stage a case is in follows wf.transition_applied; stage_entered/exited add when it entered that stage.
    handles = frozenset({("wf.application_created", 1), ("wf.application_submitted", 1),
                         ("wf.application_submitted", 2), ("wf.transition_applied", 1),
                         ("wf.stage_entered", 1), ("wf.stage_exited", 1)})
    compared_fields = ("institution_id", "category", "academic_year", "status", "current_stage", "ruleset_rev")

    def apply(self, state: dict[str, dict], ev: EventRecord) -> None:
        p = ev.payload
        key = str(p["application_id"])
        if ev.event_type == "wf.application_created":
            state[key] = {"institution_id": str(p["institution_id"]), "category": p["category"],
                          "academic_year": p["academic_year"], "status": "DRAFT", "current_stage": None,
                          "ruleset_rev": None, "created_at": ev.at.isoformat(), "submitted_at": None,
                          "stage_visit": None, "stage_since": None}
        elif ev.event_type == "wf.application_submitted" and key in state:
            state[key].update(status="IN_PROCESS", current_stage=p["first_stage"], ruleset_rev=p["ruleset_rev"],
                              submitted_at=ev.at.isoformat())
        elif ev.event_type == "wf.transition_applied" and key in state:
            stage = p["to_state"] if p["to_state"] in STAGES else None
            state[key].update(status=p["to_status"], current_stage=stage, ruleset_rev=p["ruleset_rev"])
            if p["action"] == "submit":
                state[key]["submitted_at"] = state[key]["submitted_at"] or ev.at.isoformat()
        elif ev.event_type == "wf.stage_entered" and key in state:
            state[key].update(stage_visit=str(p["stage_visit_id"]), stage_since=p["entered_at"])
        elif ev.event_type == "wf.stage_exited" and key in state:
            if state[key]["stage_visit"] == str(p["stage_visit_id"]):
                state[key].update(stage_visit=None, stage_since=None)

    def live(self, session: Session) -> dict[str, dict]:
        rows = session.execute(text(
            "SELECT id::text, institution_id::text, category, academic_year, status, current_stage, ruleset_rev "
            "FROM wf.application")).all()
        return {r[0]: dict(zip(("institution_id", "category", "academic_year", "status", "current_stage",
                                "ruleset_rev"), r[1:])) for r in rows}


class DeficienciesProjection:
    name = "deficiencies"
    owner = "Workflow events, projection in analytics"
    handles = frozenset({("wf.deficiency_recorded", 1), ("wf.deficiency_item_responded", 1),
                         ("wf.compliance_submitted", 1), ("wf.deficiency_item_decided", 1),
                         ("wf.deficiency_closed", 1), ("wf.deficiency_superseded", 1)})
    compared_fields = ("application_id", "round_no", "status", "items")

    def apply(self, state: dict[str, dict], ev: EventRecord) -> None:
        p = ev.payload
        key = str(p["deficiency_id"])
        if ev.event_type == "wf.deficiency_recorded":
            state[key] = {"application_id": str(p["application_id"]), "round_no": p["round_no"], "status": "OPEN",
                          "items": {str(i["item_id"]): "OPEN" for i in p["items"]}}
            return
        d = state.get(key)
        if d is None:
            return
        if ev.event_type == "wf.deficiency_item_responded":
            d["items"][str(p["item_id"])] = "RESPONDED"
        elif ev.event_type == "wf.compliance_submitted":
            d["status"] = "RESPONDED"
        elif ev.event_type == "wf.deficiency_item_decided":
            d["items"][str(p["item_id"])] = p["state"]
        else:   # closed (accepted) or superseded by the next round
            d["status"] = "CLOSED"

    def live(self, session: Session) -> dict[str, dict]:
        live = {r[0]: {"application_id": r[1], "round_no": r[2], "status": r[3], "items": {}}
                for r in session.execute(text(
                    "SELECT id::text, application_id::text, round_no, status FROM wf.deficiency")).all()}
        for deficiency_id, item_id, item_state in session.execute(text(
                "SELECT deficiency_id::text, id::text, state FROM wf.deficiency_item")).all():
            if deficiency_id in live:
                live[deficiency_id]["items"][item_id] = item_state
        return live


class CommitteesProjection:
    """Committees and their tasks, keyed by committee id or task id (`kind` says which)."""
    name = "committees"
    owner = "Workflow events, projection in analytics"
    handles = frozenset({("wf.committee_formed", 1), ("wf.task_assigned", 1), ("wf.observation_added", 1),
                         ("wf.report_version_added", 1)})
    compared_fields = ("kind", "application_id", "committee_id", "type", "members", "assignee", "title_key",
                       "observations", "reports")

    def apply(self, state: dict[str, dict], ev: EventRecord) -> None:
        p = ev.payload
        if ev.event_type == "wf.committee_formed":
            state[str(p["committee_id"])] = {
                "kind": "committee", "application_id": str(p["application_id"]), "type": p["type"],
                "members": sorted(str(m["user_ref"]) for m in p["members"]), "reports": 0}
        elif ev.event_type == "wf.task_assigned":
            state[str(p["task_id"])] = {
                "kind": "task", "application_id": str(p["application_id"]), "committee_id": str(p["committee_id"]),
                "assignee": str(p["assignee_user_ref"]), "title_key": p["title_key"], "observations": 0}
        elif ev.event_type == "wf.observation_added" and str(p["task_id"]) in state:
            state[str(p["task_id"])]["observations"] += 1
        elif ev.event_type == "wf.report_version_added" and str(p["committee_id"]) in state:
            state[str(p["committee_id"])]["reports"] += 1

    def live(self, session: Session) -> dict[str, dict]:
        live = {r[0]: {"kind": "committee", "application_id": r[1], "type": r[2], "members": [], "reports": r[3]}
                for r in session.execute(text(
                    "SELECT c.id::text, c.application_id::text, c.type, "
                    "(SELECT count(*) FROM wf.report_version v WHERE v.committee_id = c.id) FROM wf.committee c")).all()}
        for committee_id, user_ref in session.execute(text(
                "SELECT committee_id::text, user_ref::text FROM wf.committee_member")).all():
            if committee_id in live:
                live[committee_id]["members"].append(user_ref)
        for c in live.values():
            c["members"].sort()
        for r in session.execute(text(
                "SELECT t.id::text, c.application_id::text, t.committee_id::text, t.assignee_user_ref::text, "
                "t.title_key, (SELECT count(*) FROM wf.observation o WHERE o.task_id = t.id) "
                "FROM wf.task t JOIN wf.committee c ON c.id = t.committee_id")).all():
            live[r[0]] = {"kind": "task", "application_id": r[1], "committee_id": r[2], "assignee": r[3],
                          "title_key": r[4], "observations": r[5]}
        return live


class EvcProjection:
    """EVC requests and where each stands in the queue: QUEUED, PROPOSED, PUBLISHED, DONE or CANCELLED."""
    name = "evc"
    owner = "EVC events, projection in analytics"
    handles = frozenset({("evc.request_created", 1), ("evc.assignment_proposed", 1), ("evc.assignment_published", 1),
                         ("evc.schedule_discarded", 1), ("evc.request_completed", 1), ("evc.request_cancelled", 1)})
    compared_fields = ("application_id", "status", "due_by", "deadline_id")

    def apply(self, state: dict[str, dict], ev: EventRecord) -> None:
        p = ev.payload
        if ev.event_type == "evc.schedule_discarded":
            for w in p["withdrawn"]:
                if str(w["request_id"]) in state:
                    state[str(w["request_id"])].update(status="QUEUED", visit_date=None, run_id=None)
            return
        key = str(p["request_id"])
        if ev.event_type == "evc.request_created":
            state[key] = {"application_id": str(p["application_id"]), "status": "QUEUED", "due_by": p["due_by"],
                          "deadline_id": str(p["deadline_ref"]), "visit_date": None, "run_id": None}
            return
        r = state.get(key)
        if r is None:
            return
        if ev.event_type in ("evc.assignment_proposed", "evc.assignment_published"):
            r.update(status=p["request_status"], visit_date=p["date"], run_id=str(p["run_id"]))
        elif ev.event_type == "evc.request_completed":
            r["status"] = "DONE"
        else:
            r["status"] = "CANCELLED"

    def live(self, session: Session) -> dict[str, dict]:
        rows = session.execute(text(
            "SELECT id::text, application_id::text, status, due_by::text, deadline_ref::text "
            "FROM evc.evc_request")).all()
        return {r[0]: dict(zip(self.compared_fields, r[1:])) for r in rows}


class ComplianceProjection:
    """Letters, obligations and evidence, keyed by their ids (`kind` says which)."""
    name = "compliance"
    owner = "Compliance events, projection in analytics"
    handles = frozenset({("cmp.letter_registered", 1), ("cmp.obligation_created", 1),
                         ("cmp.evidence_submitted", 1), ("cmp.evidence_verified", 1)})
    compared_fields = ("kind", "application_id", "type", "status", "obligation_id", "deadline_id", "due_date")

    def apply(self, state: dict[str, dict], ev: EventRecord) -> None:
        p = ev.payload
        if ev.event_type == "cmp.letter_registered":
            state[str(p["letter_id"])] = {"kind": "letter", "application_id": str(p["application_id"]),
                                          "type": p["letter_type"]}
        elif ev.event_type == "cmp.obligation_created":
            state[str(p["obligation_id"])] = {
                "kind": "obligation", "application_id": str(p["application_id"]), "type": p["kind"],
                "status": "OPEN", "deadline_id": str(p["deadline_id"]) if p["deadline_id"] else None,
                "due_date": p["due_date"]}
        elif ev.event_type == "cmp.evidence_submitted":
            state[str(p["evidence_id"])] = {"kind": "evidence", "application_id": str(p["application_id"]),
                                            "obligation_id": str(p["obligation_id"]), "status": "SUBMITTED"}
            if str(p["obligation_id"]) in state:
                state[str(p["obligation_id"])]["status"] = "EVIDENCE_SUBMITTED"
        elif ev.event_type == "cmp.evidence_verified":
            if str(p["evidence_id"]) in state:
                state[str(p["evidence_id"])]["status"] = p["decision"]
            if str(p["obligation_id"]) in state:
                state[str(p["obligation_id"])]["status"] = p["obligation_status"]

    def live(self, session: Session) -> dict[str, dict]:
        live = {r[0]: {"kind": "letter", "application_id": r[1], "type": r[2]} for r in session.execute(text(
            "SELECT id::text, application_id::text, letter_type FROM cmp.approval_letter")).all()}
        for r in session.execute(text(
                "SELECT id::text, application_id::text, kind, status, deadline_id::text, due_date::text "
                "FROM cmp.obligation")).all():
            live[r[0]] = {"kind": "obligation", "application_id": r[1], "type": r[2], "status": r[3],
                          "deadline_id": r[4], "due_date": r[5]}
        for r in session.execute(text(
                "SELECT id::text, application_id::text, obligation_id::text, status FROM cmp.evidence")).all():
            live[r[0]] = {"kind": "evidence", "application_id": r[1], "obligation_id": r[2], "status": r[3]}
        return live


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


# Stored events no projection folds, on purpose; replay lists them with the reason instead of as a gap.
NOT_PROJECTED = {
    "wf.application_item_updated": "Checklist entries are read from the application itself; each change is on the "
                                   "case timeline.",
    "evc.expert_registered": "The expert pool is read from the EVC module; dashboards count requests, not experts.",
    "evc.availability_set": "Expert availability is an input to scheduling, read from the EVC module.",
    "evc.coi_recorded": "Conflicts of interest are an input to scheduling, read from the EVC module.",
    "evc.schedule_proposed": "A proposed run is followed through its evc.assignment_proposed events.",
    "doc.document_uploaded": "Document versions are kept by the documents module with their own content hashes.",
    "doc.document_scanned": "Scan results are kept on the document version by the documents module.",
    "doc.fact_reviewed": "OCR reviews are kept by the documents module with their two-person check.",
    "doc.fact_confirmed": "Confirmed facts are kept by the documents module with their two-person check.",
}

ALL = (ApplicationsProjection(), DeadlinesProjection(), DeficienciesProjection(), CommitteesProjection(),
       EvcProjection(), ComplianceProjection())
