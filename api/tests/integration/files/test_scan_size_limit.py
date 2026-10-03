"""A-97 / ADR-011 / blueprint 20.2: uploads are at most 20,000,000 bytes. The presigned PUT is bounded by what the client
declares, not by what it sends, so the scanner must check the real object size itself and never download an oversized
object (memory) or feed it to ClamAV."""

from collections.abc import Iterator
from typing import Any

import pytest

from app.core.config import get_settings
from tests.factories import s3
from tests.factories.contract import load
from tests.factories.db import SeededTenant
from tests.factories.env import bucket_files, bucket_quarantine
from tests.integration.files.helpers import PDF, new_key

pytestmark = pytest.mark.integration

LIMIT = 20_000_000


@pytest.fixture(autouse=True)
def _fresh_settings(engine_env: None) -> Iterator[None]:
    yield
    get_settings.cache_clear()


@pytest.fixture
def s3_operations(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Names of every S3 API call made by any boto3 client in this process, while the test runs."""
    from botocore.client import BaseClient

    seen: list[str] = []
    original = BaseClient._make_api_call

    def recording(self: Any, operation_name: str, api_params: Any) -> Any:
        seen.append(operation_name)
        return original(self, operation_name, api_params)

    monkeypatch.setattr(BaseClient, "_make_api_call", recording)
    return seen


def oversized_pdf(size: int) -> bytes:
    return PDF + b"\x00" * (size - len(PDF))


def test_an_object_larger_than_20_000_000_bytes_is_quarantined_as_too_large_without_download_or_scan(
    seeded: SeededTenant, monkeypatch: pytest.MonkeyPatch, s3_operations: list[str]
) -> None:
    key = new_key(seeded.id, "doc", "pdf")
    s3.put_quarantine(key, oversized_pdf(LIMIT + 1), "application/pdf")
    scanner = load("app.core.files.scanner")
    scanned: list[int] = []

    def refuse(data: bytes) -> None:
        scanned.append(len(data))
        raise AssertionError("an oversized object must never be sent to ClamAV")

    monkeypatch.setattr(scanner, "scan_bytes", refuse)
    s3_operations.clear()

    result = scanner.scan_quarantined(seeded.id, key)

    assert result.status == "quarantined"
    assert result.reason == "too_large"
    assert result.sha256 is None
    assert scanned == [], "ClamAV was fed the oversized object"
    assert "GetObject" not in s3_operations, f"the oversized object was downloaded: {s3_operations}"
    assert "CopyObject" not in s3_operations and "PutObject" not in s3_operations
    assert not s3.exists(bucket_files(), key), "never promoted"
    assert s3.exists(bucket_quarantine(), key), "kept in quarantine like other rejected uploads"


def test_the_files_scan_job_does_not_retry_an_oversized_object(seeded: SeededTenant) -> None:
    """Too large is a final verdict, not a transient failure: the call returns, it does not raise (which would retry)."""
    key = new_key(seeded.id, "doc", "pdf")
    s3.put_quarantine(key, oversized_pdf(LIMIT + 1024), "application/pdf")
    result = load("app.core.files.scanner", "scan_quarantined")(seeded.id, key)
    assert (result.status, result.reason) == ("quarantined", "too_large")
