"""The demo case seed: every stage reached through the real case API, dated from the demo clock, rerun-safe."""
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import select, text

from app.compliance.models import ApprovalLetter, Obligation
from app.deadlines.models import Deadline
from app.deadlines.wiring import clock
from app.evc.models import EvcRequest
from app.intake.models import Application
from app.platform.db import new_session
from app.workflow import demo_seed
from app.workflow.facts import IST
from app.workflow.models import Appeal
from conftest import headers


@pytest.fixture
def api(client, monkeypatch):
    monkeypatch.setenv("WF_ENABLE_LETTER_ISSUANCE", "true")
    with client:
        yield client
    # Experts and EVC rows are not part of the per-test cleanup set.
    with new_session() as session, session.begin():
        session.execute(text("TRUNCATE evc.assignment_expert, evc.assignment, evc.availability, evc.coi, "
                             "evc.slot, evc.schedule_run_request, evc.schedule_run, evc.evc_request, evc.expert"))


def test_the_seed_reaches_every_stage_dated_from_the_demo_clock(api):
    clock.advance(40)  # the seed follows the demo clock, not the calendar
    today = clock.now().astimezone(IST).date()
    offset = clock.offset

    cases = demo_seed.seed_cases(api)
    assert set(cases) == {c.key for c in demo_seed.DEMO_CASES}
    assert clock.offset == offset  # every back-dated step put the shared clock back

    expected = {"SCRUTINY-OVERDUE": ("IN_PROCESS", "SCRUTINY"), "SCRUTINY-OVERDUE-NORTH": ("IN_PROCESS", "SCRUTINY"),
                "SCRUTINY": ("IN_PROCESS", "SCRUTINY"), "DEFICIENT": ("IN_PROCESS", "DEFICIENT"),
                "EVC-QUEUED-SOUTH": ("IN_PROCESS", "EVC"), "EVC-QUEUED-NORTH": ("IN_PROCESS", "EVC"),
                "EVC-PUBLISHED": ("IN_PROCESS", "EVC"), "SHC": ("IN_PROCESS", "SHC"),
                "LOA-OVERDUE": ("APPROVED", None), "LOA-SOUTH": ("APPROVED", None), "LOA-NORTH": ("APPROVED", None),
                "LOD-APPEAL-OPEN": ("IN_PROCESS", "SCRUTINY"), "APPEAL-AT-SAC": ("IN_PROCESS", "SAC"),
                "RANDOM-INSPECTION": ("IN_PROCESS", "EVC")}
    with new_session() as s:
        for key, app_id in cases.items():
            row = s.get(Application, app_id)
            assert (row.status, row.current_stage) == expected[key], key
        assert row.submitted_at is not None
        evc = {r.application_id: r.status for r in s.scalars(select(EvcRequest))}
        assert evc[cases["EVC-QUEUED-SOUTH"]] == evc[cases["EVC-QUEUED-NORTH"]] == "QUEUED"
        assert evc[cases["RANDOM-INSPECTION"]] == "QUEUED"
        appeals = {a.application_id: a.status for a in s.scalars(select(Appeal))}
        assert appeals == {cases["LOD-APPEAL-OPEN"]: "WINDOW_OPEN", cases["APPEAL-AT-SAC"]: "FILED"}
        assert evc[cases["EVC-PUBLISHED"]] == "PUBLISHED" and evc[cases["SHC"]] == "DONE"

        # LoAs come from issue_loa on the approved cases only, dated on the (moved) demo clock; LoDs from issue_lod
        rows = list(s.scalars(select(ApprovalLetter)))
        letters = {a.application_id: a for a in rows if a.letter_type == "LOA"}
        assert {a.application_id for a in rows if a.letter_type == "LOD"} == {cases["LOD-APPEAL-OPEN"],
                                                                             cases["APPEAL-AT-SAC"]}
        assert set(letters) == {cases["LOA-OVERDUE"], cases["LOA-SOUTH"], cases["LOA-NORTH"]}
        assert letters[cases["LOA-OVERDUE"]].issue_date == today - timedelta(days=20)
        assert letters[cases["LOA-SOUTH"]].issue_date == today - timedelta(days=2)
        assert all(a.f_no.startswith(demo_seed.F_NO_PREFIX) for a in letters.values())
        kinds = sorted((o.kind, o.rule_id) for o in s.scalars(select(Obligation).where(
            Obligation.application_id == cases["LOA-SOUTH"])))
        assert kinds == [("AFFIDAVIT", "DEPOSIT_15D"), ("DEPOSIT", "DEPOSIT_15D"),
                         ("UNDERTAKING", "AFFIDAVIT3_REMAINING_1M")]

        clocks = {(d.subject_id, d.rule_id): d.status for d in s.scalars(select(Deadline))}
        assert clocks[(cases["LOD-APPEAL-OPEN"], "APPEAL_7D")] == "RUNNING"
        assert clocks[(cases["APPEAL-AT-SAC"], "APPEAL_7D")] == "MET"
        assert clocks[(cases["SCRUTINY-OVERDUE"], "AICTE_PROCESSING")] == "BREACHED"
        assert clocks[(cases["SCRUTINY-OVERDUE-NORTH"], "AICTE_PROCESSING")] == "BREACHED"
        assert clocks[(cases["SCRUTINY"], "AICTE_PROCESSING")] == "RUNNING"
        assert clocks[(cases["DEFICIENT"], "INSTITUTION_RESPONSE")] == "RUNNING"
        assert clocks[(cases["DEFICIENT"], "AICTE_PROCESSING")] == "PAUSED"
        overdue = [d.status for d in s.scalars(select(Deadline).join(Obligation, Obligation.deadline_id == Deadline.id)
                                               .where(Obligation.application_id == cases["LOA-OVERDUE"],
                                                      Obligation.rule_id == "DEPOSIT_15D"))]
        assert overdue == ["BREACHED", "BREACHED"]

    # rerunning finds every case and adds nothing
    with new_session() as s:
        before = s.scalar(text("SELECT count(*) FROM wf.application"))
    assert demo_seed.seed_cases(api) == cases
    with new_session() as s:
        assert s.scalar(text("SELECT count(*) FROM wf.application")) == before
    assert api.get("/api/ledger/verify", headers=headers("AUDITOR")).json()["ok"]


def test_the_seed_refuses_outside_demo_mode(monkeypatch):
    from dataclasses import replace

    from app.platform import settings as settings_module

    monkeypatch.setattr(settings_module, "settings", replace(settings_module.settings, demo_mode=False))
    assert demo_seed.main() == 1


def test_case_references_are_stable_fixture_ids():
    refs = {demo_seed.case_ref(c.key) for c in demo_seed.DEMO_CASES}
    assert len(refs) == len(demo_seed.DEMO_CASES) and all(isinstance(r, UUID) and r.version == 5 for r in refs)
