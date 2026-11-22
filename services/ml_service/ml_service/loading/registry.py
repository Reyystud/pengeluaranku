"""Holds the loaded models. A new version replaces the old one in a single reference swap."""

from __future__ import annotations

import threading

from ml_service.config import Settings
from ml_service.loading.artifact import LoadedClassifier, ModelLoadError, load_classifier
from ml_service.loading.sources import ModelSource, make_source
from ml_service.metrics import (
    record_model_load_failure,
    record_model_loaded,
    record_shadow_loaded,
)


class ModelRegistry:
    def __init__(
        self,
        settings: Settings,
        source: ModelSource | None = None,
        candidate_source: ModelSource | None = None,
    ) -> None:
        self._settings = settings
        self._source = source or make_source(
            settings, settings.classifier_model_name, settings.classifier_alias
        )
        # Shadow mode needs the registry's `candidate` alias; a local models/ directory has none.
        self._candidate_source: ModelSource | None = candidate_source
        if (
            self._candidate_source is None
            and settings.shadow_enabled
            and settings.model_source == "mlflow"
        ):
            self._candidate_source = make_source(
                settings, settings.classifier_model_name, settings.classifier_shadow_alias
            )
        self._lock = threading.Lock()
        self.classifier: LoadedClassifier | None = None
        self.candidate: LoadedClassifier | None = None
        self.error: ModelLoadError | None = None

    @property
    def shadow_active(self) -> bool:
        """A candidate is loaded and it is not the version production already serves."""
        c, p = self.candidate, self.classifier
        return c is not None and p is not None and c.version != p.version

    def load_candidate(self) -> bool:
        """Load the shadow candidate. Never touches readiness or the production model.

        No candidate alias (or a failed load) simply means no shadow traffic.
        """
        if not self._settings.shadow_enabled or self._candidate_source is None:
            return False
        try:
            resolved = self._candidate_source.resolve()
            loaded = load_classifier(
                resolved.directory,
                version=resolved.version,
                alias=resolved.alias,
                expected_name=self._settings.classifier_model_name,
            )
        except ModelLoadError:
            with self._lock:
                self.candidate = None
            record_shadow_loaded(self._settings.classifier_model_name, None)
            return False
        with self._lock:
            self.candidate = loaded
        record_shadow_loaded(loaded.name, loaded.version)
        return True

    def refresh_candidate(self) -> bool:
        """Poll step for the candidate alias; True when a different version was loaded."""
        if not self._settings.shadow_enabled or self._candidate_source is None:
            return False
        current = self.candidate
        try:
            latest = self._candidate_source.current_version()
        except ModelLoadError:
            if current is None:
                return False
            with self._lock:  # the alias was removed (for example after a promotion)
                self.candidate = None
            record_shadow_loaded(self._settings.classifier_model_name, None)
            return True
        if current is not None and current.version == latest:
            return False
        return self.load_candidate()

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
