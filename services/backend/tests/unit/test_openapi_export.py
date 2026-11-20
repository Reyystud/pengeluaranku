"""The committed OpenAPI file is what the frontend client is generated from (PRD 8.3)."""

from __future__ import annotations

from pathlib import Path

from app.openapi_export import render

COMMITTED = Path(__file__).resolve().parents[2] / "openapi.json"


def test_8_3_committed_openapi_matches_the_app() -> None:
    assert (
        COMMITTED.read_text(encoding="utf-8") == render()
    ), "services/backend/openapi.json is stale: run `make openapi` and commit the result"


def test_8_3_export_is_deterministic() -> None:
    assert render() == render()
