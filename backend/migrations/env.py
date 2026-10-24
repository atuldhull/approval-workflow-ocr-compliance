import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "backend"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from app.main import load_models  # noqa: E402
from app.platform.db import Base  # noqa: E402
from app.platform.settings import settings  # noqa: E402

if context.config.config_file_name and context.config.attributes.get("configure_logger", True):
    fileConfig(context.config.config_file_name, disable_existing_loggers=False)

load_models()
target_metadata = Base.metadata


def run_offline() -> None:
    context.configure(url=settings.database_url, target_metadata=target_metadata, include_schemas=True,
                      literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    engine = create_engine(settings.database_url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, include_schemas=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
