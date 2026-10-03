"""P01 contract item 3 (security review): a session deleted while `load_session` is between its read and its
refresh must stay deleted. Deterministic: the delete is injected right after the session record was read."""

from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import pytest
import redis as redis_lib

from tests.factories.contract import load
from tests.factories.redis_chaos import ChaosRedis, key_command
from tests.integration.auth.helpers import session_key

pytestmark = pytest.mark.integration


def sessions_module() -> Any:
    return load("app.core.auth.sessions")


def make_session(client: redis_lib.Redis) -> tuple[str, UUID, UUID]:
    sessions = sessions_module()
    user_id, tenant_id = uuid4(), uuid4()
    token, _data = sessions.create_session(
        client, user_id=user_id, tenant_id=tenant_id, ip="203.0.113.9", user_agent="pytest"
    )
    return token, user_id, tenant_id


def run_with_delete_after_read(
    redis_client: redis_lib.Redis, token: str, delete: Callable[[ChaosRedis], None]
) -> tuple[Any, ChaosRedis]:
    """`load_session` on a client that runs `delete` right after the first read of the session key."""
    chaos = ChaosRedis.sharing(redis_client)
    chaos.arm(
        key_command(session_key(token), "GET", "GETEX", "EVAL", "EVALSHA", "WATCH"),
        lambda: delete(chaos),
    )
    return sessions_module().load_session(chaos, token), chaos


def test_load_session_does_not_resurrect_a_session_deleted_between_its_read_and_its_refresh(
    redis_client: redis_lib.Redis,
) -> None:
    sessions = sessions_module()
    token, user_id, _ = make_session(redis_client)

    def delete(_: ChaosRedis) -> None:
        sessions.delete_session(redis_client, token, user_id)

    result, chaos = run_with_delete_after_read(redis_client, token, delete)
    assert chaos.fired_by is not None, (
        "the injected delete never ran: load_session did not read the key"
    )
    if (
        chaos.fired_by == "GET"
    ):  # a plain read-then-write implementation: the session is gone by now
        assert result is None
    assert redis_client.exists(session_key(token)) == 0, "the deleted session was written back"
    assert (
        redis_client.sismember(f"user_sessions:{user_id}", session_key(token).removeprefix("sess:"))
        == 0
    )
    assert sessions.load_session(redis_client, token) is None


def test_load_session_does_not_resurrect_a_session_ended_by_delete_user_sessions(
    redis_client: redis_lib.Redis,
) -> None:
    """Deactivation / password reset end every session of a user; a concurrent request must not undo that."""
    sessions = sessions_module()
    token, user_id, _ = make_session(redis_client)
    other_token, _, _ = make_session(redis_client)

    def delete(_: ChaosRedis) -> None:
        assert sessions.delete_user_sessions(redis_client, user_id) == 1

    result, chaos = run_with_delete_after_read(redis_client, token, delete)
    assert chaos.fired_by is not None
    if chaos.fired_by == "GET":
        assert result is None
    assert redis_client.exists(session_key(token)) == 0, (
        "a deactivated user's session came back to life"
    )
    assert redis_client.exists(session_key(other_token)) == 1, (
        "another user's session is not affected"
    )
    assert sessions.load_session(redis_client, token) is None


def test_load_session_still_slides_the_idle_window_for_a_live_session(
    redis_client: redis_lib.Redis,
) -> None:
    """Control: the fix must not stop the sliding refresh (record `last_seen_at` and Redis TTL)."""
    sessions = sessions_module()
    token, _, _ = make_session(redis_client)
    key = session_key(token)
    redis_client.expire(key, 600)
    data = sessions.load_session(redis_client, token)
    assert data is not None
    assert redis_client.ttl(key) > 600, "TTL must be extended back towards the 8 hour idle window"
