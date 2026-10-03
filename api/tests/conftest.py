"""Shared fixtures. Integration tests use the real Postgres/Redis from compose or CI services (no SQLite).

Test DB URLs come from QL_TEST_DATABASE_URL (app role) and QL_TEST_DATABASE_URL_OWNER (owner role);
QL_REDIS_URL points at Redis. Defaults target localhost:5432 / 6379.
"""

import os
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import pytest
import redis as redis_lib
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, event, text

from alembic import command
from app.core.config import Settings, get_settings
from app.core.db import get_engine
from tests.factories import db as dbf
from tests.factories import mail as mailf
from tests.factories.api import ApiFactory
from tests.factories.env import owner_url, with_redis_db

API_ROOT = Path(__file__).resolve().parents[1]

# Redis key families the app user may touch (ADR-008). Tests clean exactly these, never FLUSHDB.
REDIS_KEY_PATTERNS = (
    "sess:*",
    "user_sessions:*",
    "otp:*",
    "rl:*",
    "idem:*",
    "sched:*",
    "dramatiq:*",
)


# Fixed advisory-lock key ("QLTE") that serialises whole pytest runs against the shared qualloop_test database and
# Redis db 15: two concurrent runs would otherwise delete each other's rows/keys and drain each other's queues.
RUN_LOCK_KEY = 0x514C5445
RUN_LOCK_WAIT_SECONDS = 20 * 60


@pytest.fixture(scope="session")
def _exclusive_run() -> Iterator[None]:
    """Hold a session-level `pg_advisory_lock` (owner role, dedicated connection) for the whole run.

    A second run waits here (polling `pg_try_advisory_lock`) instead of interfering. If Postgres is not reachable
    there is nothing shared to protect (unit-only runs), so the run proceeds without the lock."""
    import psycopg

    url = owner_url().replace("postgresql+psycopg://", "postgresql://", 1)
    try:
        conn = psycopg.connect(url, autocommit=True, connect_timeout=5)
    except psycopg.OperationalError:
        yield
        return
    try:
        deadline = time.monotonic() + RUN_LOCK_WAIT_SECONDS
        while not conn.execute("SELECT pg_try_advisory_lock(%s)", (RUN_LOCK_KEY,)).fetchone()[0]:  # type: ignore[index]
            if time.monotonic() > deadline:
                pytest.exit(
                    "another pytest run held the shared test database lock for 20 minutes", 3
                )
            time.sleep(1.0)
        yield
        conn.execute("SELECT pg_advisory_unlock(%s)", (RUN_LOCK_KEY,))
    finally:
        conn.close()


@pytest.fixture(scope="session", autouse=True)
def _test_env(_exclusive_run: None) -> Iterator[None]:
    """Point every in-process component (app, worker, dispatcher) at the TEST database and Redis db 15.

    Without this a bare `pytest` would run the app against the dev database (RLS data leaks between dev and
    tests) and the in-process Dramatiq worker would race the dev stack's worker on Redis db 0."""
    base = Settings()
    os.environ["QL_DATABASE_URL"] = base.test_database_url
    os.environ["QL_DATABASE_URL_OWNER"] = (
        owner_url()
    )  # read by alembic/env.py only, never by the runtime
    os.environ["QL_REDIS_URL"] = with_redis_db(base.redis_url)
    for name, default in (
        ("QL_SMTP_HOST", "localhost"),
        ("QL_SMTP_PORT", "1025"),
        ("QL_S3_ENDPOINT_URL", "http://localhost:8333"),
        ("QL_S3_ACCESS_KEY", "qualloop-dev"),
        ("QL_S3_SECRET_KEY", "change-me-local-only"),
        ("QL_S3_BUCKET_FILES", "qualloop-files"),
        ("QL_S3_BUCKET_QUARANTINE", "qualloop-quarantine"),
        ("QL_CLAMAV_HOST", "localhost"),
        ("QL_CLAMAV_PORT", "3310"),
    ):
        os.environ.setdefault(name, default)
    get_settings.cache_clear()
    get_engine.cache_clear()
    yield


@pytest.fixture(scope="session")
def settings(_test_env: None) -> Settings:
    return Settings()


def alembic_config(owner_url: str) -> Config:
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", owner_url.replace("%", "%%"))
    return cfg


@pytest.fixture(scope="session")
def migrated_db(settings: Settings) -> Iterator[None]:
    """Test database at alembic head."""
    command.upgrade(alembic_config(owner_url()), "head")
    yield


def _role_guard(expected: str) -> Callable[[Any, Any], None]:
    """Pool `connect` listener: every new connection must be the expected, RLS-bound role.

    A superuser or BYPASSRLS connection would silently skip row-level security (ADR-004), turning every
    isolation test into a false pass."""

    def check(dbapi_connection: Any, _record: Any) -> None:
        with dbapi_connection.cursor() as cur:
            cur.execute(
                "SELECT current_user, r.rolsuper, r.rolbypassrls FROM pg_roles r "
                "WHERE r.rolname = current_user"
            )
            user, superuser, bypass = cur.fetchone()
        dbapi_connection.rollback()
        if user != expected or superuser or bypass:
            raise RuntimeError(
                f"test DB guard: connected as {user!r} (super={superuser}, bypassrls={bypass}); "
                f"expected non-bypass role {expected!r}"
            )

    return check


@pytest.fixture(scope="session")
def owner_engine(settings: Settings, migrated_db: None) -> Iterator[Engine]:
    engine = create_engine(owner_url(), isolation_level="AUTOCOMMIT")
    event.listen(engine, "connect", _role_guard("qualloop_owner"))
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def app_engine(settings: Settings, migrated_db: None) -> Iterator[Engine]:
    engine = create_engine(settings.test_database_url)
    event.listen(engine, "connect", _role_guard("qualloop_app"))
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


# --------------------------------------------------------------------------------------------------
# P01 fixtures
# --------------------------------------------------------------------------------------------------
@pytest.fixture
def engine_env(migrated_db: None) -> Iterator[None]:
    """Fresh settings/engine caches so core code (tenant_tx, dispatcher, worker) uses the test DB."""
    get_settings.cache_clear()
    get_engine.cache_clear()
    yield
    if get_engine.cache_info().currsize:
        get_engine().dispose()
    get_settings.cache_clear()
    get_engine.cache_clear()


@pytest.fixture
def redis_client(settings: Settings) -> Iterator[redis_lib.Redis]:
    client: redis_lib.Redis = redis_lib.Redis.from_url(
        with_redis_db(settings.redis_url), decode_responses=True
    )
    _clean_redis(client)
    yield client
    _clean_redis(client)
    client.close()


def _clean_redis(client: redis_lib.Redis) -> None:
    for pattern in REDIS_KEY_PATTERNS:
        for key in client.scan_iter(match=pattern, count=500):
            client.delete(key)


@pytest.fixture
def api(
    settings: Settings, engine_env: None, redis_client: redis_lib.Redis
) -> Iterator[ApiFactory]:
    """The real app, wired to the test DB and Redis db 15. Each `.anonymous()` is a separate browser."""
    from app.main import create_app

    with ExitStack() as stack:
        yield ApiFactory(create_app(), stack)


@pytest.fixture
def seeded(app_engine: Engine) -> dbf.SeededTenant:
    return dbf.seed_tenant(app_engine)


@pytest.fixture
def seeded_pair(app_engine: Engine) -> tuple[dbf.SeededTenant, dbf.SeededTenant]:
    return dbf.seed_tenant(app_engine), dbf.seed_tenant(app_engine)


@pytest.fixture
def mailbox() -> Iterator[None]:
    mailf.clear()
    yield
    mailf.clear()


@pytest.fixture
def clean_outbox(app_engine: Engine, engine_env: None) -> None:
    dbf.drain_outbox(app_engine)


def assert_current_user(engine: Engine, expected: str = "qualloop_app") -> None:
    with engine.connect() as conn:
        assert conn.execute(text("SELECT current_user")).scalar_one() == expected


# --------------------------------------------------------------------------------------------------
# Background threads: in-process Dramatiq workers must never outlive their test (a leaked non-daemon thread keeps
# the pytest process alive after the run, and a leaked consumer keeps taking jobs from the shared Redis db 15).
# --------------------------------------------------------------------------------------------------
_STARTED_WORKERS: list[Any] = []


@pytest.fixture(scope="session", autouse=True)
def _track_dramatiq_workers() -> Iterator[None]:
    """Record every `dramatiq.Worker` started in this process so a finaliser can stop the ones a test left running."""
    import dramatiq

    original_start, original_stop = dramatiq.Worker.start, dramatiq.Worker.stop

    def start(self: Any) -> None:
        _STARTED_WORKERS.append(self)
        original_start(self)

    def stop(self: Any, *args: Any, **kwargs: Any) -> None:
        if self in _STARTED_WORKERS:
            _STARTED_WORKERS.remove(self)
        original_stop(self, *args, **kwargs)

    dramatiq.Worker.start = start  # type: ignore[method-assign]
    dramatiq.Worker.stop = stop  # type: ignore[method-assign]
    yield
    _stop_started_workers()
    dramatiq.Worker.start, dramatiq.Worker.stop = original_start, original_stop  # type: ignore[method-assign]


def _stop_started_workers() -> None:
    for worker in list(_STARTED_WORKERS):  # `stop` removes the worker from the list
        try:
            worker.stop()
        except Exception:  # best effort: shutdown must not fail an unrelated test
            _STARTED_WORKERS.clear()


@pytest.fixture(autouse=True)
def _stop_leaked_threads() -> Iterator[None]:
    """After every test: stop any Dramatiq worker it started and left running, and wait briefly for helper
    threads (dispatcher loop, scheduler) that the test forgot to join, so none keeps running into the next test."""
    before = set(threading.enumerate())
    yield
    _stop_started_workers()
    for thread in set(threading.enumerate()) - before:
        if thread.is_alive() and not thread.daemon and thread is not threading.current_thread():
            thread.join(timeout=5)
