"""ADR-011 / API.md 5 / INV-SEC-02, INV-DOC-10: POST /files/upload-url issues a presigned PUT to the quarantine
bucket. Real SeaweedFS (ADR-020)."""

import re
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import Engine

from tests.factories import s3
from tests.factories.api import ApiClient, ApiFactory, problem
from tests.factories.db import SeededTenant
from tests.factories.env import (
    MAX_UPLOAD_BYTES_CLEARLY_OK,
    MAX_UPLOAD_BYTES_CLEARLY_OVER,
    bucket_files,
    bucket_quarantine,
)
from tests.integration.files.helpers import PDF, expires_seconds

pytestmark = pytest.mark.integration

FIFTEEN_MINUTES = 15 * 60


def body(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "purpose": "document",
        "content_type": "application/pdf",
        "size": len(PDF),
    }
    base.update(over)
    return base


def quality_client(api: ApiFactory, t: SeededTenant) -> ApiClient:
    assert t.quality
    return api.login_as(t.quality)


def test_upload_url_returns_a_tenant_prefixed_key_a_url_and_an_expiry(
    api: ApiFactory, seeded: SeededTenant
) -> None:
    resp = quality_client(api, seeded).post("/files/upload-url", body())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert set(data) >= {"key", "url", "expires_at"}
    pattern = rf"^t/{seeded.id}/doc/[0-9a-f-]{{36}}/[0-9a-f]{{8}}-[0-9a-f]{{4}}-7[0-9a-f]{{3}}-[89ab][0-9a-f]{{3}}-[0-9a-f]{{12}}\.pdf$"
    assert re.match(pattern, data["key"]), data["key"]
    assert data["url"].startswith("http")
    assert bucket_quarantine() in data["url"] and bucket_files() not in data["url"]
    assert data["key"] in data["url"]


@pytest.mark.parametrize(
    ("purpose", "content_type", "kind", "ext"),
    [
        ("document", "application/pdf", "doc", "pdf"),
        ("document", "image/png", "doc", "png"),
        ("ncr_photo", "image/jpeg", "ncr", "jpg"),
        ("import", "text/csv", "import", "csv"),
    ],
)
def test_upload_url_key_kind_and_extension_follow_purpose_and_type(
    api: ApiFactory, seeded: SeededTenant, purpose: str, content_type: str, kind: str, ext: str
) -> None:
    resp = quality_client(api, seeded).post(
        "/files/upload-url", body(purpose=purpose, content_type=content_type)
    )
    assert resp.status_code == 200, resp.text
    assert re.match(rf"^t/{seeded.id}/{kind}/[^/]+/[^/]+\.{ext}$", resp.json()["key"])


def test_signed_url_expires_within_15_minutes(api: ApiFactory, seeded: SeededTenant) -> None:
    """INV-SEC-02 (upload side): both the stated expiry and the signature's own X-Amz-Expires are <= 15 min."""
    before = datetime.now(UTC)
    data = quality_client(api, seeded).post("/files/upload-url", body()).json()
    expires_at = datetime.fromisoformat(data["expires_at"])
    assert expires_at.tzinfo is not None
    assert before < expires_at <= datetime.now(UTC) + timedelta(seconds=FIFTEEN_MINUTES + 5)
    assert 0 < expires_seconds(data["url"]) <= FIFTEEN_MINUTES


def test_each_call_returns_a_distinct_key(api: ApiFactory, seeded: SeededTenant) -> None:
    client = quality_client(api, seeded)
    keys = {client.post("/files/upload-url", body()).json()["key"] for _ in range(4)}
    assert len(keys) == 4


def test_caller_cannot_choose_the_tenant_prefix(
    api: ApiFactory, seeded_pair: tuple[SeededTenant, SeededTenant]
) -> None:
    a, b = seeded_pair
    resp = quality_client(api, a).post(
        "/files/upload-url", body(tenant_id=str(b.id), key=f"t/{b.id}/doc/x/y.pdf")
    )
    if resp.status_code == 200:
        assert resp.json()["key"].startswith(f"t/{a.id}/")
    else:
        assert resp.status_code == 422


def test_presigned_put_stores_the_object_in_quarantine_not_in_the_files_bucket(
    api: ApiFactory, seeded: SeededTenant
) -> None:
    data = quality_client(api, seeded).post("/files/upload-url", body()).json()
    put = httpx.put(
        data["url"], content=PDF, headers={"Content-Type": "application/pdf"}, timeout=20
    )
    assert put.status_code in (200, 204), put.text
    assert s3.exists(bucket_quarantine(), data["key"])
    assert not s3.exists(bucket_files(), data["key"]), (
        "nothing is available before the scan promotes it"
    )
    assert s3.get(bucket_quarantine(), data["key"]) == PDF


def test_presigned_put_rejects_a_different_content_type_than_the_one_declared(
    api: ApiFactory, seeded: SeededTenant
) -> None:
    data = quality_client(api, seeded).post("/files/upload-url", body()).json()
    put = httpx.put(data["url"], content=PDF, headers={"Content-Type": "text/html"}, timeout=20)
    assert 400 <= put.status_code < 500
    assert not s3.exists(bucket_quarantine(), data["key"])


def test_presigned_put_rejects_a_body_of_a_different_length_than_declared(
    api: ApiFactory, seeded: SeededTenant
) -> None:
    data = quality_client(api, seeded).post("/files/upload-url", body(size=len(PDF))).json()
    put = httpx.put(
        data["url"],
        content=PDF + b"x" * 4096,
        headers={"Content-Type": "application/pdf"},
        timeout=20,
    )
    assert 400 <= put.status_code < 500
    assert not s3.exists(bucket_quarantine(), data["key"])


def test_upload_rejects_over_20_mb(api: ApiFactory, seeded: SeededTenant) -> None:
    resp = quality_client(api, seeded).post(
        "/files/upload-url", body(size=MAX_UPLOAD_BYTES_CLEARLY_OVER)
    )
    assert resp.status_code == 413
    assert problem(resp)["code"] == "payload_too_large"


def test_upload_accepts_a_file_just_under_20_mb(api: ApiFactory, seeded: SeededTenant) -> None:
    resp = quality_client(api, seeded).post(
        "/files/upload-url", body(size=MAX_UPLOAD_BYTES_CLEARLY_OK)
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize(
    "content_type",
    ["application/x-msdownload", "text/html", "image/gif", "application/zip", "image/svg+xml", ""],
)
def test_upload_rejects_wrong_content_type(
    api: ApiFactory, seeded: SeededTenant, content_type: str
) -> None:
    resp = quality_client(api, seeded).post("/files/upload-url", body(content_type=content_type))
    assert resp.status_code == 415, resp.text
    assert problem(resp)["code"] == "unsupported_media_type"


@pytest.mark.parametrize(
    "override",
    [
        {"purpose": "avatar"},
        {"purpose": "report"},
        {"purpose": ""},
        {"size": 0},
        {"size": -5},
        {"size": 12.5},
        {"size": "1234"},
        {"content_type": None},
    ],
    ids=[
        "unknown-purpose",
        "server-only-purpose",
        "empty-purpose",
        "zero",
        "negative",
        "float",
        "string",
        "no-type",
    ],
)
def test_upload_rejects_malformed_requests_with_422(
    api: ApiFactory, seeded: SeededTenant, override: dict[str, Any]
) -> None:
    resp = quality_client(api, seeded).post("/files/upload-url", body(**override))
    assert resp.status_code == 422, resp.text
    assert problem(resp)["code"] == "validation_error"


def test_unauthorised_user_cannot_get_signed_url(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine
) -> None:
    """INV-SEC-02: anonymous, viewer and supplier credentials all fail; admin and quality succeed."""
    assert seeded.viewer and seeded.admin
    assert api.anonymous().post("/files/upload-url", body(), csrf=False).status_code == 401
    assert api.login_as(seeded.viewer).post("/files/upload-url", body()).status_code == 403
    supplier = api.anonymous()
    supplier.http.cookies.set("ql_sup", "forged.supplier.cookie")
    assert supplier.post("/files/upload-url", body(), csrf=False).status_code == 401
    assert api.login_as(seeded.admin).post("/files/upload-url", body()).status_code == 200
    assert quality_client(api, seeded).post("/files/upload-url", body()).status_code == 200


def test_upload_url_requires_csrf_like_every_cookie_authenticated_post(
    api: ApiFactory, seeded: SeededTenant
) -> None:
    assert (
        quality_client(api, seeded).post("/files/upload-url", body(), csrf=False).status_code == 403
    )
