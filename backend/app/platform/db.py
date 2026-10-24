from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.platform.settings import settings
from contracts.types import Principal


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_sessions: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine, _sessions
    if _engine is None:
        _engine = create_engine(settings.database_url, pool_pre_ping=True)
        _sessions = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def new_session() -> Session:
    get_engine()
    return _sessions()


@dataclass
class UnitOfWork:
    session: Session
    principal: Principal


@contextmanager
def unit_of_work(principal: Principal) -> Iterator[UnitOfWork]:
    """One command = one transaction. Everything written inside commits together or not at all."""
    session = new_session()
    try:
        yield UnitOfWork(session, principal)
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()
