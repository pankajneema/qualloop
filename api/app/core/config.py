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
    # Names the ACL user: redis://qualloop_app:<password>@host:6379/0 (INV-SEC-08, ADR-008).
    redis_url: str = "redis://localhost:6379/0"

    # Object storage (S3 API; SeaweedFS locally, ADR-020). Two private buckets (ADR-011).
    s3_endpoint_url: str = "http://localhost:8333"
    # Host that browsers use to reach the store when it differs from `s3_endpoint_url` (e.g. the compose-internal
    # name `s3`). Presigned URLs are signed for this host. Empty = use `s3_endpoint_url`.
    s3_public_endpoint_url: str = ""
    s3_region: str = "us-east-1"
    s3_access_key: str = "qualloop-dev"
    s3_secret_key: str = "change-me-local-only"  # noqa: S105 - dev placeholder
    s3_bucket_files: str = "qualloop-files"
    s3_bucket_quarantine: str = "qualloop-quarantine"

    smtp_host: str = "localhost"
    smtp_port: int = 1025
    mail_from: str = "QualLoop <no-reply@qualloop.in>"

    clamav_host: str = "localhost"
    clamav_port: int = 3310

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
