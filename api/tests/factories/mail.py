"""Mailpit (local SMTP sink, REST on :8025) helpers."""

from typing import Any
from urllib.parse import quote

import httpx

from tests.factories.env import mailpit_url

TIMEOUT = 10.0


def clear() -> None:
    httpx.delete(f"{mailpit_url()}/api/v1/messages", timeout=TIMEOUT).raise_for_status()


def messages_to(address: str) -> list[dict[str, Any]]:
    resp = httpx.get(
        f"{mailpit_url()}/api/v1/search", params={"query": f"to:{quote(address)}"}, timeout=TIMEOUT
    )
    resp.raise_for_status()
    messages: list[dict[str, Any]] = resp.json()["messages"]
    return messages


def body_text(message_id: str) -> str:
    resp = httpx.get(f"{mailpit_url()}/api/v1/message/{message_id}", timeout=TIMEOUT)
    resp.raise_for_status()
    return str(resp.json()["Text"])


def headers(message_id: str) -> dict[str, list[str]]:
    resp = httpx.get(f"{mailpit_url()}/api/v1/message/{message_id}/headers", timeout=TIMEOUT)
    resp.raise_for_status()
    result: dict[str, list[str]] = resp.json()
    return result
