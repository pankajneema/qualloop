"""Shared helpers for auth tests."""

import hashlib
import re
from typing import Any

import httpx
import redis as redis_lib


def set_cookie_headers(resp: httpx.Response) -> dict[str, str]:
    """Cookie name -> raw Set-Cookie header (lower-cased attributes), from one response."""
    out: dict[str, str] = {}
    for raw in resp.headers.get_list("set-cookie"):
        name = raw.split("=", 1)[0].strip()
        out[name] = raw.lower()
    return out


def session_key(token: str) -> str:
    return f"sess:{hashlib.sha256(token.encode()).hexdigest()}"


def redis_keys(client: redis_lib.Redis, pattern: str) -> list[str]:
    return sorted(str(k) for k in client.scan_iter(match=pattern, count=500))


def redis_values(client: redis_lib.Redis, key: str) -> list[str]:
    """All stored text of a key regardless of its Redis type (for 'secret not stored in clear' checks)."""
    kind = client.type(key)
    if kind == "string":
        return [str(client.get(key))]
    if kind == "hash":
        data: Any = client.hgetall(key)
        return [f"{k}={v}" for k, v in data.items()]
    if kind == "set":
        return [str(m) for m in client.smembers(key)]
    if kind == "list":
        return [str(v) for v in client.lrange(key, 0, -1)]
    if kind == "zset":
        zset: Any = client.zrange(key, 0, -1, withscores=True)
        return [str(item[0]) for item in zset]
    return []


OTP_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")


def strip_volatile(body: dict[str, Any]) -> dict[str, Any]:
    """Problem body without per-request fields, to compare 'same generic error' responses."""
    return {k: v for k, v in body.items() if k not in {"request_id", "instance"}}
