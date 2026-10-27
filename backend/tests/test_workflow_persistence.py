"""Real PostgreSQL persistence, checksum loading, startup and migration safety."""
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import shutil
from uuid import NAMESPACE_URL, uuid5

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import MetaData, func, inspect, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
import pytest

from app.intake.models import StageVisit
from app.main import load_models
from app.platform.db import Base, get_engine, new_session
from app.platform.registry import provide
from app.workflow.loader import sync_rulesets
from app.workflow.models import CaseState, RouteDefinition, Ruleset, TransitionDefinition
from app.workflow.registry import RulesetRegistry
from conftest import SUNRISE, headers
from backend.tests.intake_test_helpers import ensure_intake_rules, provide_fixture_items
from contracts.errors import Conflict, ValidationFailed
from contracts.fakes import FakeClock
from contracts.ports import ClockPort

ROOT = Path(__file__).resolve().parents[2]
R1 = "aph-2024-27@r1"
R3 = "aph-2024-27@r3-DEMO"
AT = datetime(2026, 7, 1, 4, 30, tzinfo=timezone.utc)


def registry(root=None, *, demo=True, default=R1):
    return RulesetRegistry(root or ROOT / "rulesets", default, demo_mode=demo)


def sync(reg):
    with new_session() as session, session.begin():
        return sync_rulesets(session, reg)


def copy_sources(tmp_path):
    target = tmp_path / "rulesets"
    shutil.copytree(ROOT / "rulesets", target)
    return target


def add_revision(root):
    folder = root / "aph-2024-27/r2"
    shutil.copytree(root / "aph-2024-27/r1", folder)
    path = folder / "routes.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace("revision: r1", "revision: r2", 1), encoding="utf-8")
    return "aph-2024-27@r2"


def submitted(client):
    ensure_intake_rules(client)
    auth = headers("INSTITUTION", SUNRISE)
    response = client.post("/api/applications", headers=auth, json={
        "institution_id": str(SUNRISE), "category": "NEW_PROGRAMME", "academic_year": "2027-28",
    })
    assert response.status_code == 201
    app_id = response.json()["id"]
    provide_fixture_items(app_id)
    response = client.post(f"/api/applications/{app_id}/submit", headers=auth, json={"dsc_present": True})
    assert response.status_code == 200
    return response.json()


def pin(client):
    from uuid import UUID

    app = submitted(client)
    application_id = UUID(app["id"])
    with new_session() as session, session.begin():
        session.add(CaseState(application_id=application_id, route_id=app["category"],
                              ruleset_key=app["ruleset_rev"], current_stage=app["current_stage"], status=app["status"]))
    return application_id


def test_loader_idempotent_without_reading_clock_or_changing_metadata(client):
    provide(ClockPort, FakeClock(AT))
    first = sync(registry())
    assert first.inserted == (R1, R3)
    with new_session() as session:
        rows = session.scalars(select(Ruleset).order_by(Ruleset.key)).all()
        before = [(r.id, r.checksum, r.created_at, r.created_by_ref, r.status) for r in rows]
        assert all(r.status == "DRAFT" and r.approved_at is None and r.approved_by_ref is None for r in rows)
        assert all(r.created_at == AT for r in rows)
        assert [r.demo_only for r in rows] == [False, True]
        assert [len(r.source_files) for r in rows] == [3, 4]
        assert session.scalar(select(func.count()).select_from(RouteDefinition)) == 44
        transitions = session.scalar(select(func.count()).select_from(TransitionDefinition))
        assert transitions > 0

    class NoClockRead:
        def now(self):
            raise AssertionError("no-op import must not read time")

    provide(ClockPort, NoClockRead())
    second = sync(registry())
    assert second.unchanged == (R1, R3) and second.inserted == ()
    with new_session() as session:
        rows = session.scalars(select(Ruleset).order_by(Ruleset.key)).all()
        assert [(r.id, r.checksum, r.created_at, r.created_by_ref, r.status) for r in rows] == before
        assert session.scalar(select(func.count()).select_from(TransitionDefinition)) == transitions


def test_loading_new_revision_and_overlay_does_not_repin_case(client, tmp_path):
    root = copy_sources(tmp_path)
    sync(registry(root, demo=False))
    application_id = pin(client)
    new_key = add_revision(root)
    result = sync(registry(root, default=new_key))
    assert result.inserted == (new_key, R3)
    with new_session() as session:
        row = session.get(CaseState, application_id)
        assert (row.ruleset_key, row.route_id, row.current_stage, row.status, row.version) == (R1, "NEW_PROGRAMME", "SCRUTINY", "IN_PROCESS", 1)
        assert session.scalar(select(func.count()).select_from(Ruleset)) == 3


def test_changed_checksum_is_rejected_and_old_definition_preserved(client, tmp_path):
    root = copy_sources(tmp_path)
    sync(registry(root))
    with new_session() as session:
        before = session.scalar(select(Ruleset.checksum).where(Ruleset.key == R1))
    path = root / "aph-2024-27/r1/routes.yaml"
    path.write_text(path.read_text(encoding="utf-8") + "\n# changed source\n", encoding="utf-8")
    with pytest.raises(Conflict, match="different source checksum"):
        sync(registry(root))
    with new_session() as session:
        assert session.scalar(select(Ruleset.checksum).where(Ruleset.key == R1)) == before
        assert session.scalar(select(func.count()).select_from(RouteDefinition)) == 44


def test_loader_transaction_rolls_back_all_definitions(client):
    with new_session() as session:
        with pytest.raises(RuntimeError, match="rollback"):
            with session.begin():
                sync_rulesets(session, registry())
                raise RuntimeError("rollback")
    with new_session() as session:
        for model in (Ruleset, RouteDefinition, TransitionDefinition):
            assert session.scalar(select(func.count()).select_from(model)) == 0


def test_non_demo_startup_skips_overlay_without_approving_base(client):
    result = sync(registry(demo=False))
    assert result.inserted == (R1,) and result.skipped_demo == (R3,)
    with new_session() as session:
        assert session.scalar(select(Ruleset.status).where(Ruleset.key == R1)) == "DRAFT"


def test_sync_preserves_lifecycle_metadata(client):
    sync(registry())
    actor = uuid5(NAMESPACE_URL, "sih26262:test:approver")
    with new_session() as session, session.begin():
        row = session.scalar(select(Ruleset).where(Ruleset.key == R1))
        row.status, row.approved_by_ref, row.approved_at = "APPROVED", actor, AT
    sync(registry())
    with new_session() as session:
        row = session.scalar(select(Ruleset).where(Ruleset.key == R1))
        assert (row.status, row.approved_by_ref, row.approved_at) == ("APPROVED", actor, AT)


@pytest.mark.parametrize("values", [{"status": "UNREVIEWED"}, {"checksum": "bad"}, {"approved_at": AT}])
def test_database_rejects_invalid_ruleset_metadata(client, values):
    sync(registry())
    with pytest.raises(IntegrityError):
        with get_engine().begin() as connection:
            connection.execute(update(Ruleset).where(Ruleset.key == R1).values(**values))


@pytest.mark.parametrize("default,match", [(R3, "demo-only"), ("aph-2024-27@missing", "default ruleset source is missing")])
def test_invalid_default_rolls_back_import(client, default, match):
    with pytest.raises(ValidationFailed, match=match):
        sync(registry(demo=False, default=default))
    with new_session() as session:
        assert session.scalar(select(func.count()).select_from(Ruleset)) == 0


def test_startup_hook_materializes_rulesets_without_api_change(client):
    with client:
        with new_session() as session:
            assert session.scalar(select(func.count()).select_from(Ruleset)) == 2
        assert client.get("/api/health").status_code == 200
    with client:
        with new_session() as session:
            assert session.scalar(select(func.count()).select_from(RouteDefinition)) == 44


def test_case_optimistic_lock_rejects_stale_writer(client):
    sync(registry())
    application_id = pin(client)
    with new_session() as first, new_session() as second:
        a, b = first.get(CaseState, application_id), second.get(CaseState, application_id)
        a.current_stage = "DEFICIENT"
        first.commit()
        assert a.version == 2
        b.current_stage = "RESCRUTINY"
        with pytest.raises(StaleDataError):
            second.commit()
        second.rollback()
    with new_session() as session:
        row = session.get(CaseState, application_id)
        assert (row.current_stage, row.version, row.ruleset_key) == ("DEFICIENT", 2, R1)


@pytest.mark.parametrize("values", [{"ruleset_key": R3}, {"route_id": "MERGER"}])
def test_database_rejects_direct_pin_rewrite(client, values):
    sync(registry())
    application_id = pin(client)
    with pytest.raises(IntegrityError, match="case pin is immutable"):
        with get_engine().begin() as connection:
            connection.execute(update(CaseState).where(CaseState.application_id == application_id).values(**values))


def test_case_requires_existing_route_and_unique_application(client):
    sync(registry())
    application_id = pin(client)
    with pytest.raises(IntegrityError):
        with new_session() as session, session.begin():
            session.add(CaseState(application_id=application_id, route_id="NEW_PROGRAMME", ruleset_key=R1,
                                  current_stage="SCRUTINY", status="IN_PROCESS"))
    app = submitted(client)
    from uuid import UUID
    with pytest.raises(IntegrityError):
        with new_session() as session, session.begin():
            session.add(CaseState(application_id=UUID(app["id"]), route_id="UNKNOWN", ruleset_key=R1,
                                  current_stage="SCRUTINY", status="IN_PROCESS"))


def test_database_rejects_zero_case_version(client):
    sync(registry())
    application_id = pin(client)
    with pytest.raises(IntegrityError):
        with get_engine().begin() as connection:
            connection.execute(update(CaseState).where(CaseState.application_id == application_id).values(version=0))


def test_stage_exit_uses_clock_and_legacy_alias(client):
    provide(ClockPort, FakeClock(AT))
    app = submitted(client)
    from uuid import UUID
    with new_session() as session, session.begin():
        row = session.scalar(select(StageVisit).where(StageVisit.application_id == UUID(app["id"])))
        assert row.entered_at == AT and row.exited_at is None
        later = datetime(2026, 7, 2, 4, 30, tzinfo=timezone.utc)
        provide(ClockPort, FakeClock(later))
        note = uuid5(NAMESPACE_URL, "sih26262:test:note")
        row.record_exit(outcome="COMPLETED", reason_code="DEMO_COMPLETE", note_ref=note)
        assert row.exited_at == row.left_at == later
        assert (row.outcome, row.reason_code, row.note_ref) == ("COMPLETED", "DEMO_COMPLETE", note)
        with pytest.raises(Conflict, match="already exited"):
            row.record_exit(outcome="COMPLETED")


def test_workflow_models_match_migrations(database):
    load_models()
    metadata = MetaData()
    for table in Base.metadata.sorted_tables:
        if table.schema == "wf":
            table.to_metadata(metadata)
    with get_engine().connect() as connection:
        ctx = MigrationContext.configure(connection, opts={
            "include_schemas": True,
            "include_name": lambda name, kind, parents: name == "wf" if kind == "schema" else True,
        })
        assert compare_metadata(ctx, metadata) == []
        inspector = inspect(connection)
        assert inspector.get_pk_constraint("case_state", schema="wf")["constrained_columns"] == ["application_id"]
        assert any(i["column_names"] == ["ruleset_key", "route_id"] for i in inspector.get_indexes("case_state", schema="wf"))
        assert len(metadata.tables) == 15
        for table in metadata.tables.values():
            assert all(fk.column.table.schema == "wf" for fk in table.foreign_keys)


def test_one_head_per_module_and_inherited_workflow_label():
    scripts = ScriptDirectory.from_config(Config(str(ROOT / "backend/alembic.ini")))
    heads = defaultdict(list)
    for head in scripts.get_heads():
        rev = scripts.get_revision(head)
        heads[Path(rev.path).parent.name].append(head)
    assert dict(heads) == {"platform": ["plat_0001"], "workflow": ["wf_0006"],
                           "deadlines": ["dl_0001"], "evc": ["evc_0002"]}
    assert scripts.get_revision("evc_0002").down_revision == "evc_0001"
    assert scripts.get_revision("evc_0001").down_revision is None
    assert scripts.get_revision("evc_0001").branch_labels == {"evc"}
    assert scripts.get_revision("evc_0001").dependencies == "wf_0001"
    assert scripts.get_revision("wf_0006").down_revision == "wf_0005"
    assert scripts.get_revision("wf_0006").branch_labels == {"workflow"}
    assert scripts.get_revision("wf_0005").down_revision == "wf_0004"
    assert scripts.get_revision("wf_0005").branch_labels == {"workflow"}
    assert scripts.get_revision("wf_0004").down_revision == "wf_0003"
    assert scripts.get_revision("wf_0004").branch_labels == {"workflow"}
    assert scripts.get_revision("wf_0003").branch_labels == {"workflow"}
    assert scripts.get_revision("wf_0003").down_revision == "wf_0002"
    assert scripts.get_revision("wf_0002").branch_labels == {"workflow"}
    assert scripts.get_revision("wf_0002").down_revision == "wf_0001"


def test_upgrade_and_downgrade_preserve_existing_visit_timestamps(client):
    app = submitted(client)
    cfg = Config(str(ROOT / "backend/alembic.ini"))
    cfg.attributes["configure_logger"] = False
    with get_engine().begin() as connection:
        connection.execute(text("UPDATE wf.stage_visit SET exited_at=entered_at WHERE application_id=:id"), {"id": app["id"]})
        before = connection.execute(text("SELECT id, entered_at, exited_at FROM wf.stage_visit WHERE application_id=:id"), {"id": app["id"]}).one()
    try:
        command.downgrade(cfg, "wf_0001")
        with get_engine().connect() as connection:
            assert connection.execute(text("SELECT id, entered_at, left_at FROM wf.stage_visit WHERE application_id=:id"), {"id": app["id"]}).one() == before
        command.upgrade(cfg, "workflow@head")
        with get_engine().connect() as connection:
            assert connection.execute(text("SELECT id, entered_at, exited_at FROM wf.stage_visit WHERE application_id=:id"), {"id": app["id"]}).one() == before
    finally:
        command.upgrade(cfg, "workflow@head")
