"""Dramatiq entrypoint: `dramatiq app.worker` (ADR-006).

Builds the process-wide broker (with the tenant, retry, dead-letter and Prometheus middleware), then imports every module
that records jobs and declares them as actors. The queues and their consumers (ARCHITECTURE 6.1) come from the jobs.
"""

import structlog

from app.core.config import get_settings
from app.core.jobs import build_broker, declare_jobs, get_broker
from app.core.logging import configure_logging
from app.core.telemetry import init_telemetry, instrument_engine, instrument_redis

settings = get_settings()
if not structlog.is_configured():
    configure_logging(settings.log_level, settings.env)
if init_telemetry(settings, service_name="qualloop-worker"):
    from app.core.db import get_engine

    instrument_engine(get_engine())
    instrument_redis()

broker = get_broker()

# Importing these records their jobs (queue names: ARCHITECTURE 6.1).
import app.core.auth.jobs  # noqa: E402
import app.core.files.jobs  # noqa: E402
import app.core.outbox.sweeper  # noqa: E402, F401

declare_jobs(broker)

__all__ = ["broker", "build_broker"]
