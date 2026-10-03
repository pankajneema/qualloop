"""API.md 1.6 / INV-PLT-14: Idempotency-Key replay, mismatch, in-flight conflict, scope and 24 h retention."""

import threading
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
import time_machine
from sqlalchemy import Engine, text

from tests.factories.api import ApiFactory, new_key, problem
from tests.factories.db import SeededTenant, create_user, fetch_all
from tests.integration.commands.test_command_audit_and_outbox import log_rows, outbox_rows
from tests.integration.commands.test_platform_commands_api import admin_client, new_plant_body

pytestmark = pytest.mark.integration


def plants_with_code(engine: Engine, tenant: UUID, code: str) -> int:
    return len(fetch_all(engine, tenant, "SELECT 1 FROM plants WHERE code = :c", {"c": code}))


def test_idempotency_key_replays_original_response(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine, clean_outbox: None
) -> None:
    admin = admin_client(api, seeded)
    body = new_plant_body()
    key = new_key()
    first = admin.post("/plants", body, key=key)
    assert first.status_code in (200, 201), first.text
    assert "idempotency-replayed" not in first.headers
    again = admin.post("/plants", body, key=key)
    assert again.status_code == first.status_code
    assert again.json() == first.json()
    assert again.headers["idempotency-replayed"] == "true"
    assert plants_with_code(app_engine, seeded.id, body["code"]) == 1
    plant = UUID(first.json()["id"])
    assert len(log_rows(app_engine, seeded.id, plant)) == 1  # side effects ran once
    assert len(outbox_rows(app_engine, seeded.id, plant)) == 1


def test_replay_works_from_a_different_session_of_the_same_user(
    api: ApiFactory, seeded: SeededTenant
) -> None:
    assert seeded.admin
    body, key = new_plant_body(), new_key()
    first = api.login_as(seeded.admin).post("/plants", body, key=key)
    second = api.login_as(seeded.admin).post("/plants", body, key=key)
    assert second.headers["idempotency-replayed"] == "true"
    assert second.json() == first.json()


def test_idempotency_key_reuse_with_different_body_rejected(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine
) -> None:
    admin = admin_client(api, seeded)
    body = new_plant_body()
    key = new_key()
    first = admin.post("/plants", body, key=key)
    other = new_plant_body()
    clash = admin.post("/plants", other, key=key)
    assert clash.status_code == 422
    assert problem(clash)["code"] == "idempotency_mismatch"
    assert plants_with_code(app_engine, seeded.id, other["code"]) == 0
    replay = admin.post("/plants", body, key=key)  # the original is still replayable
    assert replay.json() == first.json()


def test_idempotency_key_is_scoped_to_the_actor(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine
) -> None:
    second_admin = create_user(app_engine, seeded.id, role="admin")
    key = new_key()
    a = admin_client(api, seeded).post("/plants", new_plant_body(), key=key)
    b = api.login_as(second_admin).post("/plants", new_plant_body(), key=key)
    assert a.status_code in (200, 201) and b.status_code in (200, 201)
    assert a.json()["id"] != b.json()["id"]
    assert "idempotency-replayed" not in b.headers


def test_idempotency_key_is_scoped_to_the_tenant(
    api: ApiFactory, seeded_pair: tuple[SeededTenant, SeededTenant]
) -> None:
    a, b = seeded_pair
    key = new_key()
    ra = admin_client(api, a).post("/plants", new_plant_body(), key=key)
    rb = admin_client(api, b).post("/plants", new_plant_body(), key=key)
    assert ra.status_code in (200, 201) and rb.status_code in (200, 201)
    assert "idempotency-replayed" not in rb.headers


def test_idempotency_record_stores_endpoint_hash_response_and_24_hour_expiry(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine
) -> None:
    admin = admin_client(api, seeded)
    key = new_key()
    resp = admin.post("/plants", new_plant_body(), key=key)
    assert seeded.admin
    row = fetch_all(
        app_engine, seeded.id, "SELECT * FROM idempotency_keys WHERE key = :k", {"k": key}
    )[0]
    assert row["actor_id"] == seeded.admin.id
    assert "plants" in row["endpoint"]
    assert row["request_hash"]
    assert row["response_status"] == resp.status_code
    assert row["response_body"] == resp.json()
    lifetime = row["expires_at"] - row["created_at"]
    assert (
        timedelta(hours=24) - timedelta(minutes=5)
        <= lifetime
        <= timedelta(hours=24) + timedelta(minutes=5)
    )


def test_expired_idempotency_key_is_forgotten(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine
) -> None:
    admin = admin_client(api, seeded)
    key = new_key()
    assert admin.post("/plants", new_plant_body(), key=key).status_code in (200, 201)
    fresh = new_plant_body()
    # the app role may not UPDATE expires_at (column grants), so move the clock past the 24 h retention instead
    with time_machine.travel(datetime.now(UTC) + timedelta(hours=25), tick=True):
        late_admin = admin_client(api, seeded)  # the old session is past its own lifetime by then
        resp = late_admin.post(
            "/plants", fresh, key=key
        )  # different body: would be 422 if the key were remembered
    assert resp.status_code in (200, 201), resp.text
    assert "idempotency-replayed" not in resp.headers
    assert plants_with_code(app_engine, seeded.id, fresh["code"]) == 1


def test_commands_without_an_idempotency_key_execute_every_time(
    api: ApiFactory, seeded: SeededTenant
) -> None:
    admin = admin_client(api, seeded)
    ids = {admin.post("/plants", new_plant_body()).json()["id"] for _ in range(3)}
    assert len(ids) == 3


def _wait_until(predicate: Any, timeout: float = 10.0) -> bool:
    waiter = threading.Event()
    deadline = datetime.now(UTC) + timedelta(seconds=timeout)
    while datetime.now(UTC) < deadline:
        if predicate():
            return True
        waiter.wait(0.05)
    return False


def _waiting_on_plants_lock(engine: Engine) -> bool:
    with engine.connect() as conn:
        waiting = conn.execute(
            text(
                "SELECT count(*) FROM pg_locks WHERE locktype = 'relation' AND NOT granted "
                "AND relation = 'public.plants'::regclass"
            )
        ).scalar_one()
    return bool(waiting > 0)


def test_same_key_while_the_first_request_is_in_flight_is_409_conflict(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine, owner_engine: Engine
) -> None:
    """The first request is parked on a table lock held by the test (a real in-flight transaction); the
    second must be refused immediately with 409 conflict, never block and never run the command twice."""
    assert seeded.admin
    body, key = new_plant_body(), new_key()
    first_client = api.login_as(seeded.admin)
    second_client = api.login_as(seeded.admin)
    results: dict[str, httpx.Response] = {}

    blocker = owner_engine.execution_options(isolation_level="READ COMMITTED").connect()
    tx = blocker.begin()
    blocker.execute(text("LOCK TABLE plants IN SHARE ROW EXCLUSIVE MODE"))

    def call(name: str, client: Any) -> None:
        results[name] = client.post("/plants", body, key=key)

    t1 = threading.Thread(target=call, args=("first", first_client))
    t2 = threading.Thread(target=call, args=("second", second_client))
    try:
        t1.start()
        parked = _wait_until(lambda: _waiting_on_plants_lock(owner_engine))
        assert parked, "the first request never reached the plants insert; test premise broken"
        t2.start()
        t2.join(timeout=10)
        second_done = not t2.is_alive()
    finally:
        tx.rollback()  # releases the lock so the first request can finish
        blocker.close()
        t1.join(timeout=20)
        t2.join(timeout=20)
    assert second_done, "second request blocked behind the in-flight one instead of returning 409"
    assert results["second"].status_code == 409, results["second"].text
    assert problem(results["second"])["code"] == "conflict"
    assert results["first"].status_code in (200, 201), results["first"].text
    assert plants_with_code(app_engine, seeded.id, body["code"]) == 1
    third = first_client.post("/plants", body, key=key)
    assert third.headers["idempotency-replayed"] == "true"
    assert third.json() == results["first"].json()
