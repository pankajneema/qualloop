"""ADR-008 amendment (A-122): `QL_REDIS_WORKER_URL` is optional and defaults to `QL_REDIS_URL`."""

import pytest

from app.core.config import Settings


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    import os

    for name in [n for n in os.environ if n.startswith("QL_")]:
        monkeypatch.delenv(name)
    monkeypatch.setenv("QL_ENV", "local")
    return monkeypatch


def test_the_worker_redis_url_defaults_to_the_app_redis_url(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("QL_REDIS_URL", "redis://qualloop_app:pw@redis:6379/0")
    settings = Settings()
    assert (
        settings.model_dump()["redis_worker_url"]
        == settings.redis_url
        == "redis://qualloop_app:pw@redis:6379/0"
    )


def test_the_worker_redis_url_can_name_its_own_user(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("QL_REDIS_URL", "redis://qualloop_app:pw@redis:6379/0")
    clean_env.setenv("QL_REDIS_WORKER_URL", "redis://qualloop_worker:wpw@redis:6379/0")
    settings = Settings()
    assert settings.model_dump()["redis_worker_url"] == "redis://qualloop_worker:wpw@redis:6379/0"
    assert settings.redis_url == "redis://qualloop_app:pw@redis:6379/0", "the app URL is unchanged"
