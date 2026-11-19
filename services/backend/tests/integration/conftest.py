"""PostgreSQL fixtures. Uses ``TEST_DATABASE_URL`` if set, else a testcontainers PostgreSQL 16."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest
from alembic import command
from app.core.db import alembic_config
from app.models import User
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        yield url
        return
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine", driver="psycopg") as pg:
        yield pg.get_connection_url()


def reset_schema(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))


@pytest.fixture(scope="session")
def engine(database_url: str) -> Iterator[Engine]:
    eng = create_engine(database_url, future=True)
    reset_schema(eng)
    command.upgrade(alembic_config(database_url), "head")
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """A session whose work is rolled back at the end of each test."""
    conn = engine.connect()
    trans = conn.begin()
    sess = sessionmaker(conn, expire_on_commit=False, autoflush=False)()
    try:
        yield sess
    finally:
        sess.close()
        if trans.is_active:
            trans.rollback()
        conn.close()


def make_user(session: Session, email: str | None = None) -> User:
    user = User(
        email=email or f"{uuid.uuid4().hex[:8]}@example.com", password_hash="x", display_name="T"
    )
    session.add(user)
    session.flush()
    return user
