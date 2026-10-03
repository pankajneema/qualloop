"""ADR-011: key layout, tenant prefix check, upload validation, magic-byte sniffing (no network)."""

import io
import re
import zipfile
from typing import Any
from uuid import UUID, uuid4

import pytest

from tests.factories.contract import load
from tests.factories.env import MAX_UPLOAD_BYTES_CLEARLY_OK, MAX_UPLOAD_BYTES_CLEARLY_OVER

TENANT = UUID("0192a3b4-0000-7000-8000-00000000000a")
OTHER = UUID("0192a3b4-0000-7000-8000-00000000000b")
OBJECT = UUID("0192a3b4-0000-7000-8000-0000000000cc")

PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n"
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01"
PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"


def _make_xlsx() -> bytes:
    """A minimal but structurally real OOXML workbook (zip with [Content_Types].xml and xl/workbook.xml)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
        archive.writestr("xl/workbook.xml", '<?xml version="1.0"?><workbook/>')
    return buffer.getvalue()


XLSX = _make_xlsx()
EXE = b"MZ\x90\x00\x03\x00\x00\x00"


def storage() -> Any:
    return load("app.core.files.storage")


def errors() -> Any:
    return load("app.core.errors")


@pytest.mark.parametrize(
    ("kind", "ext"), [("ncr", "jpg"), ("doc", "pdf"), ("evidence", "png"), ("import", "xlsx")]
)
def test_build_key_follows_the_documented_layout(kind: str, ext: str) -> None:
    key = storage().build_key(TENANT, kind, OBJECT, ext)
    pattern = rf"^t/{TENANT}/{kind}/{OBJECT}/[0-9a-f]{{8}}-[0-9a-f]{{4}}-7[0-9a-f]{{3}}-[89ab][0-9a-f]{{3}}-[0-9a-f]{{12}}\.{ext}$"
    assert re.match(pattern, key), key


def test_build_key_is_unique_per_call() -> None:
    keys = {storage().build_key(TENANT, "doc", OBJECT, "pdf") for _ in range(20)}
    assert len(keys) == 20


@pytest.mark.parametrize("kind", ["", "photos", "../doc", "DOC", "t"])
def test_build_key_rejects_kinds_outside_the_allow_list(kind: str) -> None:
    with pytest.raises(ValueError, match="kind"):
        storage().build_key(TENANT, kind, OBJECT, "pdf")


@pytest.mark.parametrize("ext", ["", "exe", "pdf/../x", "PDF "])
def test_build_key_rejects_unexpected_extensions(ext: str) -> None:
    with pytest.raises(ValueError, match="extension"):
        storage().build_key(TENANT, "doc", OBJECT, ext)


def test_assert_key_in_tenant_accepts_own_prefix() -> None:
    key = storage().build_key(TENANT, "doc", OBJECT, "pdf")
    storage().assert_key_in_tenant(key, TENANT)


@pytest.mark.parametrize(
    "key_template",
    [
        "t/{other}/doc/{obj}/x.pdf",  # other tenant
        "t/{me}/../{other}/doc/{obj}/x.pdf",  # traversal
        "/t/{me}/doc/{obj}/x.pdf",  # absolute
        "T/{me}/doc/{obj}/x.pdf",  # wrong case prefix
        "{me}/doc/{obj}/x.pdf",  # missing t/
        "t/{me}",  # no object
        "t/{me}x/doc/{obj}/x.pdf",  # prefix confusion
        "t/{me}/doc/{obj}/x.pdf\x00.exe",  # NUL injection
        "",
    ],
)
def test_assert_key_in_tenant_rejects_foreign_or_malformed_keys_with_not_found(
    key_template: str,
) -> None:
    key = key_template.format(me=TENANT, other=OTHER, obj=OBJECT)
    with pytest.raises(errors().NotFound):
        storage().assert_key_in_tenant(key, TENANT)


def test_validate_upload_returns_kind_and_extension_for_a_pdf_document() -> None:
    spec = storage().validate_upload_request("document", "application/pdf", 12_345)
    assert (spec.kind, spec.ext) == ("doc", "pdf")


@pytest.mark.parametrize(
    ("purpose", "content_type", "kind", "ext"),
    [
        ("ncr_photo", "image/jpeg", "ncr", "jpg"),
        ("ncr_photo", "image/png", "ncr", "png"),
        ("document", "image/jpeg", "doc", "jpg"),
        ("document", "image/png", "doc", "png"),
        ("evidence", "application/pdf", "evidence", "pdf"),
        ("import", "text/csv", "import", "csv"),
        (
            "import",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "import",
            "xlsx",
        ),
    ],
)
def test_validate_upload_maps_purpose_and_type_to_key_kind_and_extension(
    purpose: str, content_type: str, kind: str, ext: str
) -> None:
    spec = storage().validate_upload_request(purpose, content_type, 1000)
    assert (spec.kind, spec.ext) == (kind, ext)


def test_validate_upload_accepts_a_file_just_under_twenty_megabytes() -> None:
    storage().validate_upload_request("document", "application/pdf", MAX_UPLOAD_BYTES_CLEARLY_OK)


def test_validate_upload_rejects_over_20_mb_with_413() -> None:
    with pytest.raises(errors().PayloadTooLarge) as excinfo:
        storage().validate_upload_request(
            "document", "application/pdf", MAX_UPLOAD_BYTES_CLEARLY_OVER
        )
    assert excinfo.value.status == 413


@pytest.mark.parametrize(
    ("purpose", "content_type"),
    [
        ("document", "application/x-msdownload"),
        ("document", "text/html"),
        ("document", "image/gif"),
        ("document", "application/zip"),
        ("document", "image/svg+xml"),
        ("ncr_photo", "application/pdf"),
        ("import", "application/pdf"),
        ("import", "image/png"),
        ("document", ""),
    ],
)
def test_validate_upload_rejects_disallowed_content_types_with_415(
    purpose: str, content_type: str
) -> None:
    with pytest.raises(errors().UnsupportedMediaType) as excinfo:
        storage().validate_upload_request(purpose, content_type, 1000)
    assert excinfo.value.status == 415


@pytest.mark.parametrize("purpose", ["", "report", "export", "avatar", "../doc"])
def test_validate_upload_rejects_unknown_or_server_only_purposes(purpose: str) -> None:
    with pytest.raises(errors().ValidationFailed):
        storage().validate_upload_request(purpose, "application/pdf", 1000)


@pytest.mark.parametrize("size", [0, -1])
def test_validate_upload_rejects_non_positive_sizes(size: int) -> None:
    with pytest.raises(errors().ValidationFailed):
        storage().validate_upload_request("document", "application/pdf", size)


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (PDF, "application/pdf"),
        (JPEG, "image/jpeg"),
        (PNG, "image/png"),
        (XLSX, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        (b"", None),
        (b"plain text, no magic", None),
    ],
)
def test_sniff_content_type_reads_magic_bytes(data: bytes, expected: str | None) -> None:
    assert storage().sniff_content_type(data) == expected


def test_sniff_never_reports_an_executable_as_an_allowed_type() -> None:
    allowed = {
        "application/pdf",
        "image/jpeg",
        "image/png",
        "text/csv",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
    assert storage().sniff_content_type(EXE) not in allowed


def test_declared_type_must_agree_with_magic_bytes() -> None:
    matches = storage().declared_matches_content
    assert matches("application/pdf", PDF) is True
    assert matches("image/jpeg", JPEG) is True
    assert matches("application/pdf", JPEG) is False  # JPEG labelled as PDF
    assert matches("image/png", EXE) is False
    assert matches("image/jpeg", b"") is False


def test_random_tenant_prefix_never_matches_another_tenant() -> None:
    key = storage().build_key(TENANT, "doc", OBJECT, "pdf")
    with pytest.raises(errors().NotFound):
        storage().assert_key_in_tenant(key, uuid4())
