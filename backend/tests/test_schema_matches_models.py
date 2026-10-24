"""The SQLAlchemy models and the migrations must describe exactly the same tables."""
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.main import load_models
from app.platform.db import Base, get_engine

SCHEMAS = {"plat", "wf", "evc", "doc", "cmp", "dl", "an"}


def include_name(name, type_, parent_names):
    if type_ == "schema":
        return name in SCHEMAS
    return True


def test_models_match_migrations(database):
    load_models()
    with get_engine().connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"include_schemas": True, "include_name": include_name})
        diff = compare_metadata(ctx, Base.metadata)
    assert diff == []
