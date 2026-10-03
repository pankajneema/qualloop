"""Scheduler process: `python -m app.scheduler` (ADR-006 item 1). Enqueues cron work; it never does the work itself.

Exactly one scheduler acts at a time: the instance that holds the Redis key `sched:leader` (SET NX, TTL 30 s, renewed
every tick). Others keep trying and take over when the leader stops or its lock expires. Per-tenant jobs fan out over
`app_active_tenant_ids()` (ADR-004).
"""

import os
import signal
import socket
import threading
import time
from collections.abc import Callable
from uuid import UUID, uuid4

import redis
import structlog
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import get_engine
from app.core.jobs import enqueue
from app.core.logging import configure_logging
from app.core.outbox.sweeper import SWEEP_PENDING
from app.core.redis_client import get_redis
from app.core.telemetry import init_telemetry, instrument_engine, instrument_redis

log = structlog.get_logger("scheduler")

LEADER_KEY = "sched:leader"
LEADER_TTL_SECONDS = 30
TICK_SECONDS = 5.0

_RELEASE = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"
_RENEW = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('expire', KEYS[1], ARGV[2]) else return 0 end"


def acquire_leader(client: redis.Redis, instance_id: str) -> bool:
    return bool(client.set(LEADER_KEY, instance_id, nx=True, ex=LEADER_TTL_SECONDS))


def renew_leader(client: redis.Redis, instance_id: str) -> bool:
    return bool(client.eval(_RENEW, 1, LEADER_KEY, instance_id, LEADER_TTL_SECONDS))


def release_leader(client: redis.Redis, instance_id: str) -> None:
    client.eval(_RELEASE, 1, LEADER_KEY, instance_id)


def fan_out(send: Callable[[UUID], None]) -> int:
    """Call `send(tenant_id)` once per tenant; returns how many succeeded. A failure for one tenant does not stop the rest."""
    with get_engine().connect() as conn:
        tenant_ids = [row[0] for row in conn.execute(text("SELECT app_active_tenant_ids()"))]
    sent = 0
    for tenant_id in tenant_ids:
        try:
            send(tenant_id)
            sent += 1
        except Exception:
            log.error("fan_out_failed", tenant_id=str(tenant_id), exc_info=True)
    return sent


def run(
    stop: threading.Event,
    *,
    instance_id: str,
    redis: redis.Redis,
    tick: float,
    on_leader_tick: Callable[[], None],
) -> None:
    """Hold or contend for leadership; call `on_leader_tick` only while holding the lock; release it on a clean stop."""
    leader = False
    try:
        while not stop.is_set():
            try:
                leader = renew_leader(redis, instance_id) if leader else False
                if not leader:
                    leader = acquire_leader(redis, instance_id)
                if leader:
                    on_leader_tick()
            except Exception:
                leader = False
                log.error("scheduler_tick_failed", exc_info=True)
            stop.wait(tick)
    finally:
        try:
            release_leader(redis, instance_id)
        except Exception:
            log.error("scheduler_release_failed", exc_info=True)


class LeaderState:
    """Lets APScheduler jobs ask 'am I the leader right now?': true while leader ticks keep arriving."""

    def __init__(self, tick: float) -> None:
        self._grace = tick * 3
        self._last = float("-inf")

    def mark(self) -> None:
        self._last = time.monotonic()

    def is_leader(self) -> bool:
        return time.monotonic() - self._last <= self._grace


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.env)
    if init_telemetry(settings, service_name="qualloop-scheduler"):
        instrument_engine(get_engine())
        instrument_redis()
    state = LeaderState(TICK_SECONDS)
    scheduler = BackgroundScheduler(timezone="UTC")

    def send_sweep(tenant_id: UUID) -> None:
        enqueue(SWEEP_PENDING, tenant_id=str(tenant_id))

    def sweep() -> None:
        if state.is_leader():
            count = fan_out(send_sweep)
            log.info("scheduled_job_enqueued", job=SWEEP_PENDING.name, tenants=count)

    scheduler.add_job(
        sweep, "interval", minutes=5, id=SWEEP_PENDING.name, coalesce=True, max_instances=1
    )
    scheduler.start()
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    instance_id = f"{socket.gethostname()}-{os.getpid()}-{uuid4().hex[:8]}"
    log.info("scheduler_started", instance=instance_id)
    try:
        run(
            stop,
            instance_id=instance_id,
            redis=get_redis(),
            tick=TICK_SECONDS,
            on_leader_tick=state.mark,
        )
    finally:
        scheduler.shutdown(wait=False)
    log.info("scheduler_stopped")


if __name__ == "__main__":
    main()
