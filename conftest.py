"""Shared test fixtures: a fresh PostgreSQL test database migrated with every module's chain."""
import os
import sys
from pathlib import Path
from uuid import UUID

import pytest

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://awoc:awoc@localhost:5432/awoc_test")
os.environ.setdefault("DEMO_MODE", "true")
os.environ.setdefault("DEMO_AUTH", "true")
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

SUNRISE = UUID("00000000-0000-4000-8000-000000000001")
NORTHFIELD = UUID("00000000-0000-4000-8000-000000000002")


def headers(role: str, institution: UUID | None = None, user: str = "00000000-0000-4000-9000-000000000001"):
    h = {"X-Demo-User": user, "X-Demo-Role": role}
    if institution:
        h["X-Demo-Institution"] = str(institution)
    return h


@pytest.fixture(scope="session")
def database():
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    url = make_url(os.environ["DATABASE_URL"])
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
        c.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()

    cfg = Config(str(ROOT / "backend" / "alembic.ini"))
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "heads")
    return url


@pytest.fixture
def client(database):
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    from app.deadlines.wiring import clock
    from app.main import create_app
    from app.platform.db import get_engine
    from generator.cases.seed_demo import seed

    app = create_app()
    with get_engine().begin() as c:
        tables = c.execute(text(
            "SELECT format('%I.%I', schemaname, tablename) FROM pg_tables "
            "WHERE schemaname NOT IN ('public', 'pg_catalog', 'information_schema')")).scalars().all()
        if tables:
            c.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))
    seed()
    clock.reset()
    return TestClient(app)
