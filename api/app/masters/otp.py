"""Contact verification codes (A-78): 6 digits, hashed in Redis, TTL 10 min, 5 attempts, 3 sends per hour per contact.

The code derives from a per-request nonce under the server secret, so a retried send job regenerates the SAME code and
the code cannot be computed from anything in Redis or in the job message. Redis holds only an HMAC of the code under
`otp:contact:{contact_id}:{channel}`; the key carries no mobile number or email."""

import hashlib
import hmac
from uuid import UUID

import redis as redis_lib

from app.core.config import get_settings
from app.core.redis_client import get_redis

TTL_SECONDS = 10 * 60
MAX_ATTEMPTS = 5
SEND_LIMIT = 3
SEND_WINDOW_SECONDS = 3600


def _mac(label: str, *parts: str) -> str:
    key = get_settings().hmac_secret.encode()
    return hmac.new(key, ":".join((label, *parts)).encode(), hashlib.sha256).hexdigest()


def _key(contact_id: UUID, channel: str) -> str:
    return f"otp:contact:{contact_id}:{channel}"


def send_counter_key(contact_id: UUID) -> str:
    return f"rl:otp:send:{contact_id}"


def code_for_request(nonce: str, contact_id: UUID, channel: str) -> str:
    return f"{int(_mac('contact-code', nonce, str(contact_id), channel)[:12], 16) % 1_000_000:06d}"


def store(contact_id: UUID, channel: str, code: str, nonce: str) -> bool:
    """Make `code` the current code unless a code for a NEWER request is stored (nonces are UUIDv7, so they sort in
    request order). A late retry therefore cannot replace a newer code. Compare-and-set under WATCH."""
    redis = get_redis()
    key = _key(contact_id, channel)
    with redis.pipeline() as pipe:
        for _ in range(5):
            try:
                pipe.watch(key)  # type: ignore[no-untyped-call]
                current = pipe.hget(key, "nonce")
                if current is not None and str(current) > nonce:
                    pipe.unwatch()
                    return False
                pipe.multi()
                pipe.delete(key)
                pipe.hset(
                    key,
                    mapping={
                        "mac": _mac("contact-verify", str(contact_id), channel, code),
                        "attempts": 0,
                        "nonce": nonce,
                    },
                )
                pipe.expire(key, TTL_SECONDS)
                pipe.execute()
                return True
            except redis_lib.WatchError:
                continue
    raise RuntimeError("could not store the verification code: the key kept changing")


def attempt(contact_id: UUID, channel: str, code: str) -> bool:
    """One guess. True once for the right code; wrong, expired, burnt and never-requested codes all return False."""
    redis = get_redis()
    key = _key(contact_id, channel)
    if not redis.exists(key):
        return False
    pipe = redis.pipeline()
    pipe.hincrby(key, "attempts", 1)
    pipe.hget(key, "mac")
    pipe.expire(
        key, TTL_SECONDS, nx=True
    )  # a key re-created by HINCRBY after expiry still gets a TTL
    attempts, stored, _ = pipe.execute()
    if stored is None:
        return False
    if int(attempts) > MAX_ATTEMPTS:
        redis.delete(key)
        return False
    if not hmac.compare_digest(str(stored), _mac("contact-verify", str(contact_id), channel, code)):
        return False
    return bool(redis.delete(key))  # atomic single use
