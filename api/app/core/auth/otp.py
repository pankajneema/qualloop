"""Password-reset one-time codes (ADR-008): 6 digits, hashed in Redis, TTL 15 min, 5 attempts, single use.

The code is derived from a per-request nonce with an HMAC under the server secret, so a retried job regenerates the SAME
code (the email send is idempotent per request) while the code cannot be computed from anything stored in Redis or the
job message. Redis holds only an HMAC of the code (`otp:pwreset:{user_id}`), never the code.
"""

import hashlib
import hmac
from uuid import UUID

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


def store(user_id: UUID, code: str) -> None:
    """Replace any earlier code of this user (a new request invalidates the old one)."""
    redis = get_redis()
    pipe = redis.pipeline()
    pipe.delete(_key(user_id))
    pipe.hset(
        _key(user_id), mapping={"mac": _mac("pwreset-verify", str(user_id), code), "attempts": 0}
    )
    pipe.expire(_key(user_id), TTL_SECONDS)
    pipe.execute()


def consume(user_id: UUID, code: str) -> bool:
    """True once for the right code; False for wrong, expired, burnt or already used codes (all look the same)."""
    redis = get_redis()
    key = _key(user_id)
    if not redis.exists(key):
        return False
    attempts = redis.hincrby(key, "attempts", 1)
    if attempts > MAX_ATTEMPTS:
        redis.delete(key)
        return False
    stored = redis.hget(key, "mac")
    if stored is None or not hmac.compare_digest(
        str(stored), _mac("pwreset-verify", str(user_id), code)
    ):
        return False
    return bool(redis.delete(key))  # atomic single use: only one caller sees 1
