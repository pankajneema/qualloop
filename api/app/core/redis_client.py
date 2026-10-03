"""One shared Redis client per URL (sessions, OTPs, rate limits, idempotent sends, scheduler lock).

The URL names the ACL user `qualloop_app` (ADR-008, INV-SEC-08). Keys always use the documented prefixes
`sess:`, `user_sessions:`, `otp:`, `rl:`, `idem:`, `sched:` and `dramatiq:`; the ACL denies anything else.
"""

from functools import lru_cache

import redis

from app.core.config import get_settings


@lru_cache
def _client_for(url: str) -> redis.Redis:
    return redis.Redis.from_url(
        url,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=5,
        health_check_interval=30,
    )


def get_redis() -> redis.Redis:
    return _client_for(get_settings().redis_url)
