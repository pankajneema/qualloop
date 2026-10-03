"""ADR-006 item 1: one scheduler leader (Redis SET NX, TTL 30 s); the scheduler only fans out and enqueues."""

import threading
from typing import Any
from uuid import uuid4

import pytest
import redis as redis_lib
from sqlalchemy import Engine

from tests.factories.contract import load
from tests.factories.db import create_tenant

pytestmark = pytest.mark.integration

KEY = "sched:leader"


def mod() -> Any:
    return load("app.scheduler")


def test_first_instance_becomes_leader_and_second_does_not(redis_client: redis_lib.Redis) -> None:
    assert mod().acquire_leader(redis_client, "scheduler-a") is True
    assert mod().acquire_leader(redis_client, "scheduler-b") is False
    assert redis_client.get(KEY) == "scheduler-a"


def test_leader_lock_has_a_thirty_second_ttl(redis_client: redis_lib.Redis) -> None:
    mod().acquire_leader(redis_client, "scheduler-a")
    assert 0 < redis_client.ttl(KEY) <= 30


def test_leader_renews_its_own_lock_and_non_leaders_cannot_renew_it(
    redis_client: redis_lib.Redis,
) -> None:
    mod().acquire_leader(redis_client, "scheduler-a")
    redis_client.expire(KEY, 5)
    assert mod().renew_leader(redis_client, "scheduler-a") is True
    assert redis_client.ttl(KEY) > 25
    redis_client.expire(KEY, 5)
    assert mod().renew_leader(redis_client, "scheduler-b") is False
    assert redis_client.ttl(KEY) <= 5, "a non-leader must not extend the lock"
    assert redis_client.get(KEY) == "scheduler-a"


def test_release_only_works_for_the_owner(redis_client: redis_lib.Redis) -> None:
    mod().acquire_leader(redis_client, "scheduler-a")
    mod().release_leader(redis_client, "scheduler-b")
    assert redis_client.get(KEY) == "scheduler-a"
    mod().release_leader(redis_client, "scheduler-a")
    assert redis_client.get(KEY) is None
    assert mod().acquire_leader(redis_client, "scheduler-b") is True


def test_expired_lock_can_be_taken_over(redis_client: redis_lib.Redis) -> None:
    mod().acquire_leader(redis_client, "scheduler-a")
    redis_client.pexpire(KEY, 50)
    gone = threading.Event()
    while redis_client.exists(KEY):
        gone.wait(0.02)
    assert mod().acquire_leader(redis_client, "scheduler-b") is True


def test_fan_out_calls_send_once_for_every_active_tenant(
    app_engine: Engine, engine_env: None
) -> None:
    a, b = create_tenant(app_engine), create_tenant(app_engine)
    sent: list[Any] = []
    count = mod().fan_out(sent.append)
    assert sent.count(a) == 1 and sent.count(b) == 1
    assert count == len(sent) >= 2


def test_only_the_leader_runs_ticks_and_leadership_passes_on_clean_stop(
    redis_client: redis_lib.Redis,
) -> None:
    run = mod().run
    ticks = {"a": 0, "b": 0}
    a_ticked, b_ticked = threading.Event(), threading.Event()
    stop_a, stop_b = threading.Event(), threading.Event()

    def tick(name: str, seen: threading.Event) -> Any:
        def on_tick() -> None:
            ticks[name] += 1
            if ticks[name] >= 2:
                seen.set()

        return on_tick

    kw: dict[str, Any] = {"tick": 0.02, "redis": redis_client}
    ta = threading.Thread(
        target=run,
        args=(stop_a,),
        kwargs={**kw, "instance_id": "a", "on_leader_tick": tick("a", a_ticked)},
    )
    tb = threading.Thread(
        target=run,
        args=(stop_b,),
        kwargs={**kw, "instance_id": f"b-{uuid4()}", "on_leader_tick": tick("b", b_ticked)},
    )
    ta.start()
    try:
        assert a_ticked.wait(15), "the first instance never became leader"
        tb.start()
        assert not b_ticked.wait(0.5), "a second scheduler must not tick while the first is leader"
        assert ticks["b"] == 0
    finally:
        stop_a.set()
        ta.join(30)
    try:
        assert b_ticked.wait(15), (
            "leadership did not pass to the second instance after a clean stop"
        )
    finally:
        stop_b.set()
        if tb.is_alive():
            tb.join(30)
