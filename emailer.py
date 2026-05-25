"""
db.py — Database engine, session management, and initialisation helpers.

Provides:
  - get_engine()        : SQLAlchemy engine (singleton)
  - get_session()       : context-manager session for agent use
  - init_db()           : create all tables (called on startup)
  - health_check()      : lightweight connectivity test

Usage:
    from agent.db import get_session, init_db

    init_db()   # called once at startup

    with get_session() as session:
        run = AgentRun(cluster_name="SB-PROD", ...)
        session.add(run)
        session.commit()
"""

from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from agent.config import get_settings
from agent.logger import get_logger
from agent.models import Base

log = get_logger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Engine (singleton)
# ──────────────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def get_engine():
    """
    Create and return the SQLAlchemy engine.
    Connection pool is sized for an agent that runs ~4 concurrent DB writes
    per 15-minute cycle.
    """
    cfg = get_settings()
    engine = create_engine(
        cfg.db_url,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,      # verify connections before use
        pool_recycle=3600,       # recycle connections every hour
        echo=cfg.log_level == "DEBUG",
    )
    log.info("db_engine_created", url=cfg.db_url.split("@")[-1])  # hide credentials
    return engine


# ──────────────────────────────────────────────────────────────────────────────
# Session factory
# ──────────────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _get_session_factory() -> sessionmaker:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """
    Context manager that yields a database session.

    Automatically commits on success and rolls back on any exception.
    Always closes the session when the block exits.

    Usage:
        with get_session() as session:
            session.add(my_object)
            # commit happens automatically on clean exit
    """
    factory = _get_session_factory()
    session: Session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ──────────────────────────────────────────────────────────────────────────────
# Lifecycle helpers
# ──────────────────────────────────────────────────────────────────────────────

def init_db() -> None:
    """
    Create all ORM tables in PostgreSQL if they don't already exist.

    Safe to call on every startup — uses CREATE TABLE IF NOT EXISTS semantics.
    For schema migrations, use Alembic instead of this function.
    """
    engine = get_engine()
    log.info("db_init_start")
    Base.metadata.create_all(bind=engine)
    log.info("db_init_complete", tables=list(Base.metadata.tables.keys()))


def health_check() -> bool:
    """
    Verify the database is reachable.

    Returns True if the connection succeeds, False otherwise.
    Used by the agent's startup check and the dashboard's /health endpoint.
    """
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        log.debug("db_health_ok")
        return True
    except OperationalError as exc:
        log.error("db_health_failed", error=str(exc))
        return False
