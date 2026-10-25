from uuid import UUID

import pytest
from sqlalchemy import select

from app.platform.db import new_session
from app.workflow import engine
from app.workflow.commands import Command, Payload
from app.workflow.models import CaseState
from app.workflow.storage import visits
from contracts.enums import Role
from contracts.types import Principal
from acceptance.route_support import DECISION_REF, DEMO_REF, EXPECTED, RAW, R1
from acceptance.runtime_support import SUNRISE, headers, letter_for, snapshot, submit_route


def test_expected_csv_is_frozen_complete_and_honest_about_sources():
    assert len(EXPECTED) == 22 and len({row.route_id for row in EXPECTED}) == 22
    assert {row.route_id for row in EXPECTED} == set(RAW["routes"])
    assert sum(row.source_table == "TABLE_2_3" for row in EXPECTED) == 21
    assert [row.route_id for row in EXPECTED if row.source_table == "CHAPTER_I"] == ["NEW_INSTITUTION"]
    assert all(row.source_verification == "PRIMARY_SOURCE_UNAVAILABLE" and
               row.assumption_ref == "ACCEPTANCE_SOURCE_UNVERIFIED" for row in EXPECTED)


@pytest.mark.parametrize("expected", EXPECTED, ids=lambda row: row.route_id)
def test_submit_plan_and_transactional_engine_to_terminal(acceptance_env, expected):
    env = acceptance_env
    # All EVC routes exercise both the selected and skipped optional SHC branch.
    for applicable in ((True, False) if expected.evc else (False,)):
        env.shc = applicable
        application_id, response = submit_route(env, expected.route_id)
        assert response["stages"] == [{"stage": name, "when": when} for name, when in expected.stages]
        assert response["route_id"] == expected.route_id and response["ruleset_key"] == R1
        plan = [name for name, when in expected.stages if when == "always" or applicable]
        observed = [response["current_stage"]]
        actor = Principal(DEMO_REF, Role.BUREAU_OFFICER, institution_id=SUNRISE)
        for target in plan[1:]:
            before = snapshot(application_id)
            result = engine.execute(Command(application_id=UUID(application_id), action="advance",
                                            expected_version=before[4], actor=actor))
            assert result.current_stage == target and result.ruleset_key == R1
            assert result.version == before[4] + 1
            observed.append(result.current_stage)
        letter = letter_for(env)
        before = snapshot(application_id)
        terminal = engine.execute(Command(application_id=UUID(application_id), action="issue_loa",
            expected_version=before[4], payload=Payload(decision_ref=DECISION_REF, letter=letter), actor=actor))
        assert observed == plan
        assert terminal.status == "APPROVED" and terminal.current_stage is None
        assert terminal.version == before[4] + 1 and terminal.letter_ref is not None
        assert env.compliance.letters[-1].application_id == UUID(application_id)
        with new_session() as session:
            state = session.get(CaseState, UUID(application_id))
            assert state.ruleset_key == R1 and state.status == "APPROVED"
            rows = session.execute(select(visits).where(visits.c.application_id == UUID(application_id))).mappings().all()
            assert len(rows) == len(plan) and all(row["exited_at"] is not None for row in rows)
            assert {row["stage"] for row in rows} == set(plan)
        assert env.client.get("/api/ledger/verify", headers=headers("AUDITOR")).json()["ok"]


@pytest.mark.parametrize("expected", EXPECTED, ids=lambda row: row.route_id)
def test_shc_exactly_where_evc_is_yes(expected):
    raw = RAW["routes"][expected.route_id]["stages"]
    stages = [(stage, "always") if isinstance(stage, str) else (stage["stage"], stage["when"]) for stage in raw]
    names = [stage for stage, _ in stages]
    assert ("EVC" in names) == expected.evc == ("SHC" in names)
    if expected.evc:
        assert stages[names.index("EVC")] == ("EVC", "always")
        assert stages[names.index("SHC")] == ("SHC", "as_applicable")
        assert names.index("EVC") < names.index("SHC")
