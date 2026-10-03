"""Outbox dispatcher process: `python -m app.dispatcher` (ADR-006). Polls `outbox_events` and enqueues handler jobs."""

import signal
import threading
from collections.abc import Callable

import structlog

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.outbox.dispatcher import ClaimedEvent, dispatch_once
from app.core.telemetry import init_telemetry, instrument_engine, instrument_redis

log = structlog.get_logger("dispatcher")

INTERVAL_SECONDS = 1.0


def run(
    stop: threading.Event,
    *,
    interval: float = INTERVAL_SECONDS,
    enqueue: Callable[[ClaimedEvent], None] | None = None,
    limit: int = 100,
) -> None:
    """Dispatch until `stop` is set. A failing cycle is logged and the loop carries on; a full batch loops at once."""
    while not stop.is_set():
        pause = interval
        try:
            result = dispatch_once(enqueue=enqueue, limit=limit)
            if result.processed + result.failed >= limit:
                pause = 0.0
        except Exception:
            log.error("dispatch_cycle_failed", exc_info=True)
        stop.wait(pause)


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.env)
    if init_telemetry(settings, service_name="qualloop-dispatcher"):
        from app.core.db import get_engine

        instrument_engine(get_engine())
        instrument_redis()
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    log.info("dispatcher_started")
    run(stop)
    log.info("dispatcher_stopped")


if __name__ == "__main__":
    main()
