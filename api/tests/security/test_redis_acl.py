"""INV-SEC-08 (D-5): Redis requires AUTH with a least-privilege ACL user; admin/dangerous commands are denied.

The app user comes from QL_REDIS_URL. Destructive commands are only attempted after proving, via ACL WHOAMI,
that we are connected as the restricted user, so a misconfigured open Redis is never flushed by this test."""

from typing import Any
from urllib.parse import urlsplit

import pytest
import redis as redis_lib
from redis.exceptions import AuthenticationError, NoPermissionError, ResponseError

from app.core.config import Settings
from tests.factories.env import with_redis_db, worker_redis_url

pytestmark = pytest.mark.integration


def run(client: redis_lib.Redis, *args: str) -> Any:
    return client.execute_command(*args)  # type: ignore[no-untyped-call]


@pytest.fixture
def app_redis(settings: Settings) -> redis_lib.Redis:
    return redis_lib.Redis.from_url(with_redis_db(settings.redis_url), decode_responses=True)


def test_the_app_connects_as_the_named_restricted_user_not_default(
    settings: Settings, app_redis: redis_lib.Redis
) -> None:
    assert urlsplit(settings.redis_url).username == "qualloop_app", (
        "QL_REDIS_URL must name the ACL user"
    )
    assert urlsplit(settings.redis_url).password, "QL_REDIS_URL must carry the ACL user's password"
    assert app_redis.ping() is True


def test_redis_requires_authentication(settings: Settings) -> None:
    parts = urlsplit(settings.redis_url)
    # protocol=2: redis-py 8 defaults to RESP3 and would fail at HELLO before the server's NOAUTH reply.
    anonymous = redis_lib.Redis(
        host=parts.hostname or "localhost", port=parts.port or 6379, protocol=2
    )
    with pytest.raises(AuthenticationError, match=r"NOAUTH|Authentication required"):
        anonymous.ping()


def test_the_default_user_is_disabled(settings: Settings) -> None:
    parts = urlsplit(settings.redis_url)
    client = redis_lib.Redis(
        host=parts.hostname or "localhost",
        port=parts.port or 6379,
        username="default",
        password="nopass",
    )
    with pytest.raises((AuthenticationError, ResponseError)):
        client.ping()


def test_wrong_password_for_the_app_user_is_rejected(
    settings: Settings, app_redis: redis_lib.Redis
) -> None:
    parts = urlsplit(settings.redis_url)
    assert parts.username == "qualloop_app" and parts.password, (
        "QL_REDIS_URL must carry the ACL credentials"
    )
    assert (
        app_redis.ping() is True
    )  # the right credentials work; only the wrong ones below must fail
    client = redis_lib.Redis(
        host=parts.hostname or "localhost",
        port=parts.port or 6379,
        username="qualloop_app",
        password="definitely-not-the-password",
    )
    with pytest.raises((AuthenticationError, ResponseError)):
        client.ping()


def test_redis_app_user_cannot_run_admin_commands(
    settings: Settings, app_redis: redis_lib.Redis
) -> None:
    # Guard: never attempt FLUSHALL/SHUTDOWN unless authenticated as the restricted user (not an open Redis).
    assert urlsplit(settings.redis_url).username == "qualloop_app", (
        "not the restricted user; refusing"
    )
    assert app_redis.ping() is True
    for command in (
        ("FLUSHALL",),
        ("FLUSHDB",),
        ("KEYS", "*"),
        ("CONFIG", "GET", "*"),
        ("CONFIG", "SET", "appendonly", "no"),
        ("SHUTDOWN", "NOSAVE"),
        ("DEBUG", "SLEEP", "0"),
        ("ACL", "LIST"),
        ("SAVE",),
        ("CLIENT", "KILL", "TYPE", "normal"),
        ("MONITOR",),
    ):
        if command[0] == "DEBUG":
            # Redis ships with DEBUG disabled and refuses it before the ACL check; either refusal is a denial.
            with pytest.raises(ResponseError, match=r"NOPERM|permission|DEBUG command not allowed"):
                run(app_redis, *command)
            continue
        with pytest.raises(NoPermissionError, match=r"NOPERM|permission"):
            run(app_redis, *command)


@pytest.mark.parametrize(
    "key",
    [
        "sess:abc",
        "user_sessions:u1",
        "otp:x",
        "rl:login:x",
        "idem:x",
        "sched:leader",
        "dramatiq:default",
    ],
)
def test_app_user_can_use_the_documented_key_patterns(app_redis: redis_lib.Redis, key: str) -> None:
    app_redis.set(key, "1", ex=30)
    assert app_redis.get(key) == "1"
    app_redis.delete(key)


@pytest.mark.parametrize("key", ["other:key", "zz_unlisted", "admin:secret", "config"])
def test_app_user_cannot_touch_keys_outside_the_documented_patterns(
    app_redis: redis_lib.Redis, key: str
) -> None:
    with pytest.raises(NoPermissionError, match=r"NOPERM|permission"):
        app_redis.set(key, "1")


# --- ADR-008 amendment (A-122): `qualloop_worker`, used only by Dramatiq consumers -------------------------------
@pytest.fixture
def worker_redis() -> redis_lib.Redis:
    return redis_lib.Redis.from_url(worker_redis_url(), decode_responses=True)


def test_the_worker_connects_as_the_named_worker_user_not_the_app_user(
    worker_redis: redis_lib.Redis,
) -> None:
    assert urlsplit(worker_redis_url()).username == "qualloop_worker"
    assert run(worker_redis, "ACL", "WHOAMI") == "qualloop_worker"


@pytest.mark.parametrize("pattern", ["dramatiq:*", "sess:*", "rl:*", "otp:*"])
def test_the_worker_user_can_run_keys_on_the_allowed_patterns(
    worker_redis: redis_lib.Redis, pattern: str
) -> None:
    key = pattern.replace("*", "keys-probe")
    worker_redis.set(key, "1", ex=30)
    try:
        assert key in worker_redis.keys(pattern)
    finally:
        worker_redis.delete(key)


def test_the_app_user_still_cannot_run_keys(app_redis: redis_lib.Redis) -> None:
    assert run(app_redis, "ACL", "WHOAMI") == "qualloop_app"
    with pytest.raises(NoPermissionError, match=r"NOPERM|permission"):
        app_redis.keys("dramatiq:*")


@pytest.mark.parametrize(
    "command",
    [
        ("FLUSHALL",),
        ("FLUSHDB",),
        ("CONFIG", "GET", "*"),
        ("CONFIG", "SET", "appendonly", "no"),
        ("ACL", "LIST"),
        ("ACL", "SETUSER", "qualloop_worker", "on"),
        ("FUNCTION", "LIST"),
        ("FUNCTION", "FLUSH"),
        ("SCRIPT", "FLUSH"),
        ("SCRIPT", "KILL"),
        ("SHUTDOWN", "NOSAVE"),
        ("SAVE",),
        ("CLIENT", "KILL", "TYPE", "normal"),
        ("MONITOR",),
    ],
    ids=lambda command: "-".join(command),
)
def test_the_worker_user_is_still_denied_admin_and_dangerous_commands(
    worker_redis: redis_lib.Redis, command: tuple[str, ...]
) -> None:
    # Guard: never attempt destructive commands unless authenticated as the restricted worker user.
    assert run(worker_redis, "ACL", "WHOAMI") == "qualloop_worker", "not the worker user; refusing"
    with pytest.raises(NoPermissionError, match=r"NOPERM|permission"):
        run(worker_redis, *command)


@pytest.mark.parametrize("key", ["other:key", "zz_unlisted", "admin:secret", "config"])
def test_the_worker_user_cannot_touch_keys_outside_the_documented_patterns(
    worker_redis: redis_lib.Redis, key: str
) -> None:
    with pytest.raises(NoPermissionError, match=r"NOPERM|permission"):
        worker_redis.set(key, "1")
    with pytest.raises(NoPermissionError, match=r"NOPERM|permission"):
        worker_redis.get(key)


@pytest.mark.parametrize(
    "key",
    [
        "sess:abc",
        "user_sessions:u1",
        "otp:x",
        "rl:login:x",
        "idem:x",
        "sched:leader",
        "dramatiq:default",
    ],
)
def test_the_worker_user_can_use_the_documented_key_patterns(
    worker_redis: redis_lib.Redis, key: str
) -> None:
    worker_redis.set(key, "1", ex=30)
    assert worker_redis.get(key) == "1"
    worker_redis.delete(key)


def test_the_worker_user_requires_its_own_password(
    settings: Settings, worker_redis: redis_lib.Redis
) -> None:
    assert (
        worker_redis.ping() is True
    )  # the right credentials work; only the wrong ones below must fail
    parts = urlsplit(worker_redis_url())
    client = redis_lib.Redis(
        host=parts.hostname or "localhost",
        port=parts.port or 6379,
        username="qualloop_worker",
        password="definitely-not-the-password",
    )
    with pytest.raises((AuthenticationError, ResponseError)):
        client.ping()


def test_the_app_password_does_not_open_the_worker_user(
    settings: Settings, worker_redis: redis_lib.Redis
) -> None:
    assert worker_redis.ping() is True
    app = urlsplit(settings.redis_url)
    worker = urlsplit(worker_redis_url())
    assert app.password and app.password != worker.password, "worker needs a password of its own"
    client = redis_lib.Redis(
        host=worker.hostname or "localhost",
        port=worker.port or 6379,
        username="qualloop_worker",
        password=app.password,
    )
    with pytest.raises((AuthenticationError, ResponseError)):
        client.ping()
