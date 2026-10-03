"""Redis counters for rate limits (API.md section 6, ADR-008): fixed windows, `rl:*` keys, TTL = window.

Keys never contain a raw email (they hold a SHA-256 of the lower-cased address) or any secret.
"""

import hashlib

from app.core.redis_client import get_redis


def key_part(value: str) -> str:
    """Stable, non-reversible key fragment for emails and other identifiers."""
    return hashlib.sha256(value.strip().lower().encode()).hexdigest()


def reserve(keys: list[str], *, limit: int, window_seconds: int) -> int:
    """Take one slot on every counter in `keys`, atomically, BEFORE the guarded work starts.

    Returns 0 when every counter is within `limit` (the slots stay taken), otherwise the seconds until the most
    restrictive exceeded counter resets. Counting first and comparing second (one MULTI/EXEC) means concurrent callers
    cannot all pass a "not blocked yet?" check. A refused call keeps its slot only on the counters that refused it; the
    others are given back, so a caller blocked by one key does not burn the budget of another (for example the email's)."""
    redis = get_redis()
    pipe = redis.pipeline()
    for key in keys:
        pipe.incr(key)
        pipe.expire(key, window_seconds, nx=True)
        pipe.ttl(key)
    values = pipe.execute()
    wait = 0
    within: list[str] = []
    for index, key in enumerate(keys):
        count, _, ttl = values[3 * index : 3 * index + 3]
        if int(count) > limit:
            wait = max(wait, int(ttl) if int(ttl) > 0 else window_seconds)
        else:
            within.append(key)
    if wait:
        release(within, window_seconds=window_seconds)
    return wait


def release(keys: list[str], *, window_seconds: int) -> None:
    """Give back one slot on each counter (a successful login does not count as a failure).

    `EXPIRE ... NX` after the decrement guarantees that a counter that expired in between is not left without a TTL."""
    if not keys:
        return
    pipe = get_redis().pipeline()
    for key in keys:
        pipe.decr(key)
        pipe.expire(key, window_seconds, nx=True)
    pipe.execute()
