"""Keyset pagination helpers (API.md 1.5).

Cursor = base64url(JSON {"k": [last sort values..., last id], "s": "<sort name>"}) + "." + HMAC-SHA256 signature
(tamper-evident, keyed by `QL_HMAC_SECRET`). Sort is one of an endpoint's named sorts; ties are broken by the UUIDv7 id.
Limit is 1-200, default 50. No total counts.
"""

import base64
import hashlib
import hmac
import json
from typing import Annotated, Any

from fastapi import Query

from app.core.config import get_settings
from app.core.errors import BadRequest

DEFAULT_LIMIT = 50
MAX_LIMIT = 200

LimitParam = Annotated[int, Query(ge=1, le=MAX_LIMIT)]
CursorParam = Annotated[str | None, Query(max_length=1024)]


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(payload: str) -> str:
    key = get_settings().hmac_secret.encode()
    return _b64(hmac.new(key, payload.encode(), hashlib.sha256).digest())


def encode_cursor(keys: list[Any], sort: str) -> str:
    payload = _b64(json.dumps({"k": keys, "s": sort}, separators=(",", ":")).encode())
    return f"{payload}.{_sign(payload)}"


def decode_cursor(cursor: str, sort: str) -> list[Any]:
    """The keys of a cursor issued for `sort`; `BadRequest` for anything malformed, tampered or for another sort."""
    invalid = BadRequest("That page cursor is not valid. Start again from the first page.")
    payload, dot, signature = cursor.partition(".")
    if not dot or not hmac.compare_digest(signature, _sign(payload)):
        raise invalid
    try:
        data = json.loads(_unb64(payload))
        keys = data["k"]
        if data["s"] != sort or not isinstance(keys, list):
            raise invalid
    except (ValueError, KeyError, TypeError) as exc:
        raise invalid from exc
    return keys
