"""Outbox dispatcher cycle (ADR-006, blueprint 22.2).

One cycle = one transaction: claim up to `limit` pending events with `app_claim_outbox_batch` (FOR UPDATE SKIP LOCKED,
oldest first, skipping events still inside their backoff), hand each to `enqueue`, then mark it processed or count the
failure under that event's tenant. Two dispatchers can run side by side: SKIP LOCKED gives each event to exactly one.

Backoff after failure n is `5 s x 2^n`; the 5th failure makes the event a dead letter (stays unprocessed with
attempts = 5, never claimed again) and raises an alert (log line `outbox_event_dead_lettered`, counter).
"""

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import structlog
from dramatiq import Message
from sqlalchemy import text

from app.core.db import set_tenant, system_tx
from app.core.jobs import get_broker
from app.core.outbox import registry

log = structlog.get_logger("outbox")

MAX_ATTEMPTS = 5
MAX_ERROR_BYTES = 4096


_counters: dict[str, Any] = {}
_counters_lock = threading.Lock()


def _counter(name: str, description: str) -> Any:
    """A Prometheus counter, created on first use.

    `prometheus_client` is imported lazily on purpose: dramatiq's Prometheus middleware must set its multiprocess
    directory BEFORE the library is first imported in a worker process, so no module may import it at load time."""
    from prometheus_client import Counter

    with _counters_lock:
        if name not in _counters:
            _counters[name] = Counter(name, description)
        return _counters[name]


def _count(name: str, description: str) -> None:
    _counter(f"qualloop_outbox_events_{name}_total", description).inc()


@dataclass(frozen=True)
class ClaimedEvent:
    id: UUID
    tenant_id: UUID
    event_id: UUID
    event_type: str
    aggregate_type: str
    aggregate_id: UUID
    payload: dict[str, Any]
    attempts: int


@dataclass(frozen=True)
class DispatchResult:
    processed: int
    failed: int


def backoff_seconds(attempts: int) -> int:
    """Wait before an event that has failed `attempts` times may be claimed again: 5 s x 2^attempts."""
    return int(5 * 2**attempts)


def message_id_for(event_id: UUID, handler_name: str) -> str:
    """Stable Dramatiq message id per (event, handler): a redelivered event produces the same id."""
    return f"{event_id}:{handler_name}"


def default_enqueue(event: ClaimedEvent) -> None:
    """One Dramatiq message per handler registered for the event type (none is registered for platform events in R1)."""
    spec = registry.get(event.event_type)
    if spec is None or not spec.handlers:
        return
    broker = get_broker()
    for handler in spec.handlers:
        actor = broker.get_actor(handler)
        broker.enqueue(
            Message(
                queue_name=actor.queue_name,
                actor_name=handler,
                args=(),
                kwargs={
                    "tenant_id": str(event.tenant_id),
                    "event_id": str(event.event_id),
                    "event_type": event.event_type,
                    "aggregate_type": event.aggregate_type,
                    "aggregate_id": str(event.aggregate_id),
                    "payload": event.payload,
                },
                options={},
                message_id=message_id_for(event.event_id, handler),
            )
        )


def _safe_error(exc: BaseException) -> str:
    """Error text for `last_error`: no NUL bytes (Postgres text cannot hold them), at most 4 kB of UTF-8."""
    raw = f"{type(exc).__name__}: {exc}".replace("\x00", "")
    return raw.encode("utf-8")[:MAX_ERROR_BYTES].decode("utf-8", "ignore")


def dispatch_once(
    *, enqueue: Callable[[ClaimedEvent], None] | None = None, limit: int = 100
) -> DispatchResult:
    send = enqueue or default_enqueue
    processed = failed = 0
    with system_tx() as session:
        rows = session.execute(
            text(
                "SELECT id, tenant_id, event_id, event_type, aggregate_type, aggregate_id, payload, attempts "
                "FROM app_claim_outbox_batch(:limit)"
            ),
            {"limit": limit},
        ).all()
        for row in rows:
            event = ClaimedEvent(
                id=row.id,
                tenant_id=row.tenant_id,
                event_id=row.event_id,
                event_type=row.event_type,
                aggregate_type=row.aggregate_type,
                aggregate_id=row.aggregate_id,
                payload=dict(row.payload),
                attempts=row.attempts,
            )
            error: str | None = None
            try:
                send(event)
            except Exception as exc:
                error = _safe_error(exc)
            # Each update runs under the event's own tenant (the claim ran with none).
            set_tenant(session, event.tenant_id)
            if error is None:
                session.execute(
                    text(
                        "UPDATE outbox_events SET processed_at = now() WHERE tenant_id = :t AND id = :id"
                    ),
                    {"t": event.tenant_id, "id": event.id},
                )
                processed += 1
                _count("dispatched", "Outbox events handed to the job queue.")
                continue
            attempts = session.execute(
                text(
                    "UPDATE outbox_events SET attempts = attempts + 1, last_error = :error "
                    "WHERE tenant_id = :t AND id = :id RETURNING attempts"
                ),
                {"t": event.tenant_id, "id": event.id, "error": error},
            ).scalar_one()
            failed += 1
            _count("failed", "Outbox dispatch attempts that failed.")
            log.warning(
                "outbox_dispatch_failed",
                event_id=str(event.event_id),
                tenant_id=str(event.tenant_id),
                attempts=attempts,
            )
            if attempts >= MAX_ATTEMPTS:
                _count("dead_lettered", "Outbox events that reached 5 failed attempts.")
                log.error(
                    "outbox_event_dead_lettered",
                    event_id=str(event.event_id),
                    tenant_id=str(event.tenant_id),
                    event_type=event.event_type,
                    attempts=attempts,
                )
    return DispatchResult(processed=processed, failed=failed)
