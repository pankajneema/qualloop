"""A-92 / ADR-011 / INV-SEC-01, INV-SEC-02, INV-DOC-10: core.files.presign_download(caller, key) service.

No generic download endpoint exists in P01 (A-92); domain endpoints call this service. Real SeaweedFS."""

import contextlib
import threading
from typing import Any
from uuid import uuid4

import httpx
import pytest

from tests.factories import s3
from tests.factories.contract import load
from tests.factories.db import SeededTenant
from tests.factories.env import bucket_quarantine
from tests.integration.files.helpers import (
    JPEG,
    PDF,
    actor_for,
    disposition,
    expires_seconds,
    new_key,
)

pytestmark = pytest.mark.integration

FIFTEEN_MINUTES = 15 * 60


def presign(caller: Any, key: str, **kw: Any) -> str:
    return str(load("app.core.files", "presign_download")(caller, key, **kw))


def errors() -> Any:
    return load("app.core.errors")


def publish(tenant: SeededTenant, kind: str = "doc", ext: str = "pdf", data: bytes = PDF) -> str:
    """An object that passed the scan: present in the files bucket."""
    key = new_key(tenant.id, kind, ext)
    s3.put_files(key, data, "application/pdf" if ext == "pdf" else "image/jpeg")
    return key


def test_signed_url_expires_within_15_minutes(seeded: SeededTenant) -> None:
    """INV-SEC-02 (download side)."""
    assert seeded.quality
    url = presign(actor_for(seeded.quality), publish(seeded))
    assert 0 < expires_seconds(url) <= FIFTEEN_MINUTES


@pytest.mark.parametrize("requested", [3600, 86_400, 901])
def test_a_longer_expiry_than_15_minutes_cannot_be_requested(
    seeded: SeededTenant, requested: int
) -> None:
    assert seeded.quality
    key = publish(seeded)
    try:
        url = presign(actor_for(seeded.quality), key, expires_in=requested)
    except ValueError:
        return
    assert expires_seconds(url) <= FIFTEEN_MINUTES


def test_the_signed_url_downloads_the_object_and_then_actually_expires(
    seeded: SeededTenant,
) -> None:
    """Section 21.2 'signed file URLs expire': a 1-second URL works now and is refused by the store after."""
    assert seeded.quality
    key = publish(seeded)
    url = presign(actor_for(seeded.quality), key, expires_in=1)
    assert httpx.get(url, timeout=20).content == PDF
    threading.Event().wait(2.5)
    assert httpx.get(url, timeout=20).status_code in (400, 403)


def test_default_signed_url_works_for_the_owner_tenant_user(seeded: SeededTenant) -> None:
    assert seeded.quality
    resp = httpx.get(presign(actor_for(seeded.quality), publish(seeded)), timeout=20)
    assert resp.status_code == 200 and resp.content == PDF


def test_tenant_a_cannot_get_signed_url_for_tenant_b_file(
    seeded_pair: tuple[SeededTenant, SeededTenant],
) -> None:
    a, b = seeded_pair
    assert a.admin and a.quality
    foreign_key = publish(b)  # the object exists and is clean: only the tenant prefix stops access
    for user in (a.admin, a.quality):
        with pytest.raises(errors().NotFound) as excinfo:
            presign(actor_for(user), foreign_key)
        assert excinfo.value.status == 404, "never 403: the key's existence is not revealed"


def test_foreign_tenant_key_and_missing_key_are_indistinguishable(
    seeded_pair: tuple[SeededTenant, SeededTenant],
) -> None:
    a, b = seeded_pair
    assert a.quality
    caller = actor_for(a.quality)
    with pytest.raises(errors().NotFound) as foreign:
        presign(caller, publish(b))
    with pytest.raises(errors().NotFound) as missing:
        presign(caller, new_key(a.id))
    assert (foreign.value.status, foreign.value.code) == (missing.value.status, missing.value.code)
    assert str(foreign.value.detail) == str(missing.value.detail)


@pytest.mark.parametrize(
    "template",
    [
        "t/{me}/../{other}/doc/{o}/x.pdf",
        "/t/{other}/doc/{o}/x.pdf",
        "{other}/doc/{o}/x.pdf",
        "t/{other}/doc/{o}/x.pdf",
    ],
)
def test_traversal_and_malformed_keys_are_not_found(
    seeded_pair: tuple[SeededTenant, SeededTenant], template: str
) -> None:
    a, b = seeded_pair
    assert a.quality
    key = template.format(me=a.id, other=b.id, o=uuid4())
    with pytest.raises(errors().NotFound):
        presign(actor_for(a.quality), key)


def test_unscanned_file_not_downloadable(seeded: SeededTenant) -> None:
    """INV-DOC-10: an object that only exists in quarantine (scan not finished, or failed) is never served."""
    assert seeded.admin
    key = new_key(seeded.id)
    s3.put_quarantine(key, PDF, "application/pdf")
    assert s3.exists(bucket_quarantine(), key)
    with pytest.raises(errors().NotFound):
        presign(actor_for(seeded.admin), key)


@pytest.mark.parametrize(
    ("kind", "ext", "viewer_allowed"),
    [
        ("doc", "pdf", False),  # A-70: no original-file download for Viewer
        ("evidence", "pdf", False),
        ("import", "csv", False),
        ("export", "xlsx", False),  # A-70: no Excel export for Viewer
        ("ncr", "jpg", True),  # photos inline allowed
        ("report", "pdf", True),  # generated reports are readable by Q and V (API.md 5)
    ],
)
def test_unauthorised_user_cannot_get_signed_url_viewer_matrix(
    seeded: SeededTenant, kind: str, ext: str, viewer_allowed: bool
) -> None:
    assert seeded.viewer and seeded.quality
    key = publish(seeded, kind, ext, JPEG if ext == "jpg" else PDF)
    presign(actor_for(seeded.quality), key)  # quality always may
    if viewer_allowed:
        presign(actor_for(seeded.viewer), key)
    else:
        with pytest.raises(errors().Forbidden) as excinfo:
            presign(actor_for(seeded.viewer), key)
        assert excinfo.value.status == 403


def test_unauthorised_user_cannot_get_signed_url(seeded: SeededTenant) -> None:
    """INV-SEC-02: no caller, a supplier session or an AI actor never gets a URL for an internal file."""
    assert seeded.quality
    key = publish(seeded)
    with pytest.raises(errors().Unauthenticated):
        presign(None, key)
    for kind in ("supplier_session", "ai"):
        with pytest.raises(errors().Forbidden):
            presign(actor_for(seeded.quality, kind), key)


def test_documents_download_as_attachment_and_photos_inline(seeded: SeededTenant) -> None:
    assert seeded.quality
    caller = actor_for(seeded.quality)
    doc_url = presign(caller, publish(seeded, "doc", "pdf"))
    photo_url = presign(caller, publish(seeded, "ncr", "jpg", JPEG))
    assert disposition(doc_url).startswith("attachment")
    assert disposition(photo_url).startswith("inline")
    assert "attachment" in httpx.get(doc_url, timeout=20).headers.get("content-disposition", "")


def test_the_signed_url_points_at_the_files_bucket_never_quarantine(seeded: SeededTenant) -> None:
    assert seeded.quality
    url = presign(actor_for(seeded.quality), publish(seeded))
    assert bucket_quarantine() not in url


def test_presign_download_is_read_only_and_leaves_the_object_in_place(seeded: SeededTenant) -> None:
    assert seeded.quality
    key = publish(seeded)
    presign(actor_for(seeded.quality), key)
    with contextlib.suppress(Exception):
        presign(actor_for(seeded.quality), key)
    assert (
        s3.get(load("app.core.files.storage").__dict__.get("BUCKET_FILES", "qualloop-files"), key)
        == PDF
    )
