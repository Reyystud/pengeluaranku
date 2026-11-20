"""Classifier artifact loading with integrity checks (PRD 11.4, 11.6).

Joblib artifacts are pickles: they are loaded only after every file listed in
``metadata.json -> artifact_sha256`` matches, and only from the project's own model store.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ml.features import FEATURE_VERSION
from ml.taxonomy import MODEL_LABELS, TAXONOMY_VERSION


class ModelLoadError(Exception):
    """The artifact must not be served. ``code`` is a stable machine-readable reason."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class LoadedClassifier:
    name: str
    version: str  # shown as "<name>@<version>"
    alias: str | None
    feature_version: str
    taxonomy_version: str
    labels: tuple[str, ...]
    t_high: float
    t_low: float
    transformer: Any
    model: Any
    calibrator: Any
    metadata: dict[str, Any] = field(repr=False)
    loaded_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))

    @property
    def label(self) -> str:
        return f"{self.name}@{self.version}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_hashes(directory: Path, metadata: dict[str, Any]) -> None:
    hashes = metadata.get("artifact_sha256")
    if not isinstance(hashes, dict) or not hashes:
        raise ModelLoadError("HASH_MISSING", "metadata.json lists no artifact hashes")
    if "model.joblib" not in hashes:
        raise ModelLoadError("HASH_MISSING", "metadata.json has no hash for model.joblib")
    root = directory.resolve()
    for name, expected in hashes.items():
        path = (directory / name).resolve()
        if root not in path.parents or not path.is_file():
            raise ModelLoadError("ARTIFACT_MISSING", f"artifact {name!r} is missing")
        if sha256_file(path) != expected:
            raise ModelLoadError("HASH_MISMATCH", f"artifact {name!r} does not match its hash")


def _thresholds(metadata: dict[str, Any]) -> tuple[float, float]:
    raw = metadata.get("decision_thresholds")
    if not isinstance(raw, dict):
        raise ModelLoadError("THRESHOLDS_MISSING", "metadata.json has no decision_thresholds")
    try:
        t_high, t_low = float(raw["t_high"]), float(raw["t_low"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ModelLoadError("THRESHOLDS_INVALID", "t_high / t_low must be numbers") from exc
    if not (0.0 <= t_low <= t_high <= 1.0):
        raise ModelLoadError("THRESHOLDS_INVALID", "need 0 <= t_low <= t_high <= 1")
    return t_high, t_low


def load_classifier(
    directory: Path, *, version: str, alias: str | None = None, expected_name: str
) -> LoadedClassifier:
    """Verify, then load. Raises ``ModelLoadError``; never returns a half-checked model."""
    meta_path = directory / "metadata.json"
    if not meta_path.is_file():
        raise ModelLoadError("METADATA_MISSING", "metadata.json not found")
    try:
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ModelLoadError("METADATA_INVALID", "metadata.json is not valid JSON") from exc
    if not isinstance(metadata, dict):
        raise ModelLoadError("METADATA_INVALID", "metadata.json must be an object")

    if metadata.get("model_name") != expected_name:
        raise ModelLoadError("WRONG_MODEL", "metadata model_name does not match")
    if metadata.get("feature_version") != FEATURE_VERSION:
        raise ModelLoadError(
            "FEATURE_VERSION_UNSUPPORTED", f"this service computes {FEATURE_VERSION} only"
        )
    if metadata.get("taxonomy_version") != TAXONOMY_VERSION:
        raise ModelLoadError("TAXONOMY_MISMATCH", "taxonomy version differs from the service")
    if tuple(metadata.get("labels") or ()) != MODEL_LABELS:
        raise ModelLoadError("LABELS_MISMATCH", "labels differ from the taxonomy")
    t_high, t_low = _thresholds(metadata)
    verify_hashes(directory, metadata)  # before the pickle is touched

    import joblib

    try:
        artifacts = joblib.load(directory / "model.joblib")
        parts = (artifacts["transformer"], artifacts["model"], artifacts["calibrator"])
    except Exception as exc:  # corrupt pickle or unexpected structure
        raise ModelLoadError(
            "ARTIFACT_INVALID", f"model.joblib cannot be used: {type(exc).__name__}"
        ) from exc
    if tuple(artifacts.get("labels") or ()) != MODEL_LABELS:
        raise ModelLoadError("LABELS_MISMATCH", "model labels differ from the taxonomy")
    return LoadedClassifier(
        name=expected_name,
        version=version,
        alias=alias,
        feature_version=FEATURE_VERSION,
        taxonomy_version=TAXONOMY_VERSION,
        labels=MODEL_LABELS,
        t_high=t_high,
        t_low=t_low,
        transformer=parts[0],
        model=parts[1],
        calibrator=parts[2],
        metadata=metadata,
    )
