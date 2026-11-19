from pathlib import Path

import pytest

from data_generator.config import GeneratorConfig, load_config
from data_generator.generate import build_frames

CONFIG = Path(__file__).resolve().parents[2] / "config" / "generator" / "default.yaml"


def small_config(seed: int = 7, n_users: int = 60, months: int = 4) -> GeneratorConfig:
    return load_config(CONFIG, seed=seed, n_users=n_users, months=months)


@pytest.fixture(scope="session")
def cfg() -> GeneratorConfig:
    return small_config()


@pytest.fixture(scope="session")
def frames(cfg: GeneratorConfig):  # type: ignore[no-untyped-def]
    return build_frames(cfg)
