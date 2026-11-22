"""Typed view of ``config/insights.yaml`` (PRD 7.9, 0.3 rule 3)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from typing import Any

from ml.config import _load_yaml


@dataclass(frozen=True)
class InsightConfig:
    version: str
    dashboard_top: int
    rules: dict[str, dict[str, Any]]

    def rule_version(self, rule_id: str) -> str:
        return str(self.rules[rule_id]["version"])

    def number(self, rule_id: str, key: str) -> Decimal:
        return Decimal(str(self.rules[rule_id][key]))


@lru_cache(maxsize=1)
def load_insight_config() -> InsightConfig:
    raw = _load_yaml("insights.yaml")
    return InsightConfig(
        version=str(raw["version"]),
        dashboard_top=int(raw["dashboard_top"]),
        rules={str(k): dict(v) for k, v in raw["rules"].items()},
    )
