"""ADR-006 / ADR-004: Dramatiq worker middleware. Tenant context per job, jobs without tenant_id are rejected,
5 attempts then dead-letter recorded durably in Postgres. In-process worker on private queues (Redis db 15)."""

import contextlib
import json
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
import redis as redis_lib
from sqlalchemy import Engine, text

from app.core.config import Settings
from app.core.logging import configure_logging
from tests.factories.contract import load
from tests.factories.db import create_tenant, fetch_all, seed_tenant
from tests.factories.env import worker_redis_url
from tests.factories.jobs import make_actor, running_worker, unique_queue, wait_idle

pytestmark = pytest.mark.integration

FAST_RETRY = {
    "min_backoff": 1,
    "max_backoff": 5,
}  # milliseconds; keeps 5 attempts well under a second


@pytest.fixture
def broker(settings: Settings, engine_env: None, redis_client: redis_lib.Redis) -> Iterator[Any]:
    build_broker = load("app.worker", "build_broker")
    b = build_broker(worker_redis_url())
    yield b
    b.close()


def run_job(broker: Any, queue: str, send: Callable[[Any], None], threads: int = 1) -> None:
    with running_worker(broker, {queue}, threads=threads) as worker:
        send(worker)
        wait_idle(broker, worker, {queue})


def tenant_probe(results: dict[str, Any]) -> Callable[..., None]:
    def job(tenant_id: str) -> None:
        try:
            session = load("app.core.db", "current_session")()
            results.setdefault("tenants", []).append(
                session.execute(text("SELECT current_setting('app.tenant_id', true)")).scalar_one()
            )
            results["actor_type"] = session.execute(
                text("SELECT current_setting('app.actor_type', true)")
            ).scalar_one()
            results[tenant_id] = {r[0] for r in session.execute(text("SELECT id FROM plants"))}
        except Exception as exc:
            results["error"] = repr(exc)

    return job


def test_worker_job_runs_with_job_tenant_context(broker: Any, app_engine: Engine) -> None:
    tenant = seed_tenant(app_engine)
    results: dict[str, Any] = {}
    queue = unique_queue()
    actor = make_actor(broker, tenant_probe(results), queue=queue, max_retries=0)
    run_job(broker, queue, lambda _w: actor.send(tenant_id=str(tenant.id)))
    assert "error" not in results, results.get("error")
    assert results["tenants"] == [str(tenant.id)]
    assert results["actor_type"] == "system"
    assert results[str(tenant.id)] == set(tenant.plants)


def test_worker_job_cannot_read_other_tenant(broker: Any, app_engine: Engine) -> None:
    a, b = seed_tenant(app_engine), seed_tenant(app_engine)
    outcome: dict[str, Any] = {}
    queue = unique_queue()

    def job(tenant_id: str) -> None:
        try:
            session = load("app.core.db", "current_session")()
            outcome["foreign_plants"] = session.execute(
                text("SELECT count(*) FROM plants WHERE id = ANY(:ids)"), {"ids": list(b.plants)}
            ).scalar_one()
            outcome["foreign_users"] = session.execute(
                text("SELECT count(*) FROM users WHERE tenant_id = :t"), {"t": b.id}
            ).scalar_one()
            outcome["foreign_tenant"] = session.execute(
                text("SELECT count(*) FROM tenants WHERE id = :t"), {"t": b.id}
            ).scalar_one()
        except Exception as exc:
            outcome["error"] = repr(exc)

    actor = make_actor(broker, job, queue=queue, max_retries=0)
    run_job(broker, queue, lambda _w: actor.send(tenant_id=str(a.id)))
    assert "error" not in outcome, outcome.get("error")
    assert outcome == {"foreign_plants": 0, "foreign_users": 0, "foreign_tenant": 0}


def test_worker_job_cannot_write_for_another_tenant(broker: Any, app_engine: Engine) -> None:
    a, b = seed_tenant(app_engine), seed_tenant(app_engine)
    outcome: dict[str, Any] = {}
    queue = unique_queue()

    def job(tenant_id: str) -> None:
        session = load("app.core.db", "current_session")()
        try:
            session.execute(
                text("INSERT INTO plants (tenant_id, name, code) VALUES (:t, 'Planted', 'EVIL9')"),
                {"t": b.id},
            )
            outcome["inserted"] = True
        except Exception as exc:
            outcome["error"] = str(exc)

    actor = make_actor(broker, job, queue=queue, max_retries=0)
    run_job(broker, queue, lambda _w: actor.send(tenant_id=str(a.id)))
    assert "inserted" not in outcome
    assert "row-level security" in outcome["error"]
    assert fetch_all(app_engine, b.id, "SELECT 1 FROM plants WHERE code = 'EVIL9'") == []


def test_consecutive_jobs_for_different_tenants_on_one_pooled_connection_do_not_leak_context(
    broker: Any, app_engine: Engine
) -> None:
    a, b = seed_tenant(app_engine), seed_tenant(app_engine)
    results: dict[str, Any] = {}
    queue = unique_queue()
    actor = make_actor(broker, tenant_probe(results), queue=queue, max_retries=0)

    def send(_w: Any) -> None:
        for tenant in (a, b, a, b):
            actor.send(tenant_id=str(tenant.id))

    run_job(broker, queue, send, threads=1)
    assert "error" not in results, results.get("error")
    assert results[str(a.id)] == set(a.plants) and results[str(b.id)] == set(b.plants)
    assert results["tenants"] == [str(a.id), str(b.id), str(a.id), str(b.id)]


def _ran_without_tenant(broker: Any, send_kwargs: dict[str, Any]) -> bool:
    ran: list[bool] = []
    queue = unique_queue()
    actor = make_actor(broker, lambda **_: ran.append(True), queue=queue, max_retries=0)
    with running_worker(broker, {queue}) as worker:
        with contextlib.suppress(Exception):
            actor.send(**send_kwargs)  # the middleware may refuse at send time or at run time
        wait_idle(broker, worker, {queue})
    return bool(ran)


@pytest.mark.parametrize(
    "kwargs",
    [{}, {"tenant_id": None}, {"tenant_id": ""}, {"tenant_id": "not-a-uuid"}, {"note": "x"}],
    ids=["no-kwargs", "none", "empty", "malformed", "other-kwargs-only"],
)
def test_job_without_a_valid_tenant_id_is_rejected_and_never_runs(
    broker: Any, kwargs: dict[str, Any]
) -> None:
    assert _ran_without_tenant(broker, kwargs) is False


# --- retries and dead letters ----------------------------------------------------------------------
class Boom:
    def __init__(self, message: str = "provider timeout") -> None:
        self.message = message
        self.calls = 0

    def run(self, tenant_id: str, event_id: str | None = None) -> None:
        self.calls += 1
        raise RuntimeError(self.message)


def send_failing_job(
    broker: Any, tenant: UUID, boom: Boom, queue: str, **extra: Any
) -> tuple[Any, Any]:
    actor = make_actor(broker, boom.run, queue=queue, **FAST_RETRY)
    holder: list[Any] = []
    run_job(broker, queue, lambda _w: holder.append(actor.send(tenant_id=str(tenant), **extra)))
    return actor, holder[0]


def test_job_dead_lettered_after_5_attempts(broker: Any, app_engine: Engine) -> None:
    """Blueprint 22.2: dead-letter after 5 attempts (five executions in total)."""
    tenant = create_tenant(app_engine)
    boom = Boom()
    send_failing_job(broker, tenant, boom, unique_queue())
    assert boom.calls == 5


def test_a_job_that_succeeds_on_the_third_attempt_is_not_dead_lettered(
    broker: Any, app_engine: Engine
) -> None:
    tenant = create_tenant(app_engine)
    calls: list[int] = []

    def flaky(tenant_id: str) -> None:
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("transient")

    queue = unique_queue()
    actor = make_actor(broker, flaky, queue=queue, **FAST_RETRY)
    run_job(broker, queue, lambda _w: actor.send(tenant_id=str(tenant)))
    assert len(calls) == 3
    assert fetch_all(app_engine, tenant, "SELECT 1 FROM job_dead_letters") == []


def test_dead_lettered_job_recorded_in_job_dead_letters(
    broker: Any, app_engine: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    """INV-PLT-20: durable row under the job's tenant, plus a job_dead_lettered alert log line."""
    configure_logging("INFO", "ci")
    tenant, other = create_tenant(app_engine), create_tenant(app_engine)
    event_id = uuid4()
    queue = unique_queue()
    started = datetime.now(UTC)
    actor, message = send_failing_job(
        broker, tenant, Boom("provider timeout"), queue, event_id=str(event_id)
    )
    rows = fetch_all(app_engine, tenant, "SELECT * FROM job_dead_letters")
    assert len(rows) == 1, "exactly one durable row per dead-lettered message"
    row = rows[0]
    assert row["queue"] == queue
    assert row["actor_name"] == actor.actor_name
    assert row["message_id"] == message.message_id
    assert row["event_id"] == event_id
    assert row["attempts"] == 5
    assert "provider timeout" in row["last_error"]
    assert row["payload"]["tenant_id"] == str(tenant) and row["payload"]["event_id"] == str(
        event_id
    )
    assert (
        started - timedelta(seconds=5)
        <= row["dead_lettered_at"]
        <= datetime.now(UTC) + timedelta(seconds=5)
    )
    assert row["resolved_at"] is None and row["resolved_by"] is None
    assert fetch_all(app_engine, other, "SELECT 1 FROM job_dead_letters") == [], (
        "RLS hides it from others"
    )
    alerts = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("{") and '"job_dead_lettered"' in line
    ]
    assert len(alerts) == 1
    assert alerts[0]["level"] in {"error", "critical"}
    assert alerts[0]["message_id"] == message.message_id and alerts[0]["tenant_id"] == str(tenant)
    assert alerts[0]["actor_name"] == actor.actor_name


def test_dead_letter_row_is_not_duplicated_if_the_same_message_dead_letters_twice(
    broker: Any, app_engine: Engine
) -> None:
    tenant = create_tenant(app_engine)
    queue = unique_queue()
    _, message = send_failing_job(broker, tenant, Boom(), queue)
    broker.enqueue(message)  # same message id again (e.g. a manual redrive of the Redis DLQ entry)
    with running_worker(broker, {queue}) as worker:
        wait_idle(broker, worker, {queue})
    assert (
        len(
            fetch_all(
                app_engine,
                tenant,
                "SELECT 1 FROM job_dead_letters WHERE message_id = :m",
                {"m": message.message_id},
            )
        )
        == 1
    )


def test_dead_letter_payload_is_ids_only_and_never_holds_exception_traceback(
    broker: Any, app_engine: Engine
) -> None:
    tenant = create_tenant(app_engine)
    send_failing_job(broker, tenant, Boom("secret token abc123 in message"), unique_queue())
    row = fetch_all(app_engine, tenant, "SELECT payload, last_error FROM job_dead_letters")[0]
    assert "abc123" not in json.dumps(row["payload"])
    assert "Traceback" not in row["last_error"]


# --- wiring ----------------------------------------------------------------------------------------
def test_global_broker_has_retry_and_prometheus_middleware_with_adr_006_backoff() -> None:
    broker = load("app.worker", "broker")
    by_name = {type(m).__name__: m for m in broker.middleware}
    assert {"Retries", "Prometheus"} <= set(by_name)
    assert by_name["Retries"].min_backoff == 10_000  # 10 s
    assert by_name["Retries"].max_backoff == 30 * 60 * 1000  # 30 min


@pytest.mark.parametrize(
    ("actor_name", "queue"), [("files.scan", "ai"), ("core.sweep_pending", "scheduled")]
)
def test_documented_platform_actors_are_registered_on_their_queues(
    actor_name: str, queue: str
) -> None:
    broker = load("app.worker", "broker")
    assert broker.get_actor(actor_name).queue_name == queue


def test_sweep_pending_is_a_safe_no_op_stub_returning_a_count(
    app_engine: Engine, engine_env: None
) -> None:
    create_tenant(app_engine)
    assert load("app.core.outbox.sweeper", "sweep_pending")() == 0
