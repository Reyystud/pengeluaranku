"""Where model artifacts come from: a local directory (dev) or the MLflow registry (PRD 11.5)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ml_service.config import Settings
from ml_service.loading.artifact import ModelLoadError


@dataclass(frozen=True)
class Resolved:
    directory: Path
    version: str
    alias: str | None


class ModelSource(Protocol):
    def resolve(self) -> Resolved:
        """Locate (and download, if remote) the artifact directory. Raises ModelLoadError."""
        ...


class LocalDirSource:
    """``models/<name>/<run_id>/`` as written by ``make train-local``; newest run by default."""

    def __init__(self, models_dir: Path, name: str, version: str | None) -> None:
        self._root = models_dir / name
        self._version = version

    def resolve(self) -> Resolved:
        if self._version:
            candidates = [self._root / self._version]
        else:
            candidates = sorted(p for p in self._root.glob("*") if p.is_dir())[-1:]
        if not candidates or not candidates[0].is_dir():
            raise ModelLoadError("SOURCE_UNAVAILABLE", "no model directory found")
        return Resolved(candidates[0], candidates[0].name, None)


class MlflowSource:
    """``models:/<name>@<alias>``, downloaded into a local cache directory."""

    def __init__(self, tracking_uri: str, name: str, alias: str, cache_dir: Path) -> None:
        self._uri, self._name, self._alias, self._cache = tracking_uri, name, alias, cache_dir

    def resolve(self) -> Resolved:
        try:
            import mlflow
            from mlflow import MlflowClient

            client = MlflowClient(tracking_uri=self._uri, registry_uri=self._uri)
            model_version = client.get_model_version_by_alias(self._name, self._alias)
            version = str(model_version.version)
            target = self._cache / self._name / version
            target.mkdir(parents=True, exist_ok=True)
            mlflow.artifacts.download_artifacts(
                artifact_uri=model_version.source,  # runs:/<run_id>/model
                dst_path=str(target),
                tracking_uri=self._uri,
            )
        except Exception as exc:
            raise ModelLoadError(
                "SOURCE_UNAVAILABLE", f"MLflow lookup failed: {type(exc).__name__}"
            ) from exc
        return Resolved(self._directory(target), version, self._alias)

    @staticmethod
    def _directory(target: Path) -> Path:
        """The download may nest the files one level down (``model/``)."""
        if (target / "metadata.json").is_file():
            return target
        nested = [p.parent for p in target.glob("*/metadata.json")]
        return nested[0] if nested else target


def make_source(settings: Settings, name: str, alias: str) -> ModelSource:
    if settings.model_source == "local_dir":
        return LocalDirSource(settings.models_dir, name, settings.model_version)
    return MlflowSource(
        settings.mlflow_tracking_uri, name, alias, settings.models_dir / ".mlflow-cache"
    )
