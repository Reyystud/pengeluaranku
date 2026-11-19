"""Generator configuration: loads and validates the YAML files under ``config/generator/``."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from ml.config import Merchant, merchants_from_mapping
from ml.schemas.synthetic import ANOMALY_TYPES, ARCHETYPES, INCOME_PROFILES, PAYMENT_METHODS
from ml.taxonomy import MODEL_LABELS


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a mapping at top level")
    return data


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class Archetype:
    name: str
    weight: float
    income_profile: str
    income: dict[str, Any]
    daily_tx_lambda: float
    amount_scale: float
    category_share: dict[str, float]
    subscription_kinds: tuple[str, ...]
    subscription_adoption: float
    subscription_extra_services: int
    monthly_bills: tuple[dict[str, Any], ...]
    transfers_per_month: tuple[int, int]
    anomaly_rate: float
    anomaly_types: tuple[str, ...]
    end_of_period_days: int
    end_of_period_factor: float
    payday_days: int | None
    payday_factor: float | None


@dataclass
class GeneratorConfig:
    seed: int
    raw: dict[str, Any]
    n_users: int
    months: int
    start_date: date
    dataset_name: str
    archetypes: tuple[Archetype, ...]
    merchants: tuple[Merchant, ...]
    subscriptions: dict[str, Any]
    input_files_sha256: dict[str, str] = field(default_factory=dict)

    @property
    def params(self) -> dict[str, Any]:
        return self.raw

    def assign_archetypes(self) -> list[str]:
        """Deterministic archetype per user index: largest-remainder quotas, then shuffled."""
        weights = np.array([a.weight for a in self.archetypes], dtype=float)
        quotas = weights / weights.sum() * self.n_users
        counts = np.floor(quotas).astype(int)
        remainder = self.n_users - int(counts.sum())
        order = np.argsort(-(quotas - counts), kind="stable")
        for i in order[:remainder]:
            counts[i] += 1
        names = [a.name for a, c in zip(self.archetypes, counts, strict=True) for _ in range(c)]
        permutation = np.random.default_rng([self.seed, 999_999]).permutation(len(names))
        return [names[int(i)] for i in permutation]

    def archetype(self, name: str) -> Archetype:
        for a in self.archetypes:
            if a.name == name:
                return a
        raise KeyError(name)

    def manifest_config(self) -> dict[str, Any]:
        """Inlined, JSON-serializable configuration recorded in manifest.json."""
        params = {k: v for k, v in self.raw.items() if k != "_archetype_raw"}
        return {
            "seed": self.seed,
            "params": params,
            "archetypes": self.raw["_archetype_raw"],
            "input_files_sha256": self.input_files_sha256,
        }


def _parse_archetype(data: dict[str, Any]) -> Archetype:
    name = str(data["archetype"])
    if name not in ARCHETYPES:
        raise ValueError(f"unknown archetype: {name}")
    profile = str(data["income_profile"])
    if profile not in INCOME_PROFILES:
        raise ValueError(f"{name}: unknown income_profile {profile}")
    share = {str(k): float(v) for k, v in data["category_share"].items()}
    unknown = set(share) - set(MODEL_LABELS)
    if unknown:
        raise ValueError(f"{name}: unknown categories in category_share: {sorted(unknown)}")
    if abs(sum(share.values()) - 1.0) > 1e-3:
        raise ValueError(f"{name}: category_share sums to {sum(share.values()):.4f}, expected 1")
    anomalies = data.get("anomalies", {})
    types = tuple(str(t) for t in anomalies.get("types", ANOMALY_TYPES))
    if not set(types) <= set(ANOMALY_TYPES):
        raise ValueError(f"{name}: unknown anomaly types {types}")
    eop = data.get("end_of_period", {})
    payday = data.get("payday")
    tpm = data.get("transfers_per_month", [1, 3])
    return Archetype(
        name=name,
        weight=float(data["weight"]),
        income_profile=profile,
        income=dict(data["monthly_income"]),
        daily_tx_lambda=float(data["daily_tx_lambda"]),
        amount_scale=float(data.get("amount_scale", 1.0)),
        category_share=share,
        subscription_kinds=tuple(str(k) for k in data.get("subscriptions", [])),
        subscription_adoption=float(data.get("subscription_adoption", 0.75)),
        subscription_extra_services=int(data.get("subscription_extra_services", 0)),
        monthly_bills=tuple(dict(b) for b in data.get("monthly_bills", [])),
        transfers_per_month=(int(tpm[0]), int(tpm[1])),
        anomaly_rate=float(anomalies.get("rate", 0.01)),
        anomaly_types=types,
        end_of_period_days=int(eop.get("days", 0)),
        end_of_period_factor=float(eop.get("lambda_factor", 1.0)),
        payday_days=int(payday["days"]) if payday else None,
        payday_factor=float(payday["lambda_factor"]) if payday else None,
    )


def load_config(
    path: Path,
    seed: int,
    n_users: int | None = None,
    months: int | None = None,
    noise_scale: float | None = None,
) -> GeneratorConfig:
    """Load ``default.yaml``-style config; the keyword overrides are recorded in the manifest."""
    base = path.resolve().parent
    raw = _read_yaml(path)
    if n_users is not None:
        raw["n_users"] = n_users
    if months is not None:
        raw["months"] = months
    if noise_scale is not None:
        raw["noise"]["scale"] = noise_scale

    start = date.fromisoformat(str(raw["start_date"]))
    if start.day != 1:
        raise ValueError("start_date must be the 1st of a month")
    if int(raw["n_users"]) < 1 or int(raw["months"]) < 1:
        raise ValueError("n_users and months must be >= 1")

    merchants_path = base / str(raw["merchants_file"])
    subs_path = base / str(raw["subscriptions_file"])
    merchants = merchants_from_mapping(_read_yaml(merchants_path))
    subscriptions = _read_yaml(subs_path)
    archetype_paths = [base / str(p) for p in raw["archetype_files"]]
    archetype_raw = [_read_yaml(p) for p in archetype_paths]
    archetypes = tuple(_parse_archetype(a) for a in archetype_raw)

    if len({a.name for a in archetypes}) != len(archetypes):
        raise ValueError("duplicate archetype names")
    if abs(sum(a.weight for a in archetypes) - 1.0) > 1e-3:
        raise ValueError("archetype weights must sum to 1")

    used_categories = {c for a in archetypes for c in a.category_share} | {
        str(b["category"]) for a in archetypes for b in a.monthly_bills
    }
    covered = {m.category for m in merchants}
    missing = used_categories - covered
    if missing:
        raise ValueError(f"no merchants for categories: {sorted(missing)}")
    for kind, spec in subscriptions["kinds"].items():
        if spec["category"] not in MODEL_LABELS:
            raise ValueError(f"subscription kind {kind}: invalid category {spec['category']}")
    for a in archetypes:
        for kind in a.subscription_kinds:
            if kind not in subscriptions["kinds"]:
                raise ValueError(f"{a.name}: unknown subscription kind {kind}")
    for method_probs in raw["payment_methods"].values():
        if not set(method_probs) <= set(PAYMENT_METHODS):
            raise ValueError(f"unknown payment methods: {sorted(method_probs)}")

    raw["_archetype_raw"] = archetype_raw
    files = [path, merchants_path, subs_path, *archetype_paths]
    return GeneratorConfig(
        seed=seed,
        raw=raw,
        n_users=int(raw["n_users"]),
        months=int(raw["months"]),
        start_date=start,
        dataset_name=str(raw["dataset_name"]),
        archetypes=archetypes,
        merchants=merchants,
        subscriptions=subscriptions,
        input_files_sha256={p.name: _sha256(p) for p in files},
    )
