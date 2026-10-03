"""ADR-006 / INV-PLT-12, INV-PLT-13: outbox claiming (FOR UPDATE SKIP LOCKED), retries with exponential backoff,
dead-letter after 5 attempts with an alert. Real Postgres; explicit barriers, no bare sleeps."""

import json
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine, text

from app.core.logging import configure_logging
from tests.factories.contract import load
from tests.factories.db import (
    age_outbox_row,
    create_tenant,
    insert_outbox_event,
    outbox_row,
)

pytestmark = pytest.mark.integration

JOIN_TIMEOUT = 30


def dispatch_once(**kwargs: Any) -> Any:
    return load("app.core.outbox.dispatcher", "dispatch_once")(**kwargs)


class Recorder:
    """Thread-safe enqueue stand-in that remembers what it was given."""

    def __init__(self) -> None:
        self.seen: list[UUID] = []
        self.tenants: dict[UUID, UUID] = {}
        self._lock = threading.Lock()

    def __call__(self, event: Any) -> None:
        with self._lock:
            self.seen.append(event.id)
            self.tenants[event.id] = event.tenant_id


class AlwaysFail:
    def __init__(self, error: str = "provider down") -> None:
        self.error = error
        self.calls: list[UUID] = []

    def __call__(self, event: Any) -> None:
        self.calls.append(event.id)
        raise RuntimeError(self.error)


def seed_events(engine: Engine, tenant: UUID, count: int) -> list[UUID]:
    now = datetime.now(UTC)
    return [
        insert_outbox_event(engine, tenant, created_at=now - timedelta(seconds=count - i))
        for i in range(count)
    ]


def claimable_ids(engine: Engine, limit: int = 1000) -> set[UUID]:
    with engine.connect() as conn, conn.begin():
        return {
            r[0]
            for r in conn.execute(text("SELECT id FROM app_claim_outbox_batch(:n)"), {"n": limit})
        }


# --- exactly once ----------------------------------------------------------------------------------
def test_outbox_event_processed_once_with_two_concurrent_dispatchers(
    app_engine: Engine, clean_outbox: None
) -> None:
    tenant = create_tenant(app_engine)
    ids = seed_events(app_engine, tenant, 10)
    seen: list[UUID] = []
    lock = threading.Lock()
    both_inside = threading.Barrier(2, timeout=15)
    errors: list[BaseException] = []

    def make_enqueue() -> Callable[[Any], None]:
        first = [True]

        def enqueue(event: Any) -> None:
            if first[0]:
                first[0] = False
                both_inside.wait()  # both dispatchers hold their claimed rows at this instant
            with lock:
                seen.append(event.id)

        return enqueue

    def worker() -> None:
        try:
            dispatch_once(enqueue=make_enqueue(), limit=5)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(JOIN_TIMEOUT)
    assert not errors, errors
    mine = [e for e in seen if e in set(ids)]
    assert sorted(mine) == sorted(ids), "every event must be enqueued exactly once"
    assert all(outbox_row(app_engine, tenant, i)["processed_at"] is not None for i in ids)
    assert all(outbox_row(app_engine, tenant, i)["attempts"] == 0 for i in ids)


def test_app_claim_outbox_batch_skip_locked_returns_disjoint_batches_to_open_transactions(
    app_engine: Engine, clean_outbox: None
) -> None:
    tenant = create_tenant(app_engine)
    ids = set(seed_events(app_engine, tenant, 10))
    first, second = app_engine.connect(), app_engine.connect()
    tx1, tx2 = first.begin(), second.begin()
    try:
        a = {r[0] for r in first.execute(text("SELECT id FROM app_claim_outbox_batch(5)"))}
        b = {
            r[0] for r in second.execute(text("SELECT id FROM app_claim_outbox_batch(5)"))
        }  # must not block
    finally:
        tx1.rollback()
        tx2.rollback()
        first.close()
        second.close()
    assert len(a) == len(b) == 5
    assert a.isdisjoint(b)
    assert a | b == ids


def test_dispatch_once_enqueues_each_pending_event_once_and_marks_it_processed(
    app_engine: Engine, clean_outbox: None
) -> None:
    tenant = create_tenant(app_engine)
    ids = seed_events(app_engine, tenant, 4)
    recorder = Recorder()
    result = dispatch_once(enqueue=recorder)
    assert sorted(recorder.seen) == sorted(ids)
    assert result.processed == 4 and result.failed == 0
    for i in ids:
        row = outbox_row(app_engine, tenant, i)
        assert (
            row["processed_at"] is not None and row["attempts"] == 0 and row["last_error"] is None
        )
    again = Recorder()
    dispatch_once(enqueue=again)
    assert again.seen == [], "a processed event must never be dispatched again"


def test_dispatch_once_claims_oldest_first_and_honours_the_limit(
    app_engine: Engine, clean_outbox: None
) -> None:
    tenant = create_tenant(app_engine)
    ids = seed_events(app_engine, tenant, 5)  # ids[0] is the oldest
    recorder = Recorder()
    dispatch_once(enqueue=recorder, limit=3)
    assert recorder.seen == ids[:3]
    assert outbox_row(app_engine, tenant, ids[3])["processed_at"] is None


def test_dispatch_once_processes_events_of_every_tenant_each_under_its_own_tenant(
    app_engine: Engine, clean_outbox: None
) -> None:
    a, b = create_tenant(app_engine), create_tenant(app_engine)
    ea, eb = insert_outbox_event(app_engine, a), insert_outbox_event(app_engine, b)
    recorder = Recorder()
    dispatch_once(enqueue=recorder)
    assert recorder.tenants[ea] == a and recorder.tenants[eb] == b
    assert outbox_row(app_engine, a, ea)["processed_at"] is not None
    assert outbox_row(app_engine, b, eb)["processed_at"] is not None


# --- failure, backoff, dead letter -----------------------------------------------------------------
def test_failed_enqueue_increments_attempts_records_the_error_and_keeps_the_event_pending(
    app_engine: Engine, clean_outbox: None
) -> None:
    tenant = create_tenant(app_engine)
    event = insert_outbox_event(app_engine, tenant)
    result = dispatch_once(enqueue=AlwaysFail("provider down"))
    row = outbox_row(app_engine, tenant, event)
    assert row["attempts"] == 1
    assert row["processed_at"] is None
    assert "provider down" in row["last_error"]
    assert result.failed == 1 and result.processed == 0


def test_a_failing_event_does_not_block_the_rest_of_its_batch(
    app_engine: Engine, clean_outbox: None
) -> None:
    tenant = create_tenant(app_engine)
    first, middle, last = seed_events(app_engine, tenant, 3)

    def enqueue(event: Any) -> None:
        if event.id == middle:
            raise RuntimeError("only this one fails")

    dispatch_once(enqueue=enqueue)
    assert outbox_row(app_engine, tenant, first)["processed_at"] is not None
    assert outbox_row(app_engine, tenant, last)["processed_at"] is not None
    assert outbox_row(app_engine, tenant, middle)["processed_at"] is None
    assert outbox_row(app_engine, tenant, middle)["attempts"] == 1


def test_failed_event_is_not_retried_inside_its_backoff_window(
    app_engine: Engine, clean_outbox: None
) -> None:
    tenant = create_tenant(app_engine)
    event = insert_outbox_event(app_engine, tenant)
    dispatch_once(enqueue=AlwaysFail())
    retry = Recorder()
    dispatch_once(enqueue=retry)
    assert retry.seen == []
    assert outbox_row(app_engine, tenant, event)["attempts"] == 1


def test_outbox_retry_backoff_increases_exponentially(
    app_engine: Engine, owner_engine: Engine, clean_outbox: None
) -> None:
    """After failure n the event is claimable again only once 5 s x 2^n have passed (10, 20, 40, 80 s)."""
    tenant = create_tenant(app_engine)
    event = insert_outbox_event(app_engine, tenant)
    failing = AlwaysFail()
    dispatch_once(enqueue=failing)
    assert outbox_row(app_engine, tenant, event)["attempts"] == 1
    for attempts in (1, 2, 3, 4):
        window = 5 * 2**attempts
        age_outbox_row(app_engine, owner_engine, tenant, event, window - 2)
        assert event not in claimable_ids(app_engine), (
            f"claimable too early after {attempts} failures"
        )
        age_outbox_row(app_engine, owner_engine, tenant, event, window + 2)
        assert event in claimable_ids(app_engine), f"not claimable after the {window}s window"
        dispatch_once(enqueue=failing)
        assert outbox_row(app_engine, tenant, event)["attempts"] == attempts + 1
    assert len(failing.calls) == 5


def test_outbox_event_dead_lettered_after_5_attempts_and_alert_emitted(
    app_engine: Engine, owner_engine: Engine, clean_outbox: None, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging("INFO", "ci")
    tenant = create_tenant(app_engine)
    event = insert_outbox_event(app_engine, tenant)
    failing = AlwaysFail("provider down")
    for _ in range(5):
        dispatch_once(enqueue=failing)
        age_outbox_row(app_engine, owner_engine, tenant, event, 3600)  # skip the backoff wait
    row = outbox_row(app_engine, tenant, event)
    assert row["attempts"] == 5 and row["processed_at"] is None, (
        "dead letter = unprocessed with attempts >= 5"
    )
    assert len(failing.calls) == 5
    assert event not in claimable_ids(app_engine), "a dead-lettered event is never claimed again"
    again = Recorder()
    dispatch_once(enqueue=again)
    assert event not in again.seen
    alerts = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("{") and '"outbox_event_dead_lettered"' in line
    ]
    assert len(alerts) == 1, "exactly one alert, at the transition to dead"
    alert = alerts[0]
    assert alert["level"] in {"error", "critical"}
    assert alert["event_id"] == str(row["event_id"]) and alert["tenant_id"] == str(tenant)
    assert alert["attempts"] == 5


def test_dead_letter_row_shows_up_in_the_dead_partial_index_predicate(
    app_engine: Engine, owner_engine: Engine, clean_outbox: None
) -> None:
    tenant = create_tenant(app_engine)
    event = insert_outbox_event(app_engine, tenant, attempts=5)
    row = outbox_row(app_engine, tenant, event)
    assert (
        row["processed_at"] is None and row["attempts"] >= 5
    )  # DATA_MODEL 1.5: dead = unprocessed, >= 5


def test_last_error_is_truncated_to_four_kilobytes(app_engine: Engine, clean_outbox: None) -> None:
    tenant = create_tenant(app_engine)
    event = insert_outbox_event(app_engine, tenant)
    dispatch_once(enqueue=AlwaysFail("x" * 20_000))
    stored = outbox_row(app_engine, tenant, event)["last_error"]
    assert 0 < len(stored.encode()) <= 4096


def test_enqueue_failure_message_does_not_have_to_be_json_safe(
    app_engine: Engine, clean_outbox: None
) -> None:
    tenant = create_tenant(app_engine)
    event = insert_outbox_event(app_engine, tenant)
    dispatch_once(enqueue=AlwaysFail("bad \x00 byte and ☃ snowman"))
    row = outbox_row(app_engine, tenant, event)
    assert row["attempts"] == 1 and "snowman" in row["last_error"]


# --- run loop --------------------------------------------------------------------------------------
def test_dispatcher_run_loop_processes_events_until_stopped(
    app_engine: Engine, clean_outbox: None
) -> None:
    run = load("app.dispatcher", "run")
    tenant = create_tenant(app_engine)
    event = insert_outbox_event(app_engine, tenant)
    stop, got_it = threading.Event(), threading.Event()
    seen: list[UUID] = []

    def enqueue(e: Any) -> None:
        seen.append(e.id)
        got_it.set()

    thread = threading.Thread(
        target=run, args=(stop,), kwargs={"interval": 0.05, "enqueue": enqueue}
    )
    thread.start()
    try:
        assert got_it.wait(15), "the loop never dispatched the pending event"
    finally:
        stop.set()
        thread.join(JOIN_TIMEOUT)
    assert not thread.is_alive(), "run() ignored the stop event"
    assert event in seen
    assert outbox_row(app_engine, tenant, event)["processed_at"] is not None


def test_dispatcher_run_loop_survives_a_failing_cycle(
    app_engine: Engine, clean_outbox: None
) -> None:
    run = load("app.dispatcher", "run")
    tenant = create_tenant(app_engine)
    insert_outbox_event(app_engine, tenant)
    stop, attempted = threading.Event(), threading.Event()

    def enqueue(_: Any) -> None:
        attempted.set()
        raise RuntimeError("provider down")

    thread = threading.Thread(
        target=run, args=(stop,), kwargs={"interval": 0.05, "enqueue": enqueue}
    )
    thread.start()
    try:
        assert attempted.wait(15)
    finally:
        stop.set()
        thread.join(JOIN_TIMEOUT)
    assert not thread.is_alive()
