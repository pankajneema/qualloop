"""INV-SEC-08 (D-5): Redis requires AUTH with a least-privilege ACL user; admin/dangerous commands are denied.

The app user comes from QL_REDIS_URL. Destructive commands are only attempted after proving, via ACL WHOAMI,
that we are connected as the restricted user, so a misconfigured open Redis is never flushed by this test."""

from typing import Any
from urllib.parse import urlsplit

import pytest
import redis as redis_lib
from redis.exceptions import AuthenticationError, NoPermissionError, ResponseError

from app.core.config import Settings
from tests.factories.env import with_redis_db

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
    anonymous = redis_lib.Redis(host=parts.hostname or "localhost", port=parts.port or 6379)
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
