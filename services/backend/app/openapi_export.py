"""``python -m app.openapi_export [path]``: write the OpenAPI document (PRD 8.3, `make openapi`).

Deterministic output (sorted keys, trailing newline) so CI can check that the committed file
and the generated frontend client are up to date.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.core.config import Settings
from app.main import create_app


def render() -> str:
    app = create_app(Settings(_env_file=None, app_env="ci"))  # type: ignore[call-arg]
    return json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "services/backend/openapi.json")
    target.write_text(render(), encoding="utf-8")


if __name__ == "__main__":
    main()
