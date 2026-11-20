"""Security tests reuse the integration fixtures (real PostgreSQL, fresh app per test)."""

from tests.integration.conftest import (  # noqa: F401
    client,
    database_url,
    engine,
    log_stream,
    session,
)
