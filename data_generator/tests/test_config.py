from pathlib import Path

import pytest
import yaml

from data_generator.config import load_config
from data_generator.tests.conftest import CONFIG, small_config


def test_default_config_loads_and_matches_prd_mix() -> None:
    cfg = load_config(CONFIG, seed=42)
    assert cfg.n_users == 2000 and cfg.months == 12
    mix = {a.name: a.weight for a in cfg.archetypes}
    assert mix == {
        "student": 0.35,
        "young_professional": 0.35,
        "freelancer": 0.10,
        "impulsive_spender": 0.10,
        "subscription_heavy": 0.10,
    }


def test_archetype_assignment_exact_quota_and_deterministic() -> None:
    cfg = small_config(n_users=200)
    first = cfg.assign_archetypes()
    assert first == cfg.assign_archetypes()
    counts = {n: first.count(n) for n in set(first)}
    assert counts == {
        "student": 70,
        "young_professional": 70,
        "freelancer": 20,
        "impulsive_spender": 20,
        "subscription_heavy": 20,
    }


def test_assignment_depends_on_seed() -> None:
    assert (
        small_config(seed=1, n_users=200).assign_archetypes()
        != small_config(seed=2, n_users=200).assign_archetypes()
    )


def _copy_config(tmp_path: Path, mutate_archetype: str | None = None) -> Path:
    base = CONFIG.parent
    for src in [*base.glob("*.yaml"), *base.glob("archetypes/*.yaml")]:
        dst = tmp_path / src.relative_to(base)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src.read_text())
    if mutate_archetype:
        path = tmp_path / "archetypes" / "student.yaml"
        data = yaml.safe_load(path.read_text())
        data["category_share"][mutate_archetype] = 0.5
        path.write_text(yaml.safe_dump(data))
    return tmp_path / "default.yaml"


def test_category_share_must_sum_to_one(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="sums to"):
        load_config(_copy_config(tmp_path, "food_beverage"), seed=1)


def test_start_date_must_be_first_of_month(tmp_path: Path) -> None:
    path = _copy_config(tmp_path)
    data = yaml.safe_load(path.read_text())
    data["start_date"] = "2025-01-15"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match="1st of a month"):
        load_config(path, seed=1)
