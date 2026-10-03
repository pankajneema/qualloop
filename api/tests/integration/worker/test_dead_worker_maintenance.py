"""ADR-008 amendment (A-122): Dramatiq's dispatch script runs `KEYS` while it requeues the messages of dead workers.

The app Redis user cannot run KEYS, so once any worker had died (its heartbeat stays listed) every consume loop of the
restarted worker failed with an ACL error and no job ran. Consumers therefore connect as `qualloop_worker`."""

import threading
import time
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
import redis as redis_lib
from sqlalchemy import Engine

from tests.factories.contract import load
from tests.factories.db import seed_tenant
from tests.factories.env import redis_url_as, with_redis_db, worker_redis_url
from tests.factories.jobs import make_actor, running_worker, unique_queue, wait_idle

pytestmark = pytest.mark.integration

DEAD_FOR_MS = 10 * 60 * 1000  # far beyond dramatiq's 60 s heartbeat timeout
NAMESPACE = "dramatiq"


def build(url: str) -> Any:
    broker = load("app.worker", "build_broker")(url)
    broker.maintenance_chance = 1_000_000  # every dispatch runs the dead-worker maintenance step
    return broker


@pytest.fixture
def worker_broker(engine_env: None, redis_client: redis_lib.Redis) -> Iterator[Any]:
    broker = build(worker_redis_url())
    yield broker
    broker.close()


def register_dead_worker(
    redis_client: redis_lib.Redis, queue: str, message: Any, worker_id: str
) -> None:
    """A worker that died while `message` was delivered to it but not acknowledged."""
    now_ms = int(time.time() * 1000)
    redis_client.zadd(f"{NAMESPACE}:__heartbeats__", {worker_id: now_ms - DEAD_FOR_MS})
    redis_client.sadd(
        f"{NAMESPACE}:__acks__.{worker_id}.{queue}", message.options["redis_message_id"]
    )
    redis_client.hset(
        f"{NAMESPACE}:{queue}.msgs", message.options["redis_message_id"], message.encode().decode()
    )


def test_a_consumer_requeues_the_unacked_message_of_a_dead_worker_and_runs_new_jobs(
    worker_broker: Any, app_engine: Engine, redis_client: redis_lib.Redis
) -> None:
    tenant = str(seed_tenant(app_engine).id)
    queue = unique_queue()
    done: list[str] = []
    both = threading.Event()

    def job(tenant_id: str, label: str) -> None:
        done.append(label)
        if {"fresh", "orphan"} <= set(done):
            both.set()

    actor = make_actor(worker_broker, job, queue=queue, max_retries=0)
    orphan_id = uuid4().hex
    orphan = actor.message_with_options(
        kwargs={"tenant_id": tenant, "label": "orphan"}, redis_message_id=orphan_id
    ).copy(message_id=orphan_id)
    worker_id = f"dead-{uuid4().hex[:8]}"
    register_dead_worker(redis_client, queue, orphan, worker_id)

    with running_worker(worker_broker, {queue}, threads=1) as worker:
        actor.send(tenant_id=tenant, label="fresh")
        wait_idle(worker_broker, worker, {queue})
        assert both.wait(timeout=30), f"jobs run: {done}"

    assert sorted(done) == ["fresh", "orphan"]
    assert redis_client.exists(f"{NAMESPACE}:__acks__.{worker_id}.{queue}") == 0
    assert redis_client.zscore(f"{NAMESPACE}:__heartbeats__", worker_id) is None, (
        "the dead worker is removed from the heartbeats once nothing of it is left"
    )


def test_with_the_app_user_the_dead_worker_maintenance_step_is_refused_by_the_acl(
    settings: Any, engine_env: None, redis_client: redis_lib.Redis, app_engine: Engine
) -> None:
    """Documents why the worker user exists: with the app user the same maintenance step fails with NOPERM."""
    app_url = with_redis_db(redis_url_as(settings.redis_url, "qualloop_app", _password(settings)))
    broker = build(app_url)
    try:
        queue = unique_queue()
        actor = make_actor(broker, lambda tenant_id: None, queue=queue, max_retries=0)
        orphan_id = uuid4().hex
        orphan = actor.message_with_options(
            kwargs={"tenant_id": str(seed_tenant(app_engine).id)}, redis_message_id=orphan_id
        ).copy(message_id=orphan_id)
        register_dead_worker(redis_client, queue, orphan, f"dead-{uuid4().hex[:8]}")
        with pytest.raises(redis_lib.exceptions.ResponseError, match=r"(?i)keys|ACL|NOPERM"):
            broker.do_fetch(queue, 1)
    finally:
        broker.close()


def _password(settings: Any) -> str:
    return urlsplit(settings.redis_url).password or ""
