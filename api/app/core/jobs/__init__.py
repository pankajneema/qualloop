"""Job queue facade over Dramatiq (ADR-006): job registry, broker factory, enqueue.

Modules declare jobs with `@job(name, queue=...)`, which only records them. The worker process (`app.worker`) builds the
broker and declares every recorded job as an actor on it. The HTTP layer enqueues by name with `enqueue()`, which
needs neither the actor nor the worker module, so API code never imports provider clients (INV-PLT-11).
"""

import functools
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import dramatiq
from dramatiq import Broker, Message
from dramatiq.brokers.redis import RedisBroker
from dramatiq.middleware import (
    AgeLimit,
    Callbacks,
    Pipelines,
    Retries,
    ShutdownNotifications,
    TimeLimit,
)

from app.core.config import get_settings
from app.core.jobs.middleware import DeadLetter, Prometheus, TenantContext, TracebackMask

# SPEC-GAP: A-100 - blueprint 22.2: "dead-letter after 5 attempts". dramatiq counts RETRIES: max_retries=N means N + 1 executions, so
# max_retries=4 gives exactly 5 executions in total (ADR-006 says max_retries=5, which would be 6 attempts).
MAX_ATTEMPTS = 5
MAX_RETRIES = MAX_ATTEMPTS - 1
MIN_BACKOFF_MS = 10_000  # 10 s
MAX_BACKOFF_MS = 30 * 60 * 1000  # 30 min


@dataclass(frozen=True)
class JobRef:
    """A job's identity: its actor name and queue. Light enough for the HTTP layer to import; the implementation (which
    may import provider clients) lives in a `jobs.py` module that only the worker loads."""

    name: str
    queue: str


@dataclass(frozen=True)
class JobSpec:
    ref: JobRef
    fn: Callable[..., Any]
    options: dict[str, Any] = field(
        default_factory=dict
    )  # dramatiq actor options (and `own_transaction`)

    @property
    def name(self) -> str:
        return self.ref.name


_JOBS: dict[str, JobSpec] = {}
_broker: Broker | None = None
_lock = threading.Lock()


def job(ref: JobRef, **options: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Record a job. The decorated function is returned unchanged, so it stays directly callable in tests.

    By default the body runs inside one `tenant_tx`. A job that talks to the outside world (mail, HTTP, Redis state) must
    not hold a database transaction open meanwhile: it passes `own_transaction=True`, is then called with the tenant
    context bound but NO open transaction, and opens short `tenant_tx` blocks itself around its database work."""

    def register(fn: Callable[..., Any]) -> Callable[..., Any]:
        if ref.name in _JOBS and _JOBS[ref.name].fn is not fn:
            raise ValueError(f"job {ref.name!r} is already registered")
        _JOBS[ref.name] = JobSpec(ref=ref, fn=fn, options=dict(options))
        return fn

    return register


def registered_jobs() -> dict[str, JobSpec]:
    return dict(_JOBS)


class StableIdRedisBroker(RedisBroker):
    """A Redis broker whose FIRST enqueue of a message uses `message.message_id` as the Redis message id.

    Stock dramatiq invents a random Redis id per enqueue, so the same logical message sent twice is two independent
    entries. The outbox dispatcher gives every (event, handler) a stable `message_id` (`{event_id}:{actor}`); with a stable
    Redis id a redelivered event shares one stored body (an extra queue entry whose body was already acked is skipped by the
    consumer), and the id on the queue can be traced back to the event. Consumers still dedupe on `event_id`. Re-enqueues (retries carry `redis_message_id` already) and delayed sends keep dramatiq's
    behaviour: a retry must NOT share the id of the message still being processed."""

    def enqueue(self, message: Message[Any], *, delay: int | None = None) -> Message[Any]:
        if delay is not None or "redis_message_id" in message.options:
            return super().enqueue(message, delay=delay)
        message = message.copy(options={"redis_message_id": message.message_id})
        self.emit_before("enqueue", message, delay)
        self.do_enqueue(message.queue_name, message.options["redis_message_id"], message.encode())
        self.emit_after("enqueue", message, delay)
        return message


def build_broker(redis_url: str) -> Broker:
    """A Redis broker with the platform middleware. Does not become the global broker."""
    return StableIdRedisBroker(  # type: ignore[no-untyped-call]
        url=redis_url,
        middleware=[
            Prometheus(),
            AgeLimit(),
            TimeLimit(),
            ShutdownNotifications(),
            Callbacks(),
            Pipelines(),
            TenantContext(),
            TracebackMask(),  # before Retries: after-hooks run in reverse, so it sees the traceback Retries sets
            Retries(
                max_retries=MAX_RETRIES, min_backoff=MIN_BACKOFF_MS, max_backoff=MAX_BACKOFF_MS
            ),
            DeadLetter(),
        ],
    )


def get_broker() -> Broker:
    """The process-wide broker, built from settings on first use and installed as dramatiq's global broker."""
    global _broker
    with _lock:
        if _broker is None:
            _broker = build_broker(get_settings().redis_url)
            dramatiq.set_broker(_broker)
        return _broker


def declare_jobs(broker: Broker) -> None:
    """Declare every recorded job as an actor on `broker` (idempotent)."""
    for spec in _JOBS.values():
        if spec.name in broker.actors:
            continue
        dramatiq.actor(
            broker=broker,
            actor_name=spec.name,
            queue_name=spec.ref.queue,
            **spec.options,
        )(_discard_result(spec.fn))


def _discard_result(fn: Callable[..., Any]) -> Callable[..., None]:
    @functools.wraps(fn)
    def run(*args: Any, **kwargs: Any) -> None:
        fn(*args, **kwargs)

    return run


def enqueue(ref: JobRef, **kwargs: Any) -> Message[Any]:
    """Send one message for `ref`. `tenant_id` is required (the broker refuses messages without one)."""
    message: Message[Any] = Message(
        queue_name=ref.queue, actor_name=ref.name, args=(), kwargs=kwargs, options={}
    )
    return get_broker().enqueue(message)
