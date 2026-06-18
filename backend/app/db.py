"""SQLAlchemy engine/session setup.

SQLite for the MVP (single file, zero ops). Because all model access goes
through ``SessionLocal`` and the ORM, swapping ``DATABASE_URL`` to Postgres
later requires no code changes here.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


def _make_engine():
    kwargs: dict = {"pool_pre_ping": True}
    if settings.is_sqlite:
        # Ensure the sqlite file's parent dir exists.
        sqlite_path = settings.sqlite_path
        if sqlite_path is not None:
            sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False so the RQ worker + web process can share it.
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(settings.database_url, **kwargs)


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    """Create tables. Import models so they register on ``Base.metadata``."""
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


@contextmanager
def session_scope() -> Iterator:
    """Transactional session for worker/pipeline code."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator:
    """FastAPI dependency."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
