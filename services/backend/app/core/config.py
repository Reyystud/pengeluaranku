"""Application settings from environment variables (PRD 19.4). Parsed once, validated at startup."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, field_validator
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

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def service_name(self) -> str:
        return "worker" if self.role == "worker" else "backend"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
