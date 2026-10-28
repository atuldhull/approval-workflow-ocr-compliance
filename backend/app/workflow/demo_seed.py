"""DEMO ONLY: fictional cases at every workflow stage, driven through the real case API.

    python -m app.workflow.demo_seed      # needs DEMO_MODE=true; safe to rerun

Every case is created, submitted and moved by the same HTTP actions the UI sends (committees, deficiency, EVC
request, schedule proposal and publication, complete_evc, issue_loa, issue_lod, file_appeal), acting as the synthetic demo accounts, so
every row, clock, event and letter comes from the engine. Nothing is written to a table directly.

Cases are dated from the demo clock (ClockPort), never from a calendar date. A case meant to look older is driven
while the shared demo clock is moved back by its age, and the clock is put back straight after, so its submission,
response window or approval letter carry that earlier date and its clocks fall due (or are overdue) accordingly.
The deadline rules themselves are not changed.

Each case is recognised on a rerun by the fictional UUID5 document reference on its core checklist item, so a
case that exists is never created twice. Letters carry "DEMO-SEED" in their file number.
"""
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy import select

IST = ZoneInfo("Asia/Kolkata")
SUNRISE = UUID("00000000-0000-4000-8000-000000000001")
NORTHFIELD = UUID("00000000-0000-4000-8000-000000000002")
RIVERBEND = UUID("00000000-0000-4000-8000-000000000003")
REGION = {SUNRISE: "Southern", NORTHFIELD: "Northern", RIVERBEND: "Western"}
U = lambda n: f"00000000-0000-4000-9000-{n:012d}"  # noqa: E731
INSTITUTION_USER = {SUNRISE: U(1), NORTHFIELD: U(4), RIVERBEND: U(9)}
SCRUTINY = {"X-Demo-User": U(2), "X-Demo-Role": "SCRUTINY_COMMITTEE"}
BUREAU = {"X-Demo-User": U(6), "X-Demo-Role": "BUREAU_OFFICER"}
BUREAU_HEAD = {"X-Demo-User": U(7), "X-Demo-Role": "BUREAU_HEAD"}
F_NO_PREFIX = "F.No. DEMO-SEED/"
PANEL_SIZE = 3            # selector panel_size in routes.yaml
AVAILABILITY_FROM = -30   # experts' seeded availability, in days around the demo date
AVAILABILITY_TO = 45

# Stops, in the order a case passes them.
SCRUTINY_STAGE, DEFICIENT, EVC_QUEUED, EVC_PUBLISHED, SHC, APPROVED = (
    "SCRUTINY", "DEFICIENT", "EVC_QUEUED", "EVC_PUBLISHED", "SHC", "APPROVED")
# The appeal path (on a scrutiny-only route, so scrutiny decides): LoD issued with the appeal window open, and an
# appeal filed and waiting at the SAC. ONLY_EVC is an AICTE-initiated visit, queued on submission.
LOD_WINDOW, APPEAL_AT_SAC, ONLY_EVC = "LOD_WINDOW", "APPEAL_AT_SAC", "ONLY_EVC"


@dataclass(frozen=True)
class DemoCase:
    key: str
    institution_id: UUID
    stop: str
    days_ago: int = 0     # how long ago (demo clock) the case was driven to its stop
    shc: bool = False     # forms an SHC workspace, so SHC applies after the visit
    category: str = "NEW_PROGRAMME"


# Oldest first, so the event log stays in time order. A region's schedule is proposed for every request queued in
# it, so the cases that only wait in the EVC queue come after the ones whose visit is published in that region.
DEMO_CASES = (
    DemoCase("SCRUTINY-OVERDUE", SUNRISE, SCRUTINY_STAGE, days_ago=40),   # processing clock (30 days) overdue
    DemoCase("SCRUTINY-OVERDUE-NORTH", NORTHFIELD, SCRUTINY_STAGE, days_ago=33),
    DemoCase("LOA-OVERDUE", SUNRISE, APPROVED, days_ago=20),              # deposit and affidavit 5 days overdue
    DemoCase("DEFICIENT", NORTHFIELD, DEFICIENT, days_ago=10),            # reply window open, 5 days left
    DemoCase("APPEAL-AT-SAC", NORTHFIELD, APPEAL_AT_SAC, days_ago=5, category="CHANGE_OF_NAME"),
    DemoCase("LOD-APPEAL-OPEN", RIVERBEND, LOD_WINDOW, days_ago=3, category="CHANGE_OF_NAME"),  # 4 days left
    DemoCase("LOA-SOUTH", SUNRISE, APPROVED, days_ago=2),
    DemoCase("LOA-NORTH", NORTHFIELD, APPROVED, days_ago=2),
    DemoCase("EVC-QUEUED-SOUTH", SUNRISE, EVC_QUEUED, days_ago=1),
    DemoCase("EVC-QUEUED-NORTH", NORTHFIELD, EVC_QUEUED, days_ago=1),
    DemoCase("EVC-PUBLISHED", RIVERBEND, EVC_PUBLISHED),
    DemoCase("SHC", RIVERBEND, SHC, shc=True),
    DemoCase("SCRUTINY", NORTHFIELD, SCRUTINY_STAGE),
    DemoCase("RANDOM-INSPECTION", SUNRISE, ONLY_EVC, category="RANDOM_INSPECTION"),  # queued, nothing publishes after
)


def case_ref(key: str) -> UUID:
    """The fictional document reference on a seeded case's core checklist item; it identifies the case."""
    return uuid5(NAMESPACE_URL, f"SIH26262:DEMO:seed-case:{key}")


def f_no(key: str, year: str) -> str:
    return f"{F_NO_PREFIX}{key}/{year}"


def academic_year(day) -> str:
    start = day.year if day.month >= 7 else day.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def existing_cases() -> dict[str, UUID]:
    """Seeded cases already in the database, by key."""
    from app.intake.models import ApplicationItem
    from app.platform.db import new_session

    refs = {case_ref(c.key): c.key for c in DEMO_CASES}
    with new_session() as session:
        rows = session.execute(select(ApplicationItem.document_ref, ApplicationItem.application_id)
                               .where(ApplicationItem.document_ref.in_(list(refs)))).all()
    return {refs[ref]: app_id for ref, app_id in rows}


@contextmanager
def days_back(days: int):
    """Moves the shared demo clock back by `days` for the block, then forward again by the same amount."""
    from app.platform.registry import port
    from contracts.ports import ClockPort

    clock = port(ClockPort)
    if days:
        clock.advance(-days)
    try:
        yield
    finally:
        if days:
            clock.advance(days)


class Driver:
    """Sends the UI's requests as the synthetic demo accounts."""

    def __init__(self, client):
        self.client = client

    def ok(self, response):
        if response.status_code not in (200, 201):
            raise RuntimeError(f"{response.request.method} {response.request.url.path}: "
                               f"{response.status_code} {response.text[:300]}")
        return response.json()

    def get(self, path, headers, **params):
        return self.ok(self.client.get(f"/api{path}", headers=headers, params=params))

    def post(self, path, headers, body):
        return self.ok(self.client.post(f"/api{path}", headers=headers, json=body))

    def version(self, app_id):
        return self.get(f"/cases/{app_id}", BUREAU)["version"]

    def act(self, app_id, action, actor, payload=None, **extra):
        return self.post(f"/cases/{app_id}/actions", actor, {
            "action": action, "expected_version": self.version(app_id), "payload": payload or {}, **extra})

    def committee(self, app_id, kind, actor):
        return self.post(f"/cases/{app_id}/committees", actor,
                         {"type": kind, "members": [{"user_ref": actor["X-Demo-User"], "role": "CHAIR"}]})["id"]

    def today(self):
        from app.platform.registry import port
        from contracts.ports import ClockPort
        return port(ClockPort).now().astimezone(IST).date()


def institution_headers(institution_id: UUID) -> dict:
    return {"X-Demo-User": INSTITUTION_USER[institution_id], "X-Demo-Role": "INSTITUTION",
            "X-Demo-Institution": str(institution_id)}


def ensure_panel(d: Driver, region: str) -> int:
    """Three fictional DEMO experts in the region, available around the demo date. Returns how many were added."""
    listed = {e["user_ref"]: e["id"] for e in d.get("/evc/experts", BUREAU, region=region, limit=100)["items"]}
    added, start = 0, d.today()
    for index in range(PANEL_SIZE):
        user_ref = str(uuid5(NAMESPACE_URL, f"SIH26262:DEMO:seed-panel:{region}:{index}"))
        expert = listed.get(user_ref)
        if expert is None:
            expert = d.post("/evc/experts", BUREAU, {"user_ref": user_ref, "region": region,
                                                     "expertise_tags": ["DEMO"]})["id"]
            added += 1
        items = [{"date": (start + timedelta(days=day)).isoformat(), "slot_part": part, "available": True}
                 for day in range(AVAILABILITY_FROM, AVAILABILITY_TO) for part in ("AM", "PM")]
        d.post(f"/evc/experts/{expert}/availability", BUREAU, {"items": items})
    return added


def publish_region(d: Driver, region: str, key: str) -> None:
    """Proposes a schedule for the region's queued visit requests and publishes it (bureau head)."""
    start = d.today()
    run = d.post("/evc/schedule:propose", BUREAU, {
        "run_id": str(uuid5(NAMESPACE_URL, f"SIH26262:DEMO:seed-run:{key}:{start.isoformat()}")),
        "algorithm": "EDF", "horizon_start": start.isoformat(), "horizon_end": (start + timedelta(days=7)).isoformat(),
        "region": region, "slot_capacity": 4})
    if not run["proposals"]:
        raise RuntimeError(f"no visit could be planned in {region}")
    d.post("/evc/schedule:publish", BUREAU_HEAD, {"run_id": run["run_id"]})


def submit(d: Driver, case: DemoCase) -> str:
    year = academic_year(d.today() + timedelta(days=365))  # applications are for the coming academic year
    return d.post("/applications", institution_headers(case.institution_id), {
        "institution_id": str(case.institution_id), "category": case.category, "academic_year": year,
        "submit": True, "dsc_present": True,
        "items": [{"item_key": "DEMO_CORE_REFERENCE", "state": "PROVIDED", "document_ref": str(case_ref(case.key))}]})["id"]


def drive(d: Driver, case: DemoCase) -> str:
    """Creates one case and moves it to its stop. Returns its id."""
    app_id = submit(d, case)
    if case.stop == ONLY_EVC:  # submission queues the visit request
        return app_id
    scrutiny = d.committee(app_id, "SCRUTINY", SCRUTINY)
    if case.stop == SCRUTINY_STAGE:
        return app_id
    if case.stop in (LOD_WINDOW, APPEAL_AT_SAC):
        report = d.post(f"/committees/{scrutiny}/reports", SCRUTINY,
                        {"content": "Fictional DEMO scrutiny report: the core requirement is not met."})["id"]
        year = academic_year(d.today() + timedelta(days=365))
        d.act(app_id, "issue_lod", BUREAU, {"decision_ref": report, "letter": {
            "type": "LOD", "academic_year": year, "issue_date": d.today().isoformat(),
            "issue_date_source": "PORTAL_EVENT", "lists_deficiencies": False, "f_no": f_no(case.key, year)}})
        if case.stop == APPEAL_AT_SAC:
            d.act(app_id, "file_appeal", institution_headers(case.institution_id),
                  note="Fictional DEMO grounds: the requirement was met before the LoD.")
        return app_id
    if case.stop == DEFICIENT:
        d.act(app_id, "record_deficiency", SCRUTINY, {"item_keys": ["DEMO_CORE_REFERENCE"]},
              reason_code="DEMO_MISSING_EVIDENCE")
        return app_id
    d.act(app_id, "advance_to_evc", SCRUTINY)  # queues the visit request and opens its clock
    if case.stop == EVC_QUEUED:
        return app_id
    evc = d.committee(app_id, "EVC", BUREAU)
    shc = d.committee(app_id, "SHC", BUREAU) if case.shc else None
    publish_region(d, REGION[case.institution_id], case.key)
    if case.stop == EVC_PUBLISHED:
        return app_id
    d.act(app_id, "complete_evc", BUREAU)
    if case.stop == SHC:
        return app_id
    deciding = shc or evc
    report = d.post(f"/committees/{deciding}/reports", BUREAU,
                    {"content": "Fictional DEMO committee report: requirements met."})["id"]
    year = d.get(f"/cases/{app_id}", BUREAU).get("academic_year") or academic_year(d.today() + timedelta(days=365))
    d.act(app_id, "issue_loa", BUREAU, {"decision_ref": report, "letter": {
        "type": "LOA", "academic_year": year, "issue_date": d.today().isoformat(),
        "issue_date_source": "PORTAL_EVENT", "lists_deficiencies": False, "f_no": f_no(case.key, year)}})
    return app_id


def seed_cases(client) -> dict[str, UUID]:
    """Creates the demo cases that do not exist yet. Returns the ids of every seeded case, by key."""
    d = Driver(client)
    known = existing_cases()
    panels = set()
    for case in DEMO_CASES:
        if case.key in known:
            continue
        region = REGION[case.institution_id]
        if case.stop in (EVC_PUBLISHED, SHC, APPROVED) and region not in panels:
            ensure_panel(d, region)
            panels.add(region)
        with days_back(case.days_ago):
            known[case.key] = UUID(drive(d, case))
    # mark clocks that are already past their due time breached, and raise their alerts
    d.post("/sim/timers/run", BUREAU_HEAD, {})
    return known


def main() -> int:
    import os

    from app.platform.settings import settings

    if not settings.demo_mode:
        print("refusing: DEMO_MODE is not enabled")
        return 1
    # the demo stack issues letters from the case screen; the seeded approvals need the same switch
    os.environ.setdefault("WF_ENABLE_LETTER_ISSUANCE", "true")
    before = existing_cases()
    from app.platform.demo_seed import demo_client

    with demo_client() as client:
        cases = seed_cases(client)
    print(f"seeded {len(cases) - len(before)} DEMO case(s); {len(before)} already existed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
