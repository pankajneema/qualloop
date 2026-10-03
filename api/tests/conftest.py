"""Shared fixtures. Integration tests use the real Postgres/Redis from compose or CI services (no SQLite).

Test DB URLs come from QL_TEST_DATABASE_URL (app role) and QL_TEST_DATABASE_URL_OWNER (owner role);
QL_REDIS_URL points at Redis. Defaults target localhost:5432 / 6379.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine

from alembic import command
from app.core.config import Settings, get_settings
from app.core.db import get_engine

API_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings()


def alembic_config(owner_url: str) -> Config:
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", owner_url.replace("%", "%%"))
    return cfg


@pytest.fixture(scope="session")
def migrated_db(settings: Settings) -> Iterator[None]:
    """Test database at alembic head."""
    command.upgrade(alembic_config(settings.test_database_url_owner), "head")
    yield


@pytest.fixture(scope="session")
def owner_engine(settings: Settings, migrated_db: None) -> Iterator[Engine]:
    engine = create_engine(settings.test_database_url_owner, isolation_level="AUTOCOMMIT")
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def app_engine(settings: Settings, migrated_db: None) -> Iterator[Engine]:
    engine = create_engine(settings.test_database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def client(
    settings: Settings, migrated_db: None, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """App wired to the test database (as the app role)."""
    from app.main import create_app

    monkeypatch.setenv("QL_DATABASE_URL", settings.test_database_url)
    get_settings.cache_clear()
    get_engine.cache_clear()
    with TestClient(create_app()) as c:
        yield c
    get_engine().dispose()
    get_settings.cache_clear()
    get_engine.cache_clear()
