"""ML service settings (PRD 19.4). Only variables this service reads."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["local", "ci", "staging", "production"] = "local"
    log_level: str = "INFO"
    ml_auth: Literal["none", "google_id_token"] = "none"
    model_source: Literal["mlflow", "local_dir"] = "mlflow"
    models_dir: Path = Path("models")
    # A specific run directory name under models/<model>/ (default: the newest).
    model_version: str | None = None
    mlflow_tracking_uri: str = "sqlite:///data/mlflow/mlflow.db"
    classifier_model_name: str = "transaction-classifier"
    classifier_alias: str = "production"
    # Shadow mode (PRD 16.4): the candidate answers nothing, its output is only logged.
    shadow_enabled: bool = False
    classifier_shadow_alias: str = "candidate"
    # Seconds between alias checks (PRD 11.5); 0 turns polling off.
    model_poll_interval_s: float = 300
    batch_max_items: int = 500
