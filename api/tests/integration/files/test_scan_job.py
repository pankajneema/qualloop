"""ADR-011 items 3-4 / INV-DOC-10: the files.scan job. Magic-byte sniff, ClamAV INSTREAM, SHA-256, promote
quarantine -> files, fail closed. Needs the ClamAV container (A-47) and SeaweedFS."""

import contextlib
import hashlib
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
import redis as redis_lib

from app.core.config import get_settings
from tests.factories import s3
from tests.factories.contract import load
from tests.factories.db import SeededTenant
from tests.factories.env import bucket_files, bucket_quarantine
from tests.factories.jobs import running_worker, wait_idle
from tests.integration.files.helpers import JPEG, PDF, PNG, eicar, new_key

pytestmark = pytest.mark.integration


def scan(tenant: Any, key: str) -> Any:
    return load("app.core.files.scanner", "scan_quarantined")(tenant, key)


def quarantined_upload(
    tenant: SeededTenant, data: bytes, content_type: str, ext: str = "pdf"
) -> str:
    key = new_key(tenant.id, "doc", ext)
    s3.put_quarantine(key, data, content_type)
    return key


@pytest.fixture(autouse=True)
def _fresh_settings(engine_env: None) -> Iterator[None]:
    yield
    get_settings.cache_clear()


def test_clamav_flags_the_eicar_test_string_and_passes_clean_bytes() -> None:
    scan_bytes = load("app.core.files.scanner", "scan_bytes")
    bad = scan_bytes(eicar())
    assert bad.infected is True
    assert "eicar" in str(bad.signature).lower()
    good = scan_bytes(PDF)
    assert good.infected is False and good.signature is None


@pytest.mark.parametrize(
    ("data", "ctype", "ext"),
    [(PDF, "application/pdf", "pdf"), (JPEG, "image/jpeg", "jpg"), (PNG, "image/png", "png")],
)
def test_clean_file_promoted_with_sha256(
    seeded: SeededTenant, data: bytes, ctype: str, ext: str
) -> None:
    key = quarantined_upload(seeded, data, ctype, ext)
    result = scan(seeded.id, key)
    assert result.status == "available"
    assert result.sha256 == hashlib.sha256(data).hexdigest()
    assert s3.get(bucket_files(), key) == data, "promoted under the same key"
    assert not s3.exists(bucket_quarantine(), key), "removed from quarantine after promotion"


def test_eicar_upload_is_quarantined_and_never_reaches_the_files_bucket(
    seeded: SeededTenant,
) -> None:
    key = quarantined_upload(seeded, eicar(), "application/pdf")
    result = scan(seeded.id, key)
    assert result.status == "quarantined"
    assert result.sha256 is None
    assert not s3.exists(bucket_files(), key)
    assert s3.exists(bucket_quarantine(), key), "evidence stays in quarantine (7 day lifecycle)"


def test_a_file_whose_magic_bytes_disagree_with_its_declared_type_is_quarantined(
    seeded: SeededTenant,
) -> None:
    key = quarantined_upload(seeded, JPEG, "application/pdf")  # a JPEG labelled as PDF
    result = scan(seeded.id, key)
    assert result.status == "quarantined"
    assert result.reason == "content_type_mismatch"
    assert not s3.exists(bucket_files(), key)


def test_an_executable_labelled_as_pdf_is_quarantined(seeded: SeededTenant) -> None:
    key = quarantined_upload(
        seeded, b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 64, "application/pdf"
    )
    assert scan(seeded.id, key).status == "quarantined"
    assert not s3.exists(bucket_files(), key)


def test_scan_fails_closed_when_clamav_is_unreachable(
    seeded: SeededTenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = quarantined_upload(seeded, PDF, "application/pdf")
    monkeypatch.setenv("QL_CLAMAV_PORT", "1")  # nothing listens here
    get_settings.cache_clear()
    raised = False
    try:
        scan(seeded.id, key)
    except Exception:
        raised = True
    assert raised, "an unscanned file must make the job fail (and retry), never pass"
    assert not s3.exists(bucket_files(), key)
    assert s3.exists(bucket_quarantine(), key)


def test_scan_refuses_a_key_under_another_tenants_prefix(
    seeded_pair: tuple[SeededTenant, SeededTenant],
) -> None:
    a, b = seeded_pair
    key = quarantined_upload(b, PDF, "application/pdf")
    with pytest.raises(load("app.core.errors", "NotFound")):
        scan(a.id, key)
    assert s3.exists(bucket_quarantine(), key) and not s3.exists(bucket_files(), key)


def test_scan_of_a_missing_object_is_not_found(seeded: SeededTenant) -> None:
    with pytest.raises(load("app.core.errors", "NotFound")):
        scan(seeded.id, new_key(seeded.id))


def test_scan_is_idempotent_when_the_message_is_redelivered(seeded: SeededTenant) -> None:
    key = quarantined_upload(seeded, PDF, "application/pdf")
    first = scan(seeded.id, key)
    again = scan(seeded.id, key)  # quarantine copy is gone, the promoted copy exists
    assert first.status == again.status == "available"
    assert again.sha256 == first.sha256
    assert s3.get(bucket_files(), key) == PDF


def test_files_scan_actor_promotes_the_object_through_the_worker(
    seeded: SeededTenant, redis_client: redis_lib.Redis
) -> None:
    broker = load("app.worker", "broker")
    key = quarantined_upload(seeded, PDF, "application/pdf")
    queues = {"ai"}
    with running_worker(broker, queues) as worker:
        broker.get_actor("files.scan").send(tenant_id=str(seeded.id), key=key)
        wait_idle(broker, worker, queues)
    assert s3.exists(bucket_files(), key) and not s3.exists(bucket_quarantine(), key)


def test_files_scan_job_without_tenant_id_is_rejected_and_nothing_is_promoted(
    seeded: SeededTenant, redis_client: redis_lib.Redis
) -> None:
    broker = load("app.worker", "broker")
    key = quarantined_upload(seeded, PDF, "application/pdf")
    queues = {"ai"}
    with running_worker(broker, queues) as worker:
        with contextlib.suppress(Exception):
            broker.get_actor("files.scan").send(key=key, request_id=str(uuid4()))
        wait_idle(broker, worker, queues)
    assert not s3.exists(bucket_files(), key)
