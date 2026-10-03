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
# A clock that steps back by at most this much (NTP slew/step) is ignored: the last millisecond keeps counting up, so ids
# stay increasing. A bigger jump is taken at face value (a restored VM, a test moving time), so the embedded time keeps
# following the clock instead of freezing at a far-future value.
MAX_BACKWARD_CLAMP_MS = 1000


def new_id() -> UUID:
    """A new time-ordered UUIDv7, strictly greater than the previous one from this process unless the clock jumped
    back by more than `MAX_BACKWARD_CLAMP_MS`."""
    global _last_ms, _counter
    with _lock:
        ms = time.time_ns() // 1_000_000
        if ms < _last_ms and _last_ms - ms <= MAX_BACKWARD_CLAMP_MS:
            ms = _last_ms  # small backwards step: stay on the last millisecond
        if ms == _last_ms:
            if _counter < _COUNTER_MAX:
                _counter += 1
            else:  # 4096 ids in one millisecond: borrow the next one (RFC 9562 section 6.2, method 1)
                ms += 1
                _counter = secrets.randbits(11)
        else:
            # New millisecond: restart in the lower half so there is room to count up.
            _counter = secrets.randbits(11)
        _last_ms = ms
        counter = _counter
    value = (ms & 0xFFFFFFFFFFFF) << 80
    value |= 0x7 << 76
    value |= counter << 64
    value |= 0x2 << 62
    value |= secrets.randbits(62)
    return UUID(int=value)
