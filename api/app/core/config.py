"""Typed settings from environment (prefix QL_). Secrets come from env only, never from the repo."""

from functools import lru_cache
from typing import Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="QL_", extra="ignore")

    env: str = "local"
    log_level: str = "INFO"
    version: str = Field(default="dev", description="git sha, injected at image build")

    database_url: str = "postgresql+psycopg://qualloop_app:qualloop_app@localhost:5432/qualloop"
    database_url_owner: str = (
        "postgresql+psycopg://qualloop_owner:qualloop_owner@localhost:5432/qualloop"
    )
    test_database_url: str = (
        "postgresql+psycopg://qualloop_app:qualloop_app@localhost:5432/qualloop_test"
    )
    test_database_url_owner: str = (
        "postgresql+psycopg://qualloop_owner:qualloop_owner@localhost:5432/qualloop_test"
    )
    redis_url: str = "redis://localhost:6379/0"

    session_secret: str = "change-me-32-bytes-min"  # noqa: S105 - dev placeholder, rejected outside local
    hmac_secret: str = "change-me-32-bytes-min"  # noqa: S105

    public_base_url: str = "http://localhost:3000"
    otel_exporter_otlp_endpoint: str = ""

    @model_validator(mode="after")
    def _reject_defaults_outside_local(self) -> Self:
        """Fail fast at startup: non-local environments must not run on dev placeholders."""
        if self.env == "local":
            return self
        defaults = Settings.model_fields
        problems = [
            name
            for name in ("database_url", "database_url_owner", "session_secret", "hmac_secret")
            if getattr(self, name) == defaults[name].default
        ]
        problems += [
            name
            for name in ("session_secret", "hmac_secret")
            if len(getattr(self, name)) < 32 and name not in problems
        ]
        if problems:
            raise ValueError(f"QL_ENV={self.env}: unsafe default/weak settings: {sorted(problems)}")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
