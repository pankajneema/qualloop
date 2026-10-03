"""Opaque server-side sessions in Redis (ADR-008, API.md 1.2).

Cookie `ql_session` = 32 random bytes (base64url). Redis key `sess:{sha256(token)}`: the token itself is never stored.
Idle timeout 8 h (sliding) and absolute lifetime 7 d are evaluated in Python from timestamps in the record; the Redis TTL
is only a backstop. `user_sessions:{user_id}` indexes a user's sessions so deactivation can end them all at once.

CSRF (double submit): `ql_csrf` is derived from the session token with HMAC, so a token from another session or one an
attacker invents never validates, even if the attacker can set a cookie on a sibling domain.
"""

import base64
import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import redis

from app.core.config import get_settings
from app.core.ids import new_id

SESSION_COOKIE = "ql_session"
CSRF_COOKIE = "ql_csrf"
CSRF_HEADER = "X-CSRF-Token"

IDLE_SECONDS = 8 * 3600
ABSOLUTE_SECONDS = 7 * 24 * 3600

_TOKEN = re.compile(r"^[A-Za-z0-9_-]{43}$")


@dataclass(frozen=True)
class SessionData:
    session_id: UUID
    user_id: UUID
    tenant_id: UUID
    created_at: float
    last_seen_at: float


def _now() -> float:
    return datetime.now(UTC).timestamp()


def session_key(token: str) -> str:
    return f"sess:{hashlib.sha256(token.encode()).hexdigest()}"


def _index_key(user_id: UUID) -> str:
    return f"user_sessions:{user_id}"


def csrf_token_for(session_token: str) -> str:
    digest = hmac.new(
        get_settings().session_secret.encode(), session_token.encode(), hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def csrf_matches(session_token: str, cookie_value: str | None, header_value: str | None) -> bool:
    """Double submit: header == cookie == the token derived from this session."""
    if not cookie_value or not header_value:
        return False
    expected = csrf_token_for(session_token)
    return hmac.compare_digest(cookie_value, expected) and hmac.compare_digest(
        header_value, expected
    )


def create_session(
    client: redis.Redis,
    *,
    user_id: UUID,
    tenant_id: UUID,
    ip: str | None,
    user_agent: str | None,
) -> tuple[str, SessionData]:
    token = secrets.token_urlsafe(32)
    now = _now()
    data = SessionData(
        session_id=new_id(), user_id=user_id, tenant_id=tenant_id, created_at=now, last_seen_at=now
    )
    record = {
        "session_id": str(data.session_id),
        "user_id": str(user_id),
        "tenant_id": str(tenant_id),
        "created_at": data.created_at,
        "last_seen_at": data.last_seen_at,
        "ip": ip,
        "ua": (user_agent or "")[:200],
    }
    key = session_key(token)
    pipe = client.pipeline()
    pipe.set(key, json.dumps(record), ex=IDLE_SECONDS)
    pipe.sadd(_index_key(user_id), key.removeprefix("sess:"))
    pipe.expire(_index_key(user_id), ABSOLUTE_SECONDS + IDLE_SECONDS)
    pipe.execute()
    return token, data


def load_session(client: redis.Redis, token: str | None) -> SessionData | None:
    """The live session for `token`, sliding the idle window; None if absent, malformed, idle- or age-expired."""
    if not token or not _TOKEN.match(token):
        return None
    key = session_key(token)
    raw = client.get(key)
    if raw is None:
        return None
    try:
        record = json.loads(raw)
        data = SessionData(
            session_id=UUID(record["session_id"]),
            user_id=UUID(record["user_id"]),
            tenant_id=UUID(record["tenant_id"]),
            created_at=float(record["created_at"]),
            last_seen_at=float(record["last_seen_at"]),
        )
    except (ValueError, KeyError, TypeError):
        client.delete(key)
        return None
    now = _now()
    if now - data.last_seen_at > IDLE_SECONDS or now - data.created_at > ABSOLUTE_SECONDS:
        _forget(client, key, data.user_id)
        return None
    record["last_seen_at"] = now
    client.set(key, json.dumps(record), ex=IDLE_SECONDS)
    return SessionData(data.session_id, data.user_id, data.tenant_id, data.created_at, now)


def _forget(client: redis.Redis, key: str, user_id: UUID) -> None:
    pipe = client.pipeline()
    pipe.delete(key)
    pipe.srem(_index_key(user_id), key.removeprefix("sess:"))
    pipe.execute()


def delete_session(client: redis.Redis, token: str | None, user_id: UUID | None = None) -> None:
    if not token or not _TOKEN.match(token):
        return
    key = session_key(token)
    if user_id is None:
        raw = client.get(key)
        if raw is not None:
            try:
                user_id = UUID(json.loads(raw)["user_id"])
            except (ValueError, KeyError, TypeError):
                user_id = None
    if user_id is None:
        client.delete(key)
    else:
        _forget(client, key, user_id)


def delete_user_sessions(client: redis.Redis, user_id: UUID) -> int:
    """End every session of a user (deactivation, password reset). Returns how many were indexed."""
    index = _index_key(user_id)
    members = [m.decode() if isinstance(m, bytes) else str(m) for m in client.smembers(index)]
    pipe = client.pipeline()
    for member in members:
        pipe.delete(f"sess:{member}")
    pipe.delete(index)
    pipe.execute()
    return len(members)
