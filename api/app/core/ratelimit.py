"""Redis counters for rate limits (API.md section 6, ADR-008): fixed windows, `rl:*` keys, TTL = window.

Keys never contain a raw email (they hold a SHA-256 of the lower-cased address) or any secret.
"""

import hashlib

from app.core.errors import RateLimited
from app.core.redis_client import get_redis


def key_part(value: str) -> str:
    """Stable, non-reversible key fragment for emails and other identifiers."""
    return hashlib.sha256(value.strip().lower().encode()).hexdigest()


def hit(key: str, *, limit: int, window_seconds: int) -> None:
    """Count one event; raise `RateLimited` when it exceeds `limit` within the window."""
    redis = get_redis()
    pipe = redis.pipeline()
    pipe.incr(key)
    pipe.expire(key, window_seconds, nx=True)
    pipe.ttl(key)
    count, _, ttl = pipe.execute()
    if int(count) > limit:
        raise RateLimited(retry_after=ttl if int(ttl) > 0 else window_seconds)


def blocked_for(keys: list[str], *, limit: int) -> int:
    """Seconds until the most restrictive counter among `keys` that has reached `limit` resets; 0 = not blocked."""
    redis = get_redis()
    pipe = redis.pipeline()
    for key in keys:
        pipe.get(key)
        pipe.ttl(key)
    values = pipe.execute()
    wait = 0
    for index in range(0, len(values), 2):
        count, ttl = values[index], values[index + 1]
        if count is not None and int(count) >= limit:
            wait = max(wait, int(ttl) if int(ttl) > 0 else 1)
    return wait


def record(keys: list[str], *, window_seconds: int) -> None:
    """Count one event on every key (the window starts at the first event)."""
    redis = get_redis()
    pipe = redis.pipeline()
    for key in keys:
        pipe.incr(key)
        pipe.expire(key, window_seconds, nx=True)
    pipe.execute()
