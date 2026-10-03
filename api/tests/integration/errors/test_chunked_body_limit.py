"""ADR-019 / API.md 1.4: a JSON body over 1 MB is 413 `payload_too_large`, also when the client streams it
chunked (no Content-Length), which used to surface as a 400 malformed-JSON error."""

from collections.abc import Iterator
from typing import cast

import httpx
import pytest

from tests.factories.api import ApiClient, ApiFactory, problem
from tests.factories.db import SeededTenant
from tests.factories.env import API, origin
from tests.integration.commands.test_platform_commands_api import admin_client

pytestmark = pytest.mark.integration

MB = 1024 * 1024


def chunked_json(total: int, chunk: int = 64 * 1024) -> Iterator[bytes]:
    """A valid-looking JSON object streamed in pieces, `total` bytes overall."""
    yield b'{"name": "'
    sent = 11
    filler = b"x" * chunk
    while sent < total - 30:
        piece = filler[: min(chunk, total - 30 - sent)]
        yield piece
        sent += len(piece)
    yield b'", "code": "CHUNK1"}'


def post_stream(client: ApiClient, body: Iterator[bytes]) -> httpx.Response:
    headers = {
        "Origin": origin(),
        "X-CSRF-Token": client.csrf_token or "",
        "Content-Type": "application/json",
    }
    return cast(httpx.Response, client.http.post(f"{API}/plants", content=body, headers=headers))


def test_a_chunked_body_over_one_megabyte_is_413_payload_too_large(
    api: ApiFactory, seeded: SeededTenant
) -> None:
    admin = admin_client(api, seeded)
    resp = post_stream(admin, chunked_json(2 * MB))
    assert resp.status_code == 413, resp.text
    assert problem(resp)["code"] == "payload_too_large"


def test_a_chunked_body_far_over_the_limit_is_413_too(
    api: ApiFactory, seeded: SeededTenant
) -> None:
    resp = post_stream(admin_client(api, seeded), chunked_json(12 * MB))
    assert resp.status_code == 413, resp.text


def test_the_request_is_not_processed_after_a_chunked_413(
    api: ApiFactory, seeded: SeededTenant
) -> None:
    admin = admin_client(api, seeded)
    assert post_stream(admin, chunked_json(2 * MB)).status_code == 413
    plants = admin.get("/plants").json()["items"]
    assert "CHUNK1" not in {p["code"] for p in plants}


def test_a_chunked_body_under_the_limit_is_processed(api: ApiFactory, seeded: SeededTenant) -> None:
    small = iter([b'{"name": "Chunked ', b'Plant", "code": ', b'"CHUNK2"}'])
    resp = post_stream(admin_client(api, seeded), small)
    assert resp.status_code in (200, 201), resp.text
