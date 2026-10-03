"""Dramatiq helpers: run a worker in-process on private queues of the test Redis database."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

from tests.factories.contract import load


def unique_queue() -> str:
    # Private queue: the dev stack's worker (Redis db 0) can never see it, and neither can other tests.
    return f"zz_test_{uuid4().hex[:10]}"


def make_actor(broker: Any, fn: Callable[..., Any], *, queue: str, **options: Any) -> Any:
    dramatiq = load("dramatiq")
    return dramatiq.actor(
        fn, broker=broker, queue_name=queue, actor_name=f"zz_{uuid4().hex[:10]}", **options
    )


@contextmanager
def running_worker(broker: Any, queues: set[str], threads: int = 2) -> Iterator[Any]:
    dramatiq = load("dramatiq")
    worker = dramatiq.Worker(broker, queues=queues, worker_threads=threads, worker_timeout=100)
    worker.start()
    try:
        yield worker
    finally:
        worker.stop()


def wait_idle(broker: Any, worker: Any, queues: set[str], timeout_ms: int = 30_000) -> None:
    """Explicit synchronisation: block until the queues (and delay queues) are drained and idle."""
    for queue in queues:
        broker.join(queue, timeout=timeout_ms)
    worker.join()


def declared_queues(broker: Any) -> set[str]:
    """Base queue names of every actor registered on the broker (delay/dead-letter variants excluded)."""
    return {q for q in broker.get_declared_queues() if not q.endswith((".DQ", ".XQ"))}
