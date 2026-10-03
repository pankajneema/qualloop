"""Dramatiq middleware: tenant context per job, durable dead letters (ADR-004, ADR-006, A-89).

* `TenantContext`  every message must carry `tenant_id` (a UUID string) as a keyword argument; messages without a valid
  one are refused at enqueue time and, if one still arrives, failed without running the actor. The actor body runs inside
  `tenant_tx(tenant_id, "system")`, reached through `current_session()`; a job declared with `own_transaction=True`
  runs with the tenant context bound but no open transaction and opens short ones itself (no I/O inside a transaction).
* `DeadLetter`     when a message is rejected after its retries are exhausted, one `job_dead_letters` row is written under
  the job's tenant and an alert log line (`job_dead_lettered`) is emitted.
"""

import functools
import json
import threading
from collections.abc import Callable
from typing import Any
from uuid import UUID

import structlog
from dramatiq import Actor, Broker, Message
from dramatiq.broker import MessageProxy
from dramatiq.middleware import Middleware
from dramatiq.middleware.middleware import MiddlewareError
from dramatiq.middleware.prometheus import Prometheus as DramatiqPrometheus
from sqlalchemy import text

from app.core.db import tenant_tx
from app.core.ids import new_id
from app.core.logging import bind_actor_context, clear_request_context, mask_text

log = structlog.get_logger("jobs")

MAX_ERROR_CHARS = 4000


class InvalidJob(MiddlewareError):
    """Raised at enqueue time for a message that must never be sent (no tenant)."""


def parse_tenant(value: Any) -> UUID | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


class TenantContext(Middleware):
    """Per-job tenant isolation (INV-PLT-03)."""

    @property
    def actor_options(self) -> set[str]:
        return {"own_transaction"}

    def __init__(self) -> None:
        self._wrapped: set[int] = set()
        self._lock = threading.Lock()

    def before_enqueue(self, broker: Broker, message: Message[Any], delay: int | None) -> None:
        if parse_tenant(message.kwargs.get("tenant_id")) is None:
            raise InvalidJob(
                f"job {message.actor_name} needs a tenant_id keyword argument (a UUID string)"
            )

    def before_process_message(self, broker: Broker, message: MessageProxy) -> None:
        if parse_tenant(message.kwargs.get("tenant_id")) is None:
            log.critical(
                "job_rejected_missing_tenant",
                actor_name=message.actor_name,
                queue=message.queue_name,
                message_id=message.message_id,
            )
            message.fail()  # the actor never runs; the message goes to the dead-letter queue untouched

    def after_declare_actor(self, broker: Broker, actor: Actor[Any, Any]) -> None:
        with self._lock:
            if id(actor) in self._wrapped:
                return
            self._wrapped.add(id(actor))
        actor.fn = _in_tenant_tx(
            actor.fn, actor.actor_name, own_transaction=bool(actor.options.get("own_transaction"))
        )


def _in_tenant_tx(
    fn: Callable[..., Any], actor_name: str, *, own_transaction: bool = False
) -> Callable[..., Any]:
    @functools.wraps(fn)
    def run(*args: Any, **kwargs: Any) -> Any:
        tenant_id = parse_tenant(kwargs.get("tenant_id"))
        if tenant_id is None:  # defence in depth: before_process_message already refuses these
            raise InvalidJob(f"job {actor_name} has no valid tenant_id")
        bind_actor_context(tenant_id=str(tenant_id), actor_type="system", user_id=None)
        structlog.contextvars.bind_contextvars(job=actor_name)
        try:
            if (
                own_transaction
            ):  # the job opens its own short transactions (no I/O inside a transaction)
                return fn(*args, **kwargs)
            with tenant_tx(tenant_id, actor_type="system"):
                return fn(*args, **kwargs)
        finally:
            clear_request_context()

    return run


_dead_lettered: Any = None
_dead_lettered_lock = threading.Lock()


def _dead_lettered_counter() -> Any:
    """`qualloop_jobs_dead_lettered_total{queue,actor}`, created on first use.

    `prometheus_client` is imported lazily on purpose (see `Prometheus` below and the outbox dispatcher): dramatiq must set
    its multiprocess directory before the library is first imported in a worker process."""
    global _dead_lettered
    from prometheus_client import Counter

    with _dead_lettered_lock:
        if _dead_lettered is None:
            _dead_lettered = Counter(
                "qualloop_jobs_dead_lettered",
                "Jobs that exhausted their attempts and were dead-lettered.",
                ["queue", "actor"],
            )
        return _dead_lettered


class TracebackMask(Middleware):
    """Dramatiq's `Retries` stores `options["traceback"]` on a failed message, and that message is kept in Redis (retry
    queue, dead-letter queue). Exception text can hold an email or mobile number (for example a database DETAIL line), so
    the traceback is masked like every log value. Listed BEFORE `Retries`: `after_*` hooks run in reverse order, so this
    one sees the traceback after `Retries` set it and before the message is nacked or re-enqueued."""

    @staticmethod
    def _mask(message: Any) -> None:
        trace = message.options.get("traceback")
        if isinstance(trace, str):
            message.options["traceback"] = mask_text(trace)

    def before_enqueue(self, broker: Broker, message: Message[Any], delay: int | None) -> None:
        self._mask(message)

    def after_process_message(
        self,
        broker: Broker,
        message: MessageProxy,
        *,
        result: Any = None,
        exception: BaseException | None = None,
    ) -> None:
        self._mask(message)


class DeadLetter(Middleware):
    """Durable dead letters (INV-PLT-20): Redis may lose its DLQ, Postgres keeps the record."""

    _MAX_PENDING_ERRORS = 10_000

    def __init__(self) -> None:
        self._errors: dict[str, str] = {}
        self._lock = threading.Lock()

    def after_process_message(
        self,
        broker: Broker,
        message: MessageProxy,
        *,
        result: Any = None,
        exception: BaseException | None = None,
    ) -> None:
        with self._lock:
            if exception is None:
                self._errors.pop(message.message_id, None)
                return
            if len(self._errors) >= self._MAX_PENDING_ERRORS:
                self._errors.clear()
            # Exception text only (tracebacks stay out of the database), with emails and mobiles masked: database
            # errors repeat the offending value in their DETAIL line.
            self._errors[message.message_id] = mask_text(
                f"{type(exception).__name__}: {exception}"
            )[:MAX_ERROR_CHARS]

    def after_ack(self, broker: Broker, message: MessageProxy) -> None:
        with self._lock:
            self._errors.pop(message.message_id, None)

    def after_nack(self, broker: Broker, message: MessageProxy) -> None:
        with self._lock:
            error = self._errors.pop(message.message_id, None)
        tenant_id = parse_tenant(message.kwargs.get("tenant_id"))
        if tenant_id is None:
            return  # already logged by TenantContext; there is no tenant to attribute a row to
        attempts = int(message.options.get("retries", 1))
        event_id = parse_tenant(message.kwargs.get("event_id"))
        try:
            with tenant_tx(tenant_id, actor_type="system") as session:
                session.execute(
                    text(
                        "INSERT INTO job_dead_letters (id, tenant_id, queue, actor_name, message_id, event_id, "
                        "payload, attempts, last_error, dead_lettered_at) "
                        "VALUES (:id, :tenant_id, :queue, :actor_name, :message_id, :event_id, "
                        "CAST(:payload AS jsonb), :attempts, :last_error, now()) "
                        "ON CONFLICT (tenant_id, message_id) DO NOTHING"
                    ),
                    {
                        "id": new_id(),
                        "tenant_id": tenant_id,
                        "queue": message.queue_name,
                        "actor_name": message.actor_name,
                        "message_id": message.message_id,
                        "event_id": event_id,
                        "payload": json.dumps(message.kwargs, default=str).replace("\\u0000", ""),
                        "attempts": max(attempts, 1),
                        "last_error": (error or "unknown error").replace("\x00", ""),
                    },
                )
        except Exception:
            log.critical(
                "job_dead_letter_not_recorded",
                message_id=message.message_id,
                actor_name=message.actor_name,
                tenant_id=str(tenant_id),
                exc_info=True,
            )
        _dead_lettered_counter().labels(queue=message.queue_name, actor=message.actor_name).inc()
        log.error(
            "job_dead_lettered",
            message_id=message.message_id,
            actor_name=message.actor_name,
            tenant_id=str(tenant_id),
            queue=message.queue_name,
            attempts=attempts,
        )


class Prometheus(DramatiqPrometheus):
    """dramatiq's Prometheus middleware, usable without the worker CLI.

    dramatiq creates the metrics in `after_process_boot`, which only the `dramatiq` CLI calls; a broker consumed by an
    in-process `Worker` (tests, scripts) would otherwise fail on every hook. Metrics are created on first use instead.
    The name is kept so the middleware list reads as documented (ADR-006, ADR-015)."""

    _ready = False

    def after_process_boot(self, broker: Broker) -> None:
        super().after_process_boot(broker)  # type: ignore[no-untyped-call]
        self._ready = True

    def ensure_ready(self, broker: Broker) -> None:
        if not self._ready:
            self.after_process_boot(broker)


def _lazy_hook(name: str) -> Callable[..., Any]:
    parent = getattr(DramatiqPrometheus, name)

    def hook(self: Prometheus, broker: Broker, *args: Any, **kwargs: Any) -> Any:
        self.ensure_ready(broker)
        return parent(self, broker, *args, **kwargs)

    hook.__name__ = name
    return hook


for _hook in (
    "before_process_message",
    "after_process_message",
    "after_skip_message",
    "after_nack",
    "after_enqueue",
    "before_delay_message",
):
    setattr(Prometheus, _hook, _lazy_hook(_hook))
