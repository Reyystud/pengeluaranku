import io
import json
from collections.abc import Callable
from typing import Any

import pytest
from app.core.config import Settings
from app.main import create_app
from fastapi import APIRouter
from fastapi.testclient import TestClient


class Harness:
    def __init__(self, router: APIRouter | None = None) -> None:
        self.stream = io.StringIO()
        settings = Settings(_env_file=None, app_env="ci", log_level="DEBUG")  # type: ignore[call-arg]
        self.app = create_app(settings, log_stream=self.stream)
        if router is not None:
            self.app.include_router(router)
        self.client = TestClient(self.app, raise_server_exceptions=False)

    @property
    def log_text(self) -> str:
        return self.stream.getvalue()

    def log_events(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in self.log_text.splitlines() if line.startswith("{")]


@pytest.fixture
def make_harness() -> Callable[..., Harness]:
    return Harness
