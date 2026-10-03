"""Concurrency and job-level isolation of the import flow. Barriers, never sleeps (P02 plan section 4)."""

import threading
from collections.abc import Callable
from uuid import UUID

import httpx
import pytest
from sqlalchemy import Engine

from tests.factories.api import ApiClient, ApiFactory, new_key, problem
from tests.factories.contract import load
from tests.factories.db import SeededTenant, fetch_all
from tests.factories.imports import Importer, file_for, mapping_for, supplier_row

pytestmark = pytest.mark.integration

ROUNDS = 3
ROWS = 5


def validated_batch(importer: Importer, n: int = ROWS, start: int = 0) -> str:
    data, name, ctype = file_for("suppliers", [supplier_row(start + i) for i in range(n)])
    return str(importer.run("suppliers", data, name, ctype, confirm=False)["id"])


def race(calls: list[Callable[[], httpx.Response]]) -> list[httpx.Response]:
    barrier = threading.Barrier(len(calls), timeout=30)
    results: dict[int, httpx.Response | BaseException] = {}

    def go(index: int, fn: Callable[[], httpx.Response]) -> None:
        try:
            barrier.wait()
            results[index] = fn()
        except BaseException as exc:  # reported by the assertion below
            results[index] = exc

    threads = [threading.Thread(target=go, args=(i, fn)) for i, fn in enumerate(calls)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(120)
    errors = [r for r in results.values() if isinstance(r, BaseException)]
    assert not errors, errors
    return [r for _, r in sorted(results.items()) if isinstance(r, httpx.Response)]


def confirm_call(
    client: ApiClient, batch_id: str, key: str | None = None
) -> Callable[[], httpx.Response]:
    def call() -> httpx.Response:
        return client.post(f"/imports/{batch_id}/confirm", {}, key=key or new_key())

    return call


def cancel_call(client: ApiClient, batch_id: str) -> Callable[[], httpx.Response]:
    def call() -> httpx.Response:
        return client.post(f"/imports/{batch_id}/cancel", {})

    return call


def supplier_count(engine: Engine, tenant: UUID) -> int:
    return int(fetch_all(engine, tenant, "SELECT count(*) AS n FROM suppliers")[0]["n"])


def test_concurrent_confirm_of_the_same_batch_one_wins_and_the_other_gets_409(
    api: ApiFactory,
    seeded: SeededTenant,
    importer: Importer,
    app_engine: Engine,
) -> None:
    assert seeded.quality and seeded.approver
    second_user = api.login_as(seeded.approver)
    for round_no in range(ROUNDS):
        before = supplier_count(app_engine, seeded.id)
        bid = validated_batch(importer, start=round_no * 100)  # new rows every round
        responses = race([confirm_call(importer.client, bid), confirm_call(second_user, bid)])
        codes = sorted(r.status_code for r in responses)
        assert codes[0] in (200, 201, 202) and codes[1] == 409, codes
        loser = next(r for r in responses if r.status_code == 409)
        assert problem(loser)["code"] in {"invalid_transition", "conflict"}
        importer.drain()
        batch = importer.get(bid)
        assert batch["status"] == "completed" and batch["rows_imported"] == ROWS
        assert supplier_count(app_engine, seeded.id) == before + ROWS, "imported exactly once"
        records = fetch_all(
            app_engine,
            seeded.id,
            "SELECT 1 FROM import_records WHERE batch_id = :b",
            {"b": UUID(bid)},
        )
        assert len(records) == ROWS


def test_two_requests_with_the_same_idempotency_key_import_once(
    api: ApiFactory, importer: Importer, seeded: SeededTenant, app_engine: Engine
) -> None:
    assert seeded.quality
    same_user_other_session = api.login_as(seeded.quality)
    bid = validated_batch(importer)
    key = new_key()
    responses = race(
        [confirm_call(importer.client, bid, key), confirm_call(same_user_other_session, bid, key)]
    )
    codes = sorted(r.status_code for r in responses)
    assert codes[0] in (200, 201, 202) and codes[1] in (200, 201, 202, 409), codes
    importer.drain()
    assert importer.get(bid)["status"] == "completed"
    assert supplier_count(app_engine, seeded.id) == ROWS


def test_a_cancel_racing_a_confirm_leaves_a_consistent_batch(
    api: ApiFactory, seeded: SeededTenant, importer: Importer, app_engine: Engine
) -> None:
    assert seeded.approver
    other = api.login_as(seeded.approver)
    bid = validated_batch(importer)
    responses = race([confirm_call(importer.client, bid), cancel_call(other, bid)])
    assert sorted(r.status_code in (200, 201, 202) for r in responses) == [False, True], [
        r.status_code for r in responses
    ]
    importer.drain()
    batch = importer.get(bid)
    if batch["status"] == "cancelled":
        assert supplier_count(app_engine, seeded.id) == 0
    else:
        assert batch["status"] == "completed" and supplier_count(app_engine, seeded.id) == ROWS


# =================================================================================================
# job-level tenant isolation (ADR-004: a job runs under its message's tenant and nothing else)
# =================================================================================================
def send_job(actor_name: str, tenant_id: UUID, batch_id: str) -> None:
    broker = load("app.worker", "broker")
    actor = broker.get_actor(actor_name)
    actor.send_with_options(
        kwargs={"tenant_id": str(tenant_id), "batch_id": batch_id}, max_retries=0
    )


def test_a_validate_job_sent_under_tenant_a_cannot_touch_tenant_bs_batch(
    api: ApiFactory,
    seeded_pair: tuple[SeededTenant, SeededTenant],
    drain: Callable[[], None],
) -> None:
    a, b = seeded_pair
    assert b.quality
    imp_b = Importer(api.login_as(b.quality), b.id, drain)
    data, name, ctype = file_for("suppliers", [supplier_row(2)])
    batch = imp_b.upload("suppliers", data, name, ctype)
    assert imp_b.map(batch["id"], mapping_for("suppliers")).status_code in (200, 201, 202)
    send_job("imports.validate", a.id, batch["id"])
    drain()
    after = imp_b.get(batch["id"])
    assert after["status"] == "mapped" and after["rows_received"] == 0


def test_an_import_job_sent_under_tenant_a_cannot_import_tenant_bs_batch(
    api: ApiFactory,
    seeded_pair: tuple[SeededTenant, SeededTenant],
    drain: Callable[[], None],
    app_engine: Engine,
) -> None:
    a, b = seeded_pair
    assert b.quality
    imp_b = Importer(api.login_as(b.quality), b.id, drain)
    bid = validated_batch(imp_b, 3)
    send_job("imports.run", a.id, bid)
    drain()
    assert imp_b.get(bid)["status"] == "validated"
    assert supplier_count(app_engine, b.id) == 0 and supplier_count(app_engine, a.id) == 0


def test_a_job_message_without_a_tenant_id_never_runs(
    importer: Importer, drain: Callable[[], None]
) -> None:
    bid = validated_batch(importer, 3)
    broker = load("app.worker", "broker")
    broker.get_actor("imports.run").send_with_options(kwargs={"batch_id": bid}, max_retries=0)
    drain()
    assert importer.get(bid)["status"] == "validated"
