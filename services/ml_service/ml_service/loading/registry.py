"""Holds the loaded models. A new version replaces the old one in a single reference swap."""

from __future__ import annotations

import threading

from ml_service.config import Settings
from ml_service.loading.artifact import LoadedClassifier, ModelLoadError, load_classifier
from ml_service.loading.sources import ModelSource, make_source
from ml_service.metrics import record_model_load_failure, record_model_loaded


class ModelRegistry:
    def __init__(self, settings: Settings, source: ModelSource | None = None) -> None:
        self._settings = settings
        self._source = source or make_source(
            settings, settings.classifier_model_name, settings.classifier_alias
        )
        self._lock = threading.Lock()
        self.classifier: LoadedClassifier | None = None
        self.error: ModelLoadError | None = None

    def load(self) -> bool:
        """Resolve, verify and load the classifier. On failure the previous model (if any) stays."""
        try:
            resolved = self._source.resolve()
            loaded = load_classifier(
                resolved.directory,
                version=resolved.version,
                alias=resolved.alias,
                expected_name=self._settings.classifier_model_name,
            )
        except ModelLoadError as exc:
            with self._lock:
                self.error = exc
            record_model_load_failure(self._settings.classifier_model_name, exc.code)
            return False
        with self._lock:
            self.classifier, self.error = loaded, None
        record_model_loaded(loaded.name, loaded.version, loaded.alias or "local")
        return True

    def refresh(self) -> bool:
        """Poll step (PRD 11.5): load only when the source now points at another version.

        The old model keeps serving until the new one is loaded and verified; a lookup or load
        failure leaves it in place. Returns True when a new version was swapped in.
        """
        current = self.classifier
        try:
            latest = self._source.current_version()
        except ModelLoadError as exc:
            with self._lock:
                self.error = exc
            record_model_load_failure(self._settings.classifier_model_name, exc.code)
            return False
        if current is not None and current.version == latest:
            return False
        return self.load()

    def require_classifier(self) -> LoadedClassifier:
        classifier = self.classifier
        if classifier is None:
            raise ModelLoadError("MODEL_NOT_AVAILABLE", "the classifier is not loaded")
        return classifier

    def check_ready(self) -> None:
        """Readiness check: every required model is loaded (the classifier is required)."""
        if self.classifier is None:
            raise ModelLoadError(
                self.error.code if self.error else "NOT_LOADED", "classifier not loaded"
            )
