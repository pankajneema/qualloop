"""Password-reset one-time codes (ADR-008): 6 digits, hashed in Redis, TTL 15 min, 5 attempts, single use.

The code is derived from a per-request nonce with an HMAC under the server secret, so a retried job regenerates the SAME
code (the email send is idempotent per request) while the code cannot be computed from anything stored in Redis or the
job message. Redis holds only an HMAC of the code (`otp:pwreset:{user_id}`), never the code.
"""

import hashlib
import hmac
from uuid import UUID

import redis as redis_lib

from app.core.config import get_settings
from app.core.redis_client import get_redis

TTL_SECONDS = 15 * 60
MAX_ATTEMPTS = 5


def _mac(label: str, *parts: str) -> str:
    key = get_settings().hmac_secret.encode()
    return hmac.new(key, ":".join((label, *parts)).encode(), hashlib.sha256).hexdigest()


def code_for_request(request_nonce: str, user_id: UUID) -> str:
    """The 6-digit code for one reset request."""
    return f"{int(_mac('pwreset-code', request_nonce, str(user_id))[:12], 16) % 1_000_000:06d}"


def _key(user_id: UUID) -> str:
    return f"otp:pwreset:{user_id}"


def store(user_id: UUID, code: str, nonce: str | None = None) -> bool:
    """Make `code` the user's current code (without a `nonce`: unconditionally), unless a code for a NEWER request is already stored.

    Request nonces are UUIDv7, so they sort in request order (lower-case hyphenated text compares like the number). A job
    that is redelivered or retried after a newer request was processed must not replace the newer code: it returns False
    and the caller sends nothing (the SAME nonce may store again: a retry after a failed send regenerates the same
    code). Compare-and-set under WATCH: a concurrent writer makes the transaction retry."""
    redis = get_redis()
    key = _key(user_id)
    with redis.pipeline() as pipe:
        for _ in range(5):
            try:
                pipe.watch(key)  # type: ignore[no-untyped-call]
                current = pipe.hget(key, "nonce")
                if nonce is not None and current is not None and str(current) > nonce:
                    pipe.unwatch()
                    return False
                pipe.multi()
                pipe.delete(key)
                pipe.hset(
                    key,
                    mapping={
                        "mac": _mac("pwreset-verify", str(user_id), code),
                        "attempts": 0,
                        "nonce": nonce or "",
                    },
                )
                pipe.expire(key, TTL_SECONDS)
                pipe.execute()
                return True
            except redis_lib.WatchError:
                continue
    raise RuntimeError("could not store the reset code: the key kept changing")


def has_live_code(user_id: UUID) -> bool:
    """True while a code is stored for the user (it may still turn out to be burnt or expired)."""
    return bool(get_redis().exists(_key(user_id)))


def attempt(user_id: UUID, code: str) -> str:
    """One guess: "none" (no live code, nothing was counted), "ok" (right, now used up) or "wrong".

    The attempt counter, the code and the TTL are handled in ONE MULTI/EXEC: `EXPIRE ... NX` gives any key that
    `HINCRBY` had to re-create (the code expired between the check and the increment) a TTL, so no `otp:` key can ever
    exist without one. Such a stray key has no `mac`, so it never verifies and reports "none"."""
    redis = get_redis()
    key = _key(user_id)
    if not redis.exists(key):
        return "none"
    pipe = redis.pipeline()
    pipe.hincrby(key, "attempts", 1)
    pipe.hget(key, "mac")
    pipe.expire(key, TTL_SECONDS, nx=True)
    attempts, stored, _ = pipe.execute()
    if stored is None:
        return "none"
    if int(attempts) > MAX_ATTEMPTS:
        redis.delete(key)
        return "wrong"
    if not hmac.compare_digest(str(stored), _mac("pwreset-verify", str(user_id), code)):
        return "wrong"
    return "ok" if redis.delete(key) else "none"  # atomic single use: only one caller sees 1


def consume(user_id: UUID, code: str) -> bool:
    """True once for the right code; False for wrong, expired, burnt or already used codes (all look the same)."""
    return attempt(user_id, code) == "ok"
