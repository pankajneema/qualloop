"""File keys, upload validation and content sniffing (ADR-011).

Key layout: `t/{tenant_id}/{kind}/{object_id}/{uuid7}.{ext}`. Every key is built here and every key coming from outside
is checked against the caller's tenant prefix here, so a key of another tenant is indistinguishable from a missing one
(404, never 403).
"""

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from uuid import UUID

import filetype
from botocore.config import Config

from app.core.config import get_settings
from app.core.errors import (
    NotFound,
    PayloadTooLarge,
    UnsupportedMediaType,
    ValidationFailed,
    field_error,
)
from app.core.ids import new_id

KINDS = ("ncr", "doc", "evidence", "import", "report", "export")
EXTENSIONS = ("pdf", "jpg", "png", "csv", "xlsx")

# SPEC-GAP: A-97 - blueprint 20.2 says "<= 20 MB" without saying MB (10^6) or MiB (2^20): the smaller one is used.
MAX_UPLOAD_BYTES = 20_000_000
MAX_PRESIGN_SECONDS = 15 * 60  # blueprint 21.1: signed URLs expire within 15 minutes

PDF = "application/pdf"
JPEG = "image/jpeg"
PNG = "image/png"
CSV = "text/csv"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

_EXTENSION_OF_TYPE = {PDF: "pdf", JPEG: "jpg", PNG: "png", CSV: "csv", XLSX: "xlsx"}

# Purposes a client may ask an upload URL for -> (key kind, allowed content types). `report` and `export` are produced
# by the server only and are deliberately absent.
PURPOSES: dict[str, tuple[str, frozenset[str]]] = {
    "ncr_photo": ("ncr", frozenset({JPEG, PNG})),
    "document": ("doc", frozenset({PDF, JPEG, PNG})),
    "evidence": ("evidence", frozenset({PDF, JPEG, PNG})),
    "import": ("import", frozenset({CSV, XLSX})),
}

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_KEY = re.compile(
    rf"^t/(?P<tenant>{_UUID})/(?P<kind>{'|'.join(KINDS)})/(?P<object>{_UUID})/(?P<file>{_UUID})\.(?P<ext>{'|'.join(EXTENSIONS)})$"
)


@dataclass(frozen=True)
class UploadSpec:
    kind: str
    ext: str
    content_type: str


def build_key(tenant_id: UUID, kind: str, object_id: UUID, ext: str) -> str:
    if kind not in KINDS:
        raise ValueError(f"unknown key kind {kind!r}; expected one of {KINDS}")
    if ext not in EXTENSIONS:
        raise ValueError(f"unexpected extension {ext!r}; expected one of {EXTENSIONS}")
    return f"t/{tenant_id}/{kind}/{object_id}/{new_id()}.{ext}"


def parse_key(key: str) -> re.Match[str] | None:
    return _KEY.fullmatch(key) if isinstance(key, str) else None


def assert_key_in_tenant(key: str, tenant_id: UUID) -> None:
    """`NotFound` unless `key` is a well-formed key under `t/{tenant_id}/` (traversal, case tricks and NULs all fail)."""
    match = parse_key(key)
    if match is None or match.group("tenant") != str(tenant_id):
        raise NotFound("We could not find that file.")


def key_kind(key: str) -> str:
    match = parse_key(key)
    if match is None:
        raise NotFound("We could not find that file.")
    return match.group("kind")


def validate_upload_request(purpose: str, content_type: str, size: int) -> UploadSpec:
    """Check an upload request and return the key kind and extension. 422 / 415 / 413 per API.md 1.4."""
    if purpose not in PURPOSES:
        raise ValidationFailed(
            "That upload purpose is not supported.",
            errors=[
                field_error(
                    "purpose", "unknown_purpose", f"Use one of: {', '.join(sorted(PURPOSES))}."
                )
            ],
        )
    if size <= 0:
        raise ValidationFailed(
            "The file is empty.",
            errors=[field_error("size", "invalid", "The file size must be above zero.")],
        )
    kind, allowed = PURPOSES[purpose]
    if content_type not in allowed:
        raise UnsupportedMediaType(
            "That file type is not accepted here.",
            errors=[
                field_error(
                    "content_type", "unsupported", f"Allowed: {', '.join(sorted(allowed))}."
                )
            ],
        )
    if size > MAX_UPLOAD_BYTES:
        raise PayloadTooLarge(
            "That file is larger than 20 MB.",
            errors=[field_error("size", "too_large", "Files can be up to 20 MB.")],
        )
    return UploadSpec(kind=kind, ext=_EXTENSION_OF_TYPE[content_type], content_type=content_type)


def sniff_content_type(data: bytes) -> str | None:
    """The MIME type named by the magic bytes (`filetype`), or None when there is no recognised signature."""
    guessed = filetype.guess(data)
    return str(guessed.mime) if guessed is not None else None


def _looks_like_text(data: bytes) -> bool:
    if not data or b"\x00" in data:
        return False
    try:
        data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return False
    return True


def declared_matches_content(declared: str, data: bytes) -> bool:
    """True iff the declared type agrees with the content: magic bytes for PDF/JPEG/PNG/XLSX, text for CSV."""
    sniffed = sniff_content_type(data)
    if declared == CSV:
        return sniffed is None and _looks_like_text(data)
    return sniffed is not None and sniffed == declared and declared in _EXTENSION_OF_TYPE


@lru_cache
def _client(endpoint: str, access_key: str, secret_key: str, region: str) -> Any:
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            connect_timeout=5,
            read_timeout=30,
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )


def s3_client() -> Any:
    """S3 client for server-side calls (get/put/copy/delete)."""
    s = get_settings()
    return _client(s.s3_endpoint_url, s.s3_access_key, s.s3_secret_key, s.s3_region)


def presign_client() -> Any:
    """S3 client whose host is the one browsers use, for presigned URLs (signing needs no network)."""
    s = get_settings()
    return _client(
        s.s3_public_endpoint_url or s.s3_endpoint_url, s.s3_access_key, s.s3_secret_key, s.s3_region
    )


def bucket_files() -> str:
    return get_settings().s3_bucket_files


def bucket_quarantine() -> str:
    return get_settings().s3_bucket_quarantine
