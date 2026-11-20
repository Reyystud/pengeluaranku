"""Database engine, sessions and readiness checks (PRD 12, 13.2)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings

BACKEND_DIR = Path(__file__).resolve().parents[2]


def create_db_engine(url: str) -> Engine:
    """Sync engine (PRD 6.5: SQLAlchemy 2, sync). ``pool_pre_ping`` recovers dropped connections."""
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5, future=True)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False, autoflush=False)


def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Yield a session; commit on success, roll back on error (use as a FastAPI dependency)."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def alembic_config(url: str | None = None) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    if url:
        config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def head_revision() -> str | None:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def database_check(engine: Engine) -> Callable[[], None]:
    """Readiness check: the database answers ``SELECT 1``."""

    def check() -> None:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

    return check


def migrations_check(engine: Engine) -> Callable[[], None]:
    """Readiness check: the database is at the Alembic head revision."""

    def check() -> None:
        with engine.connect() as conn:
            current = MigrationContext.configure(conn).get_current_revision()
        if current != head_revision():
            raise RuntimeError("database is not at the migration head")

    return check


def register_readiness(
    app_state_checks: dict[str, Callable[[], None]], settings: Settings
) -> Engine | None:
    """Create the engine and register DB readiness checks; ``None`` if no DATABASE_URL."""
    if not settings.database_url:
        return None
    engine = create_db_engine(settings.database_url)
    app_state_checks["database"] = database_check(engine)
    app_state_checks["migrations"] = migrations_check(engine)
    return engine
