"""P01 contract items 7 and 8 (security review): `QL_ENV` is mandatory and non-local environments refuse every dev
placeholder; the runtime settings never hold the migration owner credential (ADR-017, ADR-019)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings

API_ROOT = Path(__file__).resolve().parents[2]

OWNER_ENV = "QL_DATABASE_URL_OWNER"

ENV_NAMES = ("local", "ci", "staging", "production")
STRICT_ENVS = ("staging", "production")

# QL_DATABASE_URL_OWNER is part of the baseline only so that each rejection test below fails (today) for the one
# reason it names and not because the not-yet-removed owner placeholder trips the validator first. After item 8 the
# runtime ignores it; `test_settings_outside_local_do_not_require_an_owner_url` removes it.
SAFE = {
    "QL_DATABASE_URL_OWNER": "postgresql+psycopg://qualloop_owner:Zx9-owner-pw@db.internal:5432/qualloop",
    "QL_DATABASE_URL": "postgresql+psycopg://qualloop_app:Zx9-app-pw@db.internal:5432/qualloop",
    "QL_REDIS_URL": "redis://qualloop_app:Zx9-redis-pw@redis.internal:6379/0",
    "QL_S3_ACCESS_KEY": "AKIA-PROD-EXAMPLE-0001",
    "QL_S3_SECRET_KEY": "s3-secret-for-production-0000000000000001",
    "QL_SESSION_SECRET": "session-secret-0123456789-abcdefghijkl",
    "QL_HMAC_SECRET": "hmac-secret-9876543210-zyxwvutsrqpo",
}


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """No QL_* variable at all, so each test states exactly what it needs."""
    import os

    for name in [n for n in os.environ if n.startswith("QL_")]:
        monkeypatch.delenv(name)
    return monkeypatch


def safe_env(monkeypatch: pytest.MonkeyPatch, env: str, **override: str) -> None:
    for name, value in {**SAFE, "QL_ENV": env, **override}.items():
        monkeypatch.setenv(name, value)


# --- item 7 ----------------------------------------------------------------------------------------
def test_settings_without_ql_env_fails_instead_of_defaulting_to_local(
    clean_env: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValidationError) as excinfo:
        Settings()
    assert any(error["loc"] == ("env",) for error in excinfo.value.errors()), excinfo.value


def test_env_is_a_required_field_without_a_default() -> None:
    assert Settings.model_fields["env"].is_required()


@pytest.mark.parametrize("value", ["dev", "development", "prod", "test", "Local", "", "preprod"])
def test_an_unknown_ql_env_value_is_rejected(clean_env: pytest.MonkeyPatch, value: str) -> None:
    safe_env(clean_env, value)
    with pytest.raises(ValidationError) as excinfo:
        Settings()
    assert any(error["loc"] == ("env",) for error in excinfo.value.errors()), excinfo.value


@pytest.mark.parametrize("value", ENV_NAMES)
def test_each_documented_env_value_is_accepted_with_safe_settings(
    clean_env: pytest.MonkeyPatch, value: str
) -> None:
    safe_env(clean_env, value)
    assert Settings().env == value


def test_local_and_ci_keep_the_dev_placeholders_usable(clean_env: pytest.MonkeyPatch) -> None:
    for value in ("local", "ci"):
        clean_env.setenv("QL_ENV", value)
        clean_env.setenv("QL_SESSION_SECRET", "s" * 40)  # ci always needs real-length secrets
        clean_env.setenv("QL_HMAC_SECRET", "h" * 40)
        clean_env.setenv("QL_DATABASE_URL", SAFE["QL_DATABASE_URL"])
        clean_env.setenv(OWNER_ENV, SAFE[OWNER_ENV])
        assert Settings().env == value  # default s3 keys and default redis url are fine here


@pytest.mark.parametrize("env", STRICT_ENVS)
@pytest.mark.parametrize(
    ("variable", "dev_default", "field"),
    [
        ("QL_S3_ACCESS_KEY", "qualloop-dev", "s3_access_key"),
        ("QL_S3_SECRET_KEY", "change-me-local-only", "s3_secret_key"),
        ("QL_REDIS_URL", "redis://localhost:6379/0", "redis_url"),
    ],
    ids=["s3-access-key", "s3-secret-key", "redis-url"],
)
def test_outside_local_and_ci_a_default_placeholder_is_rejected(
    clean_env: pytest.MonkeyPatch, env: str, variable: str, dev_default: str, field: str
) -> None:
    safe_env(clean_env, env, **{variable: dev_default})
    with pytest.raises(ValidationError, match=field):
        Settings()


@pytest.mark.parametrize("env", STRICT_ENVS)
def test_outside_local_and_ci_the_s3_keys_may_not_be_left_unset(
    clean_env: pytest.MonkeyPatch, env: str
) -> None:
    safe_env(clean_env, env)
    clean_env.delenv("QL_S3_ACCESS_KEY")
    clean_env.delenv("QL_S3_SECRET_KEY")
    with pytest.raises(ValidationError, match="s3_"):
        Settings()


@pytest.mark.parametrize("env", STRICT_ENVS)
def test_outside_local_and_ci_session_secret_equal_to_hmac_secret_is_rejected(
    clean_env: pytest.MonkeyPatch, env: str
) -> None:
    same = "one-secret-used-twice-0123456789abcdef"
    safe_env(clean_env, env, QL_SESSION_SECRET=same, QL_HMAC_SECRET=same)
    with pytest.raises(ValidationError) as excinfo:
        Settings()
    message = str(excinfo.value)
    assert "session_secret" in message and "hmac_secret" in message


# --- item 8 ----------------------------------------------------------------------------------------
def test_runtime_settings_have_no_database_url_owner_field() -> None:
    assert "database_url_owner" not in Settings.model_fields


def test_the_owner_url_is_not_exposed_on_a_settings_instance_even_if_the_env_var_is_set(
    clean_env: pytest.MonkeyPatch,
) -> None:
    safe_env(clean_env, "production")
    clean_env.setenv(
        OWNER_ENV, "postgresql+psycopg://qualloop_owner:Owner-pw-1@db.internal/qualloop"
    )
    settings = Settings()
    assert not hasattr(settings, "database_url_owner")
    assert "Owner-pw-1" not in settings.model_dump_json()
    assert "Owner-pw-1" not in repr(settings)


@pytest.mark.parametrize("env", STRICT_ENVS)
def test_settings_outside_local_do_not_require_an_owner_url(
    clean_env: pytest.MonkeyPatch, env: str
) -> None:
    safe_env(clean_env, env)
    clean_env.delenv(OWNER_ENV, raising=False)
    assert Settings().env == env


def test_only_alembic_env_reads_the_owner_url_from_the_environment() -> None:
    """The migration job is the single reader of QL_DATABASE_URL_OWNER; application code never mentions it."""
    offenders = [
        str(path.relative_to(API_ROOT))
        for path in (API_ROOT / "app").rglob("*.py")
        if "database_url_owner" in path.read_text().lower()
    ]
    assert offenders == []
    assert OWNER_ENV in (API_ROOT / "alembic" / "env.py").read_text()
