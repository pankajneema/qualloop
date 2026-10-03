"""P01 contract item 4 (code review): the dispatcher's DEFAULT enqueue must work in the dispatcher process, where
actors are declared nowhere (they live in `app.worker`, which only the worker process imports).

A handler is registered by job name AND queue: `registry.add_handler(event_type, actor_name, queue=...)`
(contract section 5), so the dispatcher can build the Dramatiq message without having the actor object. The run happens
in a fresh interpreter so that no other test has imported `app.worker` or declared an actor on the global broker."""

import json
import os
import subprocess
import sys
from typing import Any
from uuid import UUID, uuid4

import pytest
import redis as redis_lib
from sqlalchemy import Engine

from tests.conftest import API_ROOT
from tests.factories.db import create_tenant, insert_outbox_event, outbox_row

pytestmark = pytest.mark.integration

EVENT_TYPE = "PLANT_CREATED"

SCRIPT = """
import json, sys
from app.core.outbox import registry
from app.core.outbox.dispatcher import dispatch_once

for actor_name, queue in json.loads(sys.argv[2]):
    try:
        registry.add_handler(sys.argv[1], actor_name, queue=queue)
    except TypeError:  # signature before the contract extension: the queue cannot be named
        registry.add_handler(sys.argv[1], actor_name)
result = dispatch_once()
print("RESULT " + json.dumps({"processed": result.processed, "failed": result.failed}))
"""


def run_dispatcher_process(handlers: list[tuple[str, str]]) -> dict[str, Any]:
    done = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-c", SCRIPT, EVENT_TYPE, json.dumps(handlers)],
        cwd=API_ROOT,
        env=dict(os.environ),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, f"dispatcher process failed:\n{done.stderr[-3000:]}"
    line = next(row for row in done.stdout.splitlines() if row.startswith("RESULT "))
    result: dict[str, Any] = json.loads(line.removeprefix("RESULT "))
    return result


def queued_message(redis_client: redis_lib.Redis, queue: str, message_id: str) -> dict[str, Any]:
    assert message_id in redis_client.lrange(f"dramatiq:{queue}", 0, -1), (
        f"{message_id} is not on queue {queue}"
    )
    raw = redis_client.hget(f"dramatiq:{queue}.msgs", message_id)
    assert raw is not None, f"no message body stored for {message_id}"
    message: dict[str, Any] = json.loads(raw)
    return message


def event_ids(engine: Engine, tenant: UUID, row_id: UUID) -> UUID:
    event_id = outbox_row(engine, tenant, row_id)["event_id"]
    assert isinstance(event_id, UUID)
    return event_id


def test_default_enqueue_in_a_fresh_dispatcher_process_puts_the_job_on_the_registered_queue(
    app_engine: Engine, clean_outbox: None, redis_client: redis_lib.Redis
) -> None:
    tenant = create_tenant(app_engine)
    row = insert_outbox_event(app_engine, tenant, event_type=EVENT_TYPE)
    event_id = event_ids(app_engine, tenant, row)
    handler, queue = f"zz.handler_{uuid4().hex[:8]}", f"zz_queue_{uuid4().hex[:8]}"

    result = run_dispatcher_process([(handler, queue)])

    assert result["failed"] == 0 and result["processed"] >= 1, result
    message = queued_message(redis_client, queue, f"{event_id}:{handler}")
    assert message["queue_name"] == queue
    assert message["actor_name"] == handler
    assert message["message_id"] == f"{event_id}:{handler}"
    assert message["kwargs"]["tenant_id"] == str(tenant)
    assert message["kwargs"]["event_id"] == str(event_id)
    assert message["kwargs"]["event_type"] == EVENT_TYPE
    row_after = outbox_row(app_engine, tenant, row)
    assert row_after["processed_at"] is not None, (
        "a successfully enqueued event must be marked processed"
    )
    assert row_after["attempts"] == 0 and row_after["last_error"] is None


def test_default_enqueue_sends_one_message_per_registered_handler_each_on_its_own_queue(
    app_engine: Engine, clean_outbox: None, redis_client: redis_lib.Redis
) -> None:
    tenant = create_tenant(app_engine)
    row = insert_outbox_event(app_engine, tenant, event_type=EVENT_TYPE)
    event_id = event_ids(app_engine, tenant, row)
    handlers = [
        (f"zz.first_{uuid4().hex[:6]}", f"zz_queue_a_{uuid4().hex[:6]}"),
        (f"zz.second_{uuid4().hex[:6]}", f"zz_queue_b_{uuid4().hex[:6]}"),
    ]

    result = run_dispatcher_process(handlers)

    assert result["failed"] == 0, result
    for handler, queue in handlers:
        message = queued_message(redis_client, queue, f"{event_id}:{handler}")
        assert message["actor_name"] == handler and message["queue_name"] == queue
    assert outbox_row(app_engine, tenant, row)["processed_at"] is not None


def test_an_event_without_registered_handlers_is_marked_processed_and_sends_nothing(
    app_engine: Engine, clean_outbox: None, redis_client: redis_lib.Redis
) -> None:
    tenant = create_tenant(app_engine)
    row = insert_outbox_event(app_engine, tenant, event_type=EVENT_TYPE)

    result = run_dispatcher_process([])

    assert result["failed"] == 0, result
    assert outbox_row(app_engine, tenant, row)["processed_at"] is not None
    assert not list(redis_client.scan_iter(match="dramatiq:zz_*", count=200))
