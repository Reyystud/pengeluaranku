"""A tiny synthetic dataset with locked splits, built once per session in a temp root."""

from __future__ import annotations

from pathlib import Path

import pytest

from data_generator.config import load_config
from data_generator.generate import write_dataset
from ml.evaluation.__main__ import main as splits_main

CONFIG = Path(__file__).resolve().parents[2] / "config" / "generator" / "default.yaml"
VERSION = "synthetic/tiny"


@pytest.fixture(scope="session")
def tiny_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("pipeline_root")
    cfg = load_config(CONFIG, seed=7, n_users=60, months=4)
    write_dataset(cfg, root / "data" / VERSION)
    code = splits_main(
        [
            "make-splits",
            "--data",
            str(root / "data" / VERSION),
            "--dataset-version",
            VERSION,
            "--splits-dir",
            str(root / "data_splits"),
            "--assignments-dir",
            str(root / "data" / "splits"),
        ]
    )
    assert code == 0
    return root
