"""P02 test contract 2.2, browser flow: the browser PUTs to the presigned quarantine URL and nothing promotes the file,
so a `POST /imports` for a key still in quarantine answers 404 AND must leave a `files.scan` job on the broker (at most
once per 30 s per key). The scan is a side effect of a request that ends in 404, so it must survive that response.

Regression: the scan was enqueued inside the command transaction, deferred to commit, and the 404 rolled it back, so
the file stayed in quarantine forever. These tests never promote a file themselves (unlike `stage_file`)."""

import json
from collections.abc import Callable, Iterator
from typing import Any
from uuid import UUID

import httpx
import pytest
import redis as redis_lib

from tests.factories import s3
from tests.factories.api import ApiClient
from tests.factories.contract import load
from tests.factories.db import SeededTenant
from tests.factories.env import bucket_files, bucket_quarantine, worker_redis_url
from tests.factories.imports import OK, XLSX_TYPE, file_for, supplier_row
from tests.factories.jobs import running_worker, wait_idle

pytestmark = pytest.mark.integration

SCAN_QUEUE = "ai"


@pytest.fixture
def broker_redis(redis_client: redis_lib.Redis) -> Iterator[redis_lib.Redis]:
    """The broker's own Redis connection (worker ACL user, db 15), cleared of the `ai` queue before and after."""
    client: redis_lib.Redis = redis_lib.Redis.from_url(worker_redis_url(), decode_responses=True)
    _clear_queue(client)
    yield client
    _clear_queue(client)
    client.close()


def _clear_queue(client: redis_lib.Redis) -> None:
    for name in (
        f"dramatiq:{SCAN_QUEUE}",
        f"dramatiq:{SCAN_QUEUE}.DQ",
        f"dramatiq:{SCAN_QUEUE}.msgs",
    ):
        client.delete(name)


def queued_scans(client: redis_lib.Redis, key: str) -> list[dict[str, Any]]:
    """`files.scan` messages waiting on the `ai` queue (ready or delayed) whose `key` argument is `key`."""
    found: list[dict[str, Any]] = []
    for queue in (f"dramatiq:{SCAN_QUEUE}", f"dramatiq:{SCAN_QUEUE}.DQ"):
        for message_id in client.lrange(queue, 0, -1):
            raw = client.hget(f"dramatiq:{SCAN_QUEUE}.msgs", message_id)
            if raw is None:
                continue
            message = json.loads(raw)
            if message.get("actor_name") == "files.scan" and message["kwargs"].get("key") == key:
                found.append(message)
    return found


def browser_upload(client: ApiClient, data: bytes, content_type: str = XLSX_TYPE) -> str:
    """What the browser does: presigned PUT URL from the API, then PUT the bytes. No scan, no promotion."""
    resp = client.post(
        "/files/upload-url", {"purpose": "import", "content_type": content_type, "size": len(data)}
    )
    assert resp.status_code == 200, resp.text
    info = resp.json()
    put = httpx.put(info["url"], content=data, headers={"Content-Type": content_type}, timeout=120)
    assert put.status_code in (200, 204), put.text
    return str(info["key"])


def _create(client: ApiClient, key: str, name: str) -> httpx.Response:
    return client.post("/imports", {"entity": "suppliers", "key": key, "file_name": name})


def _suppliers_file() -> tuple[bytes, str]:
    data, name, _ = file_for("suppliers", [supplier_row(i) for i in range(3)])
    return data, name


def test_post_imports_for_a_key_still_in_quarantine_is_404_and_enqueues_a_files_scan_job(
    quality: ApiClient, broker_redis: redis_lib.Redis
) -> None:
    data, name = _suppliers_file()
    key = browser_upload(quality, data)
    assert s3.exists(bucket_quarantine(), key), (
        "precondition: the browser PUT left it in quarantine"
    )

    resp = _create(quality, key, name)

    assert resp.status_code == 404, resp.text
    scans = queued_scans(broker_redis, key)
    assert len(scans) == 1, "the 404 must not roll back the scan request (files.scan on queue `ai`)"
    assert scans[0]["kwargs"]["tenant_id"] == str(UUID(scans[0]["kwargs"]["tenant_id"]))


def test_browser_upload_becomes_importable_after_the_scan_runs_without_test_side_promotion(
    quality: ApiClient,
    seeded: SeededTenant,
    drain: Callable[[], None],
    broker_redis: redis_lib.Redis,
) -> None:
    data, name = _suppliers_file()
    key = browser_upload(quality, data)

    first = _create(quality, key, name)
    assert first.status_code == 404, first.text

    broker = load("app.worker", "broker")
    with running_worker(broker, {SCAN_QUEUE}, threads=1) as worker:
        wait_idle(broker, worker, {SCAN_QUEUE})
    drain()

    assert s3.exists(bucket_files(), key), "the worker, not the test, promoted the file"
    assert not s3.exists(bucket_quarantine(), key)
    second = _create(quality, key, name)
    assert second.status_code in OK, second.text
    batch = second.json()
    assert (batch["entity"], batch["status"], batch["file_name"]) == ("suppliers", "uploaded", name)
    assert batch["started_by"] == str(seeded.quality.id if seeded.quality else "")


def test_a_second_post_imports_within_30_seconds_does_not_enqueue_a_second_scan(
    quality: ApiClient, broker_redis: redis_lib.Redis
) -> None:
    data, name = _suppliers_file()
    key = browser_upload(quality, data)

    assert _create(quality, key, name).status_code == 404
    assert len(queued_scans(broker_redis, key)) == 1, (
        "precondition: the first request enqueued the scan"
    )
    assert _create(quality, key, name).status_code == 404
    assert _create(quality, key, name).status_code == 404

    assert len(queued_scans(broker_redis, key)) == 1, "at most one files.scan per key per 30 s"
