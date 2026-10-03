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
from app.core.jobs.middleware import DeadLetter, Prometheus, TenantContext

# Blueprint 22.2: "dead-letter after 5 attempts". dramatiq counts RETRIES: max_retries=N means N + 1 executions, so
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
    options: dict[str, Any] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.ref.name


_JOBS: dict[str, JobSpec] = {}
_broker: Broker | None = None
_lock = threading.Lock()


def job(ref: JobRef, **options: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Record a job. The decorated function is returned unchanged, so it stays directly callable in tests."""

    def register(fn: Callable[..., Any]) -> Callable[..., Any]:
        if ref.name in _JOBS and _JOBS[ref.name].fn is not fn:
            raise ValueError(f"job {ref.name!r} is already registered")
        _JOBS[ref.name] = JobSpec(ref=ref, fn=fn, options=dict(options))
        return fn

    return register


def registered_jobs() -> dict[str, JobSpec]:
    return dict(_JOBS)


def build_broker(redis_url: str) -> Broker:
    """A Redis broker with the platform middleware. Does not become the global broker."""
    return RedisBroker(  # type: ignore[no-untyped-call]
        url=redis_url,
        middleware=[
            Prometheus(),
            AgeLimit(),
            TimeLimit(),
            ShutdownNotifications(),
            Callbacks(),
            Pipelines(),
            TenantContext(),
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
