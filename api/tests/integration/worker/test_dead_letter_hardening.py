"""P01 contract items 9 (job part), 16 and 17 (code and security review): dead-lettered jobs are observable
(`qualloop_jobs_dead_lettered_total{queue,actor}`) and neither the database row nor the dead-lettered Dramatiq message
keeps PII from the exception (bound parameters, DETAIL lines, tracebacks)."""

import json
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
import redis as redis_lib
from prometheus_client import REGISTRY
from sqlalchemy import Engine, text

from app.core.config import Settings
from tests.factories.contract import load
from tests.factories.db import SeededTenant, create_tenant, fetch_all, seed_tenant
from tests.factories.env import worker_redis_url
from tests.factories.jobs import make_actor, unique_queue
from tests.integration.auth.helpers import redis_keys, redis_values
from tests.integration.worker.test_worker_jobs import FAST_RETRY, Boom, run_job, send_failing_job

pytestmark = pytest.mark.integration

METRIC = "qualloop_jobs_dead_lettered_total"


@pytest.fixture
def broker(settings: Settings, engine_env: None, redis_client: redis_lib.Redis) -> Iterator[Any]:
    b = load("app.worker", "build_broker")(worker_redis_url())
    yield b
    b.close()


def sample(queue: str, actor: str) -> float | None:
    return REGISTRY.get_sample_value(METRIC, {"queue": queue, "actor": actor})


def dead_letter_with_db_error(
    broker: Any, engine: Engine, tenant: Any, sql: str, params: dict[str, Any]
) -> tuple[Any, dict[str, Any]]:
    queue = unique_queue()

    def job(tenant_id: str) -> None:
        load("app.core.db", "current_session")().execute(text(sql), params)

    actor = make_actor(broker, job, queue=queue, **FAST_RETRY)
    run_job(broker, queue, lambda _w: actor.send(tenant_id=str(tenant)))
    rows = fetch_all(engine, tenant, "SELECT last_error, attempts FROM job_dead_letters")
    assert len(rows) == 1, "the job should have been dead-lettered after its attempts"
    return actor, rows[0]


# --- item 16: metric --------------------------------------------------------------------------------
def test_dead_lettering_a_job_increments_the_dead_letter_counter_for_its_queue_and_actor(
    broker: Any, app_engine: Engine
) -> None:
    tenant = create_tenant(app_engine)
    queue = unique_queue()
    boom = Boom()
    assert REGISTRY.get_sample_value(METRIC, {"queue": queue, "actor": "zz_none"}) is None
    actor, _message = send_failing_job(broker, tenant, boom, queue)
    assert boom.calls == 5
    assert sample(queue, actor.actor_name) == 1.0


def test_a_job_that_recovers_does_not_touch_the_dead_letter_counter(
    broker: Any, app_engine: Engine
) -> None:
    tenant = create_tenant(app_engine)
    calls: list[int] = []

    def flaky(tenant_id: str) -> None:
        calls.append(1)
        if len(calls) < 2:
            raise RuntimeError("transient")

    queue = unique_queue()
    actor = make_actor(broker, flaky, queue=queue, **FAST_RETRY)
    run_job(broker, queue, lambda _w: actor.send(tenant_id=str(tenant)))
    assert len(calls) == 2
    assert sample(queue, actor.actor_name) in (None, 0.0)


def test_each_dead_lettered_message_counts_once(broker: Any, app_engine: Engine) -> None:
    tenant = create_tenant(app_engine)
    queue = unique_queue()
    boom = Boom()
    actor = make_actor(broker, boom.run, queue=queue, **FAST_RETRY)

    def send_two(_worker: Any) -> None:
        for _ in range(2):
            actor.send(tenant_id=str(tenant))

    run_job(broker, queue, send_two)
    assert sample(queue, actor.actor_name) == 2.0


# --- item 17: traceback ----------------------------------------------------------------------------
def test_a_dead_lettered_dramatiq_message_does_not_keep_the_raw_email_from_the_exception(
    broker: Any, app_engine: Engine, redis_client: redis_lib.Redis
) -> None:
    tenant = create_tenant(app_engine)
    queue = unique_queue()
    email = f"pii.person.{uuid4().hex[:8]}@example.test"
    send_failing_job(broker, tenant, Boom(f"cannot deliver to {email}"), queue)

    assert redis_client.zcard(f"dramatiq:{queue}.XQ") == 1, (
        "the message must be in the dead-letter queue"
    )
    stored = [
        value
        for key in redis_keys(redis_client, f"dramatiq:{queue}*")
        for value in redis_values(redis_client, key)
    ]
    assert stored, "nothing stored for the queue"
    blob = " ".join(stored)
    assert email not in blob, "raw email survived in the dead-lettered message (options.traceback)"
    assert json.dumps(email) not in blob


def test_the_dead_lettered_message_still_names_the_exception_type(
    broker: Any, app_engine: Engine, redis_client: redis_lib.Redis
) -> None:
    """Masking must not blank the traceback: operators still need to see what failed."""
    tenant = create_tenant(app_engine)
    queue = unique_queue()
    send_failing_job(broker, tenant, Boom("plain failure"), queue)
    blob = " ".join(
        value
        for key in redis_keys(redis_client, f"dramatiq:{queue}*")
        for value in redis_values(redis_client, key)
    )
    assert "RuntimeError" in blob


# --- item 9: database errors in jobs ---------------------------------------------------------------
def test_a_job_failing_on_a_database_error_does_not_store_the_bound_email_in_last_error(
    broker: Any, app_engine: Engine
) -> None:
    tenant = create_tenant(app_engine)
    email = f"param.leak.{uuid4().hex[:8]}@example.test"
    _actor, row = dead_letter_with_db_error(
        broker,
        app_engine,
        tenant,
        "INSERT INTO users (tenant_id, email, no_such_column) VALUES (:t, :e, 1)",
        {"t": tenant, "e": email},
    )
    assert row["attempts"] == 5
    assert email not in row["last_error"]
    assert "[parameters:" not in row["last_error"]
    assert "no_such_column" in row["last_error"], "the cause must stay readable"


def test_a_unique_violation_in_a_job_does_not_store_the_duplicate_email_from_the_detail_line(
    broker: Any, app_engine: Engine
) -> None:
    """PostgreSQL's DETAIL ("Key (email)=(...) already exists") repeats the value even without bound parameters."""
    seeded: SeededTenant = seed_tenant(app_engine)
    assert seeded.admin
    _actor, row = dead_letter_with_db_error(
        broker,
        app_engine,
        seeded.id,
        "INSERT INTO users (tenant_id, email, name, role) VALUES (:t, :e, 'Dup', 'quality')",
        {"t": seeded.id, "e": seeded.admin.email},
    )
    assert seeded.admin.email not in row["last_error"]
    assert "duplicate key" in row["last_error"].lower(), "the cause must stay readable"
