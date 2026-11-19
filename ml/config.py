"""Loaders for the versioned YAML files in ``config/`` (PRD section 22).

The config directory defaults to ``<repo>/config`` and can be overridden with the
``SEI_CONFIG_DIR`` environment variable (used by container images).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, cast

import yaml

HolidayKind = Literal["national", "collective_leave"]
_HOLIDAY_KINDS: tuple[str, ...] = ("national", "collective_leave")


def config_dir() -> Path:
    override = os.environ.get("SEI_CONFIG_DIR")
    return Path(override) if override else Path(__file__).resolve().parents[1] / "config"


def _load_yaml(relative_path: str) -> dict[str, Any]:
    path = config_dir() / relative_path
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a mapping at top level")
    return cast("dict[str, Any]", data)


@dataclass(frozen=True)
class Merchant:
    name: str
    category: str
    weight: int
    abbrevs: tuple[str, ...] = ()
    ambiguous_with: tuple[str, ...] = ()


@dataclass(frozen=True)
class Holiday:
    day: date
    kind: HolidayKind
    name: str


@lru_cache(maxsize=1)
def load_merchants() -> tuple[Merchant, ...]:
    """All generator merchants, in file order (``config/generator/merchants.yaml``)."""
    data = _load_yaml("generator/merchants.yaml")
    merchants: list[Merchant] = []
    for category, entries in data["categories"].items():
        for entry in entries:
            merchants.append(
                Merchant(
                    name=str(entry["name"]),
                    category=str(category),
                    weight=int(entry["weight"]),
                    abbrevs=tuple(entry.get("abbrevs", ())),
                    ambiguous_with=tuple(entry.get("ambiguous_with", ())),
                )
            )
    return tuple(merchants)


@lru_cache(maxsize=1)
def load_aliases() -> dict[str, str]:
    """Merchant alias map: normalized alias -> canonical normalized name."""
    data = _load_yaml("merchant_aliases.yaml")
    return {str(k): str(v) for k, v in data["aliases"].items()}


@lru_cache(maxsize=1)
def load_cities() -> tuple[frozenset[str], frozenset[str]]:
    """(city names, city abbreviations) removed by merchant normalization step 5."""
    data = _load_yaml("cities_id.yaml")
    return frozenset(data["cities"]), frozenset(data["abbreviations"])


@lru_cache(maxsize=1)
def load_holidays() -> tuple[tuple[int, ...], tuple[Holiday, ...]]:
    """(covered years, holidays sorted by date)."""
    data = _load_yaml("holidays_id.yaml")
    holidays = []
    for entry in data["holidays"]:
        kind = str(entry["kind"])
        if kind not in _HOLIDAY_KINDS:
            raise ValueError(f"unknown holiday kind: {kind}")
        holidays.append(
            Holiday(
                day=date.fromisoformat(str(entry["date"])),
                kind=cast("HolidayKind", kind),
                name=str(entry["name"]),
            )
        )
    holidays.sort(key=lambda h: h.day)
    return tuple(int(y) for y in data["covered_years"]), tuple(holidays)
