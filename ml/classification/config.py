"""Training config loader for the classifier (config/train/classifier.yaml)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ml.config import config_dir


def load_train_config(path: Path | None = None) -> dict[str, Any]:
    target = path or config_dir() / "train" / "classifier.yaml"
    data = yaml.safe_load(target.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{target} must contain a mapping")
    return data
