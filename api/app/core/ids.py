"""UUIDv7 identifiers (ADR-005, RFC 9562).

48-bit unix milliseconds | version 7 | 12-bit counter | variant | 62 random bits.

Ids created within one millisecond keep their creation order through the counter, so keyset pagination on `id`
is stable. Unlike the `uuid6` package, no process-global "last timestamp" is kept: the embedded time always follows
the clock (which time-travelling tests rely on); only ids from the same millisecond are ordered by the counter.
"""

import secrets
import threading
import time
from uuid import UUID

_lock = threading.Lock()
_last_ms = -1
_counter = 0

_COUNTER_MAX = (1 << 12) - 1


def new_id() -> UUID:
    """A new time-ordered UUIDv7."""
    global _last_ms, _counter
    with _lock:
        ms = time.time_ns() // 1_000_000
        if ms == _last_ms and _counter < _COUNTER_MAX:
            _counter += 1
        else:
            # New millisecond (or counter exhausted): restart in the lower half so there is room to count up.
            _counter = secrets.randbits(11)
            if ms == _last_ms:  # more than 4096 ids in one ms: borrow the next millisecond
                ms += 1
        _last_ms = ms
        counter = _counter
    value = (ms & 0xFFFFFFFFFFFF) << 80
    value |= 0x7 << 76
    value |= counter << 64
    value |= 0x2 << 62
    value |= secrets.randbits(62)
    return UUID(int=value)
