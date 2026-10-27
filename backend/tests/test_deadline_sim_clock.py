"""Demo time travel is stored in dl.sim_clock, so a separately running timer worker sees the same time as the API."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.deadlines import clock as clock_module
from app.deadlines.clock import SystemClock
from app.deadlines.wiring import clock
from app.platform.db import get_engine
from conftest import SUNRISE, headers
from contracts.errors import Forbidden

INST = headers("INSTITUTION", SUNRISE)


def stored_offset() -> int | None:
    with get_engine().connect() as c:
        return c.execute(text("SELECT offset_seconds FROM dl.sim_clock WHERE id = 1")).scalar()


def test_api_time_travel_is_seen_by_another_process_clock(client):
    worker_clock = SystemClock(refresh_seconds=0)          # what a separate worker process would build
    assert worker_clock.offset == timedelta(0)
    r = client.post("/api/sim/clock", headers=INST, json={"days": 3})
    assert r.status_code == 200 and r.json()["offset_days"] == 3
    assert stored_offset() == 3 * 86400
    assert worker_clock.offset == timedelta(days=3)
    assert SystemClock().offset == timedelta(days=3)         # a fresh process reads it on first use
    assert abs(worker_clock.now() - (datetime.now(timezone.utc) + timedelta(days=3))) < timedelta(seconds=5)

    clock.reset()
    assert stored_offset() == 0
    assert worker_clock.offset == timedelta(0)
    assert client.get("/api/sim/clock", headers=INST).json()["offset_days"] == 0


def test_the_offset_is_cached_briefly_but_own_changes_apply_at_once(client):
    cached = SystemClock(refresh_seconds=3600)
    assert cached.offset == timedelta(0)
    clock.advance(2)                                        # another process moves the clock
    assert cached.offset == timedelta(0)                    # not re-read yet
    cached.advance(1)                                       # its own change: read back from the database
    assert cached.offset == timedelta(days=3) and stored_offset() == 3 * 86400
    cached.reset()
    assert cached.offset == timedelta(0)
    clock.reset()


def test_outside_demo_mode_a_stored_offset_is_ignored(client, monkeypatch):
    clock.advance(30)
    assert stored_offset() == 30 * 86400
    monkeypatch.setattr(clock_module, "settings", replace(clock_module.settings, demo_mode=False))
    for c in (SystemClock(), clock):
        assert c.offset == timedelta(0)
        assert abs(c.now() - datetime.now(timezone.utc)) < timedelta(seconds=5)
        with pytest.raises(Forbidden):
            c.advance(1)
        with pytest.raises(Forbidden):
            c.reset()
    assert stored_offset() == 30 * 86400                    # refused calls changed nothing
    monkeypatch.undo()
    clock.reset()


def test_sim_clock_migration_downgrade_and_reupgrade(client):
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.attributes["configure_logger"] = False

    def table_exists() -> bool:
        with get_engine().connect() as c:
            return c.execute(text("SELECT to_regclass('dl.sim_clock')")).scalar() is not None

    clock.advance(1)
    get_engine().dispose()   # no pooled connection may hold a lock on the table while it is dropped
    try:
        command.downgrade(config, "deadlines@dl_0005_timer_alerts")
        assert not table_exists()
        assert SystemClock().offset == timedelta(0)        # unreadable table: real time, no crash
        command.upgrade(config, "heads")
        assert table_exists() and stored_offset() is None
        with get_engine().begin() as c:
            with pytest.raises(Exception):
                with c.begin_nested():
                    c.execute(text("INSERT INTO dl.sim_clock (id, offset_seconds) VALUES (2, 0)"))
        clock.reset()
        assert stored_offset() == 0
    finally:
        command.upgrade(config, "heads")
