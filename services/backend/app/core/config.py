"""Application settings from environment variables (PRD 19.4). Parsed once, validated at startup."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_JWT_SECRET_BYTES = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_env: Literal["local", "ci", "demo"] = "local"
    role: Literal["api", "worker"] = "api"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000"
    database_url: str | None = None
    jwt_secret: SecretStr | None = None
    cursor_signing_key: SecretStr = SecretStr("dev-only-cursor-signing-key")
    export_pseudonym_key: SecretStr = SecretStr("dev-only-pseudonym-key")
    max_transaction_amount: int = 1_000_000_000
    access_token_ttl_s: int = 900
    refresh_token_ttl_s: int = 2_592_000
    cookie_secure: bool = True
    # ML service (PRD 6.3, 6.4). An empty URL disables the client: every categorization then falls
    # back to needs_review without a network call.
    ml_service_url: str = ""
    ml_timeout_ms: int = 300
    ml_batch_timeout_ms: int = 3000
    ml_auth: Literal["none"] = "none"
    ml_circuit_failures: int = 5
    ml_circuit_open_s: float = 30.0
    # Events (PRD 7.11, 14.3). ``inmemory`` drains the outbox in-process after each write;
    # ``pubsub`` leaves it to the relay in the worker, which publishes to Pub/Sub (or to the
    # emulator when PUBSUB_EMULATOR_HOST is set) and the worker's push endpoint consumes.
    event_bus: Literal["inmemory", "pubsub"] = "inmemory"
    pubsub_project_id: str = ""
    pubsub_topic: str = "transaction-events"
    pubsub_emulator_host: str = ""
    relay_interval_s: float = 1.0
    relay_batch_size: int = 100
    # Internal endpoints (PRD 17.1): Google OIDC token with this audience, from one of these
    # service accounts (comma separated). Empty audience disables the check (local and CI only).
    internal_oidc_audience: str = ""
    internal_allowed_sa: str = ""
    # Used by categorize-preview when the draft has no amount yet (the model needs one).
    preview_default_amount: int = 25_000

    @field_validator("jwt_secret")
    @classmethod
    def _jwt_secret_long_enough(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and len(value.get_secret_value().encode()) < MIN_JWT_SECRET_BYTES:
            raise ValueError(f"JWT_SECRET must be at least {MIN_JWT_SECRET_BYTES} bytes")
        return value

    @field_validator("log_level")
    @classmethod
    def _log_level_known(cls, value: str) -> str:
        level = value.upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"unknown LOG_LEVEL {value!r}")
        return level

    @model_validator(mode="after")
    def _events_and_internal_auth_are_configured(self) -> Settings:
        if self.event_bus == "pubsub" and not self.pubsub_project_id:
            raise ValueError("PUBSUB_PROJECT_ID is required when EVENT_BUS=pubsub")
        if self.role == "worker" and self.app_env == "demo":
            if not self.internal_oidc_audience or not self.allowed_service_accounts:
                raise ValueError(
                    "INTERNAL_OIDC_AUDIENCE and INTERNAL_ALLOWED_SA are required for the worker"
                )
        return self

    @property
    def allowed_service_accounts(self) -> frozenset[str]:
        return frozenset(v.strip() for v in self.internal_allowed_sa.split(",") if v.strip())

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def service_name(self) -> str:
        return "worker" if self.role == "worker" else "backend"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
