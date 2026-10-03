"""Typed settings from environment (prefix QL_). Secrets come from env only, never from the repo."""

import ipaddress
from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="QL_", extra="ignore")

    # Required, no default: a forgotten QL_ENV must stop the process, not silently run as `local`.
    env: Literal["local", "ci", "staging", "production"]
    log_level: str = "INFO"
    version: str = Field(default="dev", description="git sha, injected at image build")

    database_url: str = "postgresql+psycopg://qualloop_app:qualloop_app@localhost:5432/qualloop"
    test_database_url: str = (
        "postgresql+psycopg://qualloop_app:qualloop_app@localhost:5432/qualloop_test"
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

    # SPEC-GAP: A-106 - CIDRs of the load balancers / reverse proxies whose X-Forwarded-For is believed (comma separated).
    # Empty (default): no proxy is trusted and the socket peer is the client.
    trusted_proxies: str = ""

    public_base_url: str = "http://localhost:3000"
    otel_exporter_otlp_endpoint: str = ""

    @model_validator(mode="after")
    def _check_trusted_proxies(self) -> Self:
        parse_cidrs(self.trusted_proxies)  # raises ValueError naming the bad entry
        return self

    @model_validator(mode="after")
    def _reject_defaults_outside_local(self) -> Self:
        """Fail fast at startup: staging and production must not run on dev placeholders."""
        if self.env in ("local", "ci"):
            return self
        defaults = Settings.model_fields
        problems = [
            name
            for name in (
                "database_url",
                "redis_url",
                "s3_access_key",
                "s3_secret_key",
                "session_secret",
                "hmac_secret",
            )
            if getattr(self, name) == defaults[name].default
        ]
        problems += [
            name
            for name in ("session_secret", "hmac_secret")
            if len(getattr(self, name)) < 32 and name not in problems
        ]
        if self.session_secret == self.hmac_secret:
            problems += [n for n in ("session_secret", "hmac_secret") if n not in problems]
        if problems:
            raise ValueError(f"QL_ENV={self.env}: unsafe default/weak settings: {sorted(problems)}")
        return self


def parse_cidrs(raw: str) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    """`10.0.0.0/8, 192.168.1.5` -> networks (a bare address is a /32 or /128). Blank entries are skipped."""
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for part in raw.split(","):
        entry = part.strip()
        if not entry:
            continue
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError as exc:
            raise ValueError(f"QL_TRUSTED_PROXIES: {entry!r} is not a CIDR or IP address") from exc
    return tuple(networks)


@lru_cache
def get_settings() -> Settings:
    return Settings()
