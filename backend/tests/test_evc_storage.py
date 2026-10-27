"""Real PostgreSQL constraints, trigger consistency and EVC master-data bootstrap."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
import os
import subprocess
import sys
from threading import Barrier
from types import SimpleNamespace
from uuid import UUID, NAMESPACE_URL, uuid5

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
import pytest
from sqlalchemy import delete, func, inspect, select, update
from sqlalchemy.exc import IntegrityError

from app.evc.models import Assignment, AssignmentExpert, Availability, Coi, EvcRequest, Expert, ScheduleRun, Slot
from app.platform.db import Base, get_engine, new_session
from generator.cases.scale_generator import EPOCH, LogicalClock, ROOT
from generator.cases.seed_demo import DEMO_INSTITUTIONS
from generator.cases.seed_evc_demo import demo_rows, seed

AT = LogicalClock().now()
DAY = AT.date()
INSTITUTIONS = [row[0] for row in DEMO_INSTITUTIONS]


def ref(token):
    return uuid5(NAMESPACE_URL, "SIH26262:DEMO:EVC:test:" + str(token))


@pytest.fixture
def evc_env(client):
    response = client.post("/api/applications", headers={"X-Demo-User": str(ref("actor")),
        "X-Demo-Role": "INSTITUTION", "X-Demo-Institution": str(INSTITUTIONS[0])},
        json=dict(institution_id=str(INSTITUTIONS[0]), category="NEW_INSTITUTION", academic_year="2027-28"))
    assert response.status_code == 201, response.text
    application = UUID(response.json()["id"])
    other = client.post("/api/applications", headers={"X-Demo-User": str(ref("actor")),
        "X-Demo-Role": "INSTITUTION", "X-Demo-Institution": str(INSTITUTIONS[0])},
        json=dict(institution_id=str(INSTITUTIONS[0]), category="NEW_INSTITUTION", academic_year="2027-28"))
    assert other.status_code == 201
    applications = [application, UUID(other.json()["id"])]
    with new_session() as session, session.begin():
        session.add_all([Expert(id=ref(i), user_ref=ref(f"user-{i}"), region="DEMO_REGION_01", expertise_tags=["DEMO"], active=True)
                         for i in range(3)])
        session.add(ScheduleRun(run_id=ref("run"), algorithm="EDF", parameters={"horizon_days": 60, "options": [1, True, None]},
                                created_at=AT, status="PROPOSED", metrics={"hard_violations": 0}))
        session.add_all([Slot(id=ref("slot-a"), date=DAY, slot_part="AM", capacity=3),
                         Slot(id=ref("slot-b"), date=DAY, slot_part="AM", capacity=3),
                         Slot(id=ref("slot-c"), date=DAY + timedelta(days=1), slot_part="AM", capacity=3),
                         Slot(id=ref("slot-pm"), date=DAY, slot_part="PM", capacity=3)])
        session.add_all([EvcRequest(id=ref(f"request-{i}"), application_id=applications[i], institution_ref=INSTITUTIONS[0],
            region="Southern", category="NEW_INSTITUTION", requested_at=AT, earliest_date=DAY,
            due_by=DAY + timedelta(days=60), status="QUEUED", priority_key=f"DEMO_{i:03d}") for i in range(2)])
    return SimpleNamespace(application=application)


def assignment(token, expert=0, slot="slot-a", published=True, request=0):
    return Assignment(id=ref(token), evc_request_id=ref(f"request-{request}"), slot_id=ref(slot), expert_ids=[ref(expert)],
                      panel_role="DEMO_MEMBER", published=published, schedule_run_id=ref("run"))


def save(*rows):
    with new_session() as session, session.begin():
        session.add_all(rows)


def test_evc_models_match_migration_and_no_seed_rows(database):
    with get_engine().connect() as connection:
        ctx = MigrationContext.configure(connection, opts={"include_schemas": True,
            "include_name": lambda name, kind, parent: name == "evc" if kind == "schema" else True,
            "include_object": lambda obj, name, kind, reflected, other: getattr(obj, "schema", "evc") == "evc" if kind == "table" else True})
        assert compare_metadata(ctx, Base.metadata) == []
        assert set(inspect(connection).get_table_names(schema="evc")) == {
            "evc_request", "expert", "availability", "coi", "slot", "assignment", "schedule_run", "assignment_expert"}
        assert connection.scalar(select(func.count()).select_from(Expert)) == 0
        assert connection.scalar(select(func.count()).select_from(Availability)) == 0
        for table in inspect(connection).get_table_names(schema="evc"):
            assert all(fk["referred_columns"] in (["id"], ["run_id"])
                       for fk in inspect(connection).get_foreign_keys(table, schema="evc"))


@pytest.mark.parametrize("same_slot", [True, False])
def test_published_expert_cannot_be_double_booked_even_across_slots(evc_env, same_slot):
    save(assignment("first"))
    with pytest.raises(IntegrityError, match="uq_evc_published_expert_time"):
        save(assignment("second", slot="slot-a" if same_slot else "slot-b", request=1))
    with new_session() as session:
        assert session.scalar(select(func.count()).select_from(Assignment)) == 1
        assert session.scalar(select(func.count()).select_from(AssignmentExpert)) == 1


def test_proposals_do_not_reserve_until_publication_and_failure_rolls_back(evc_env):
    save(assignment("first"), assignment("proposal", slot="slot-b", published=False))
    with pytest.raises(IntegrityError, match="uq_evc_published_expert_time"):
        with new_session() as session, session.begin():
            session.execute(update(Assignment).where(Assignment.id == ref("proposal")).values(published=True))
    with new_session() as session:
        assert not session.get(Assignment, ref("proposal")).published
        rows = session.scalars(select(AssignmentExpert).order_by(AssignmentExpert.published)).all()
        assert [r.published for r in rows] == [False, True]


def test_different_part_date_or_expert_can_be_published(evc_env):
    save(assignment("a"), assignment("b", slot="slot-pm"), assignment("c", slot="slot-c"), assignment("d", expert=1))
    with new_session() as session:
        assert session.scalar(select(func.count()).select_from(AssignmentExpert)) == 4


@pytest.mark.parametrize("mutation", ["panel", "slot", "slot_date", "slot_part"])
def test_edits_cannot_bypass_no_double_booking(evc_env, mutation):
    save(assignment("first"))
    second = assignment("second", expert=1) if mutation == "panel" else assignment("second", slot="slot-c" if mutation != "slot_part" else "slot-pm")
    save(second)
    with pytest.raises(IntegrityError, match="uq_evc_published_expert_time"):
        with new_session() as session, session.begin():
            if mutation == "panel":
                session.execute(update(Assignment).where(Assignment.id == second.id).values(expert_ids=[ref(0)]))
            elif mutation == "slot":
                session.execute(update(Assignment).where(Assignment.id == second.id).values(slot_id=ref("slot-b")))
            elif mutation == "slot_date":
                session.execute(update(Slot).where(Slot.id == ref("slot-c")).values(date=DAY))
            else:
                session.execute(update(Slot).where(Slot.id == ref("slot-pm")).values(slot_part="AM"))


@pytest.mark.parametrize("operation", ["unpublish", "delete"])
def test_releasing_assignment_frees_expert_time(evc_env, operation):
    save(assignment("first"))
    with new_session() as session, session.begin():
        statement = (update(Assignment).values(published=False) if operation == "unpublish" else delete(Assignment))
        session.execute(statement.where(Assignment.id == ref("first")))
    save(assignment("replacement", slot="slot-b"))
    with new_session() as session:
        assert session.scalar(select(func.count()).select_from(AssignmentExpert).where(AssignmentExpert.published)) == 1


def test_slot_calendar_move_keeps_projection_and_frees_old_time(evc_env):
    save(assignment("first"))
    with new_session() as session, session.begin():
        session.execute(update(Slot).where(Slot.id == ref("slot-a")).values(date=DAY + timedelta(days=2)))
    save(assignment("replacement", slot="slot-b"))
    with new_session() as session:
        row = session.get(AssignmentExpert, (ref("first"), ref(0)))
        assert row.date == DAY + timedelta(days=2)


@pytest.mark.parametrize("bad_panel", [[], [None], [ref(0), ref(0)], [[ref(0)]]])
def test_invalid_panel_arrays_are_rejected(evc_env, bad_panel):
    row = assignment("bad")
    row.expert_ids = bad_panel
    with pytest.raises(IntegrityError, match="EVC_PANEL_IDS_INVALID"):
        save(row)


def test_unknown_experts_are_rejected_even_in_drafts(evc_env):
    with pytest.raises(IntegrityError):
        save(assignment("missing", expert="does-not-exist", published=False))


@pytest.mark.parametrize("mutation", ["insert", "update", "delete"])
def test_membership_projection_rejects_direct_writes(evc_env, mutation):
    save(assignment("first"))
    with pytest.raises(IntegrityError, match="EVC_MEMBERSHIP_TRIGGER_OWNED"):
        with new_session() as session, session.begin():
            if mutation == "insert":
                session.add(AssignmentExpert(assignment_id=ref("first"), expert_id=ref(1), slot_id=ref("slot-a"), date=DAY, slot_part="AM", published=True))
            elif mutation == "update":
                session.execute(update(AssignmentExpert).values(published=False))
            else:
                session.execute(delete(AssignmentExpert))


def test_concurrent_publication_has_exactly_one_winner(evc_env):
    barrier = Barrier(2)
    def publish(index):
        try:
            with new_session() as session, session.begin():
                barrier.wait(timeout=20)
                session.add(assignment(f"concurrent-{index}", request=index, slot="slot-a" if index == 0 else "slot-b"))
            return True
        except IntegrityError as exc:
            assert "uq_evc_published_expert_time" in str(exc)
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(publish, [0, 1])) == [False, True]
    with new_session() as session:
        assert session.scalar(select(func.count()).select_from(Assignment)) == 1


def test_calendar_edit_racing_publication_cannot_leave_stale_booking(evc_env):
    save(assignment("first"))
    barrier = Barrier(2)
    def race(index):
        try:
            with new_session() as session, session.begin():
                barrier.wait(timeout=20)
                if index == 0:
                    session.add(assignment("racing", slot="slot-c", request=1))
                else:
                    session.execute(update(Slot).where(Slot.id == ref("slot-c")).values(date=DAY))
            return True
        except IntegrityError as exc:
            assert "uq_evc_published_expert_time" in str(exc)
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(race, [0, 1])) == [False, True]
    with new_session() as session:
        memberships = session.scalars(select(AssignmentExpert)).all()
        assert len({(r.expert_id, r.date, r.slot_part) for r in memberships}) == len(memberships)
        assert all((r.date, r.slot_part) == (session.get(Slot, r.slot_id).date, session.get(Slot, r.slot_id).slot_part)
                   for r in memberships)


@pytest.mark.parametrize("field,value", [("parameters", {"comment": "free text"}), ("parameters", {"nested": [1, {"note": "text"}]}),
    ("parameters", {"invalid key": 1}), ("parameters", [1, 2]), ("metrics", {"notes": "free text"})])
def test_run_json_rejects_free_text_and_non_object_parameters(evc_env, field, value):
    with pytest.raises(IntegrityError):
        with new_session() as session, session.begin():
            session.execute(update(ScheduleRun).values(**{field: value}))


@pytest.mark.parametrize("kind", ["capacity", "window", "status", "availability", "tags"])
def test_other_storage_constraints(evc_env, kind):
    with pytest.raises(IntegrityError):
        with new_session() as session, session.begin():
            if kind == "capacity":
                session.execute(update(Slot).values(capacity=0))
            elif kind == "window":
                session.execute(update(EvcRequest).values(earliest_date=DAY + timedelta(days=61)))
            elif kind == "status":
                session.execute(update(EvcRequest).values(status="UNKNOWN"))
            elif kind == "tags":
                session.execute(update(Expert).values(expertise_tags=["a person's name"]))
            else:
                session.add_all([Availability(expert_id=ref(0), date=DAY, slot_part="AM", available=True),
                                 Availability(expert_id=ref(0), date=DAY, slot_part="AM", available=False)])


def test_demo_seed_is_deterministic_complete_idempotent_and_cli_loadable(client):
    clock = LogicalClock()
    rows = demo_rows(clock, INSTITUTIONS)
    assert rows == demo_rows(LogicalClock(), INSTITUTIONS)
    assert rows["label"] == "DEMO" and rows["simulation_status"] == "SIMULATED"
    assert len(rows["experts"]) == 30 and len(rows["availability"]) == 3600 and len(rows["coi"]) == 3
    assert len({row["date"] for row in rows["availability"]}) == 60
    assert {row["available"] for row in rows["availability"]} == {True, False}
    assert all("DEMO" in row["expertise_tags"] and row["region"].startswith("DEMO_") for row in rows["experts"])
    for _ in range(2):
        with new_session() as session, session.begin():
            assert seed(session, clock, INSTITUTIONS) == dict(experts=30, availability=3600, coi=3)
    result = subprocess.run([sys.executable, "-m", "generator.cases.seed_evc_demo", "--at", EPOCH],
                            cwd=ROOT, env=os.environ.copy(), text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
    with new_session() as session:
        assert session.scalar(select(func.count()).select_from(Expert)) == 30
        assert session.scalar(select(func.count()).select_from(Availability)) == 3600
        assert session.scalar(select(func.count()).select_from(Coi)) == 3


def test_seed_refuses_conflicting_curated_rows_and_non_demo_mode(client, monkeypatch):
    import app.platform.settings as configuration
    with new_session() as session, session.begin():
        seed(session, LogicalClock(), INSTITUTIONS)
        session.execute(update(Expert).values(active=False))
    with pytest.raises(ValueError, match="conflicting"):
        with new_session() as session, session.begin():
            seed(session, LogicalClock(), INSTITUTIONS)
    monkeypatch.setattr(configuration, "settings", replace(configuration.settings, demo_mode=False))
    with pytest.raises(ValueError, match="demo mode"):
        with new_session() as session, session.begin():
            seed(session, LogicalClock(), INSTITUTIONS)


def test_seed_refuses_unknown_institution_references(client):
    with pytest.raises(ValueError, match="known fictional"):
        with new_session() as session, session.begin():
            seed(session, LogicalClock(), [ref(i) for i in range(3)])


def test_evc_migration_roundtrip_preserves_workflow(client):
    with new_session() as session:
        before = session.execute(select(func.count()).select_from(Base.metadata.tables["wf.institution"])).scalar_one()
    cfg = Config(str(ROOT / "backend/alembic.ini"))
    cfg.attributes["configure_logger"] = False
    try:
        command.downgrade(cfg, "evc@base")
        assert "evc" not in inspect(get_engine()).get_schema_names()
    finally:
        command.upgrade(cfg, "heads")
    with new_session() as session:
        assert session.execute(select(func.count()).select_from(Base.metadata.tables["wf.institution"])).scalar_one() == before
        assert session.scalar(select(func.count()).select_from(Expert)) == 0
