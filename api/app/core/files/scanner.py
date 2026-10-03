"""Upload scanning (ADR-011 items 3-4): ClamAV INSTREAM, magic-byte check, SHA-256, promote quarantine -> files.

Fails closed: if ClamAV cannot be reached the scan raises (the job retries) and nothing is promoted; an infected file or
one whose content disagrees with its declared type stays in quarantine (7-day lifecycle) and is never downloadable.
"""

import hashlib
import socket
import struct
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import structlog
from botocore.exceptions import ClientError

from app.core.config import get_settings
from app.core.errors import NotFound
from app.core.files import storage

log = structlog.get_logger("files.scan")

STATUS_AVAILABLE = "available"
STATUS_QUARANTINED = "quarantined"
REASON_INFECTED = "infected"
REASON_MISMATCH = "content_type_mismatch"
REASON_TOO_LARGE = "too_large"

_CHUNK = 64 * 1024
_CONNECT_TIMEOUT = 5.0
_READ_TIMEOUT = 120.0
_MISSING = {"404", "NoSuchKey", "NotFound"}


class ScannerUnavailable(RuntimeError):
    """ClamAV could not be reached or answered with an error: the file has NOT been scanned."""


@dataclass(frozen=True)
class ScanVerdict:
    infected: bool
    signature: str | None


@dataclass(frozen=True)
class ScanResult:
    status: str  # `available` or `quarantined`
    reason: str | None = None  # `infected`, `content_type_mismatch` or `too_large` when quarantined
    sha256: str | None = None  # lowercase hex, only when available


def scan_bytes(data: bytes) -> ScanVerdict:
    """Scan `data` with clamd over the INSTREAM protocol (length-prefixed chunks, zero-length terminator)."""
    settings = get_settings()
    try:
        with socket.create_connection(
            (settings.clamav_host, settings.clamav_port), timeout=_CONNECT_TIMEOUT
        ) as sock:
            sock.settimeout(_READ_TIMEOUT)
            sock.sendall(b"zINSTREAM\0")
            for start in range(0, len(data), _CHUNK):
                chunk = data[start : start + _CHUNK]
                sock.sendall(struct.pack("!I", len(chunk)) + chunk)
            sock.sendall(struct.pack("!I", 0))
            reply = b""
            while not reply.endswith(b"\0") and (part := sock.recv(4096)):
                reply += part
    except OSError as exc:
        raise ScannerUnavailable("ClamAV is not reachable") from exc
    text = reply.rstrip(b"\0").decode("utf-8", "replace").strip()
    if text.endswith("OK"):
        return ScanVerdict(infected=False, signature=None)
    if text.endswith("FOUND"):
        signature = text.removeprefix("stream:").removesuffix("FOUND").strip()
        return ScanVerdict(infected=True, signature=signature or "unknown")
    raise ScannerUnavailable("ClamAV did not give a verdict")


def _is_missing(exc: ClientError) -> bool:
    return str(exc.response.get("Error", {}).get("Code", "")) in _MISSING


def scan_quarantined(tenant_id: UUID, key: str) -> ScanResult:
    """Scan one uploaded object and promote it. Idempotent: a redelivered message finds the promoted copy."""
    storage.assert_key_in_tenant(key, tenant_id)
    s3: Any = storage.s3_client()
    try:
        head = s3.head_object(Bucket=storage.bucket_quarantine(), Key=key)
    except ClientError as exc:
        if not _is_missing(exc):
            raise
        return _already_promoted(s3, key)
    # SPEC-GAP: A-97 - a presigned PUT is bounded by what the client declares, not by what it sends: check the real size
    # from the metadata before downloading anything. Final verdict (no raise, so no retry); the object stays in quarantine.
    if int(head.get("ContentLength", 0)) > storage.MAX_UPLOAD_BYTES:
        log.warning("upload_quarantined", reason=REASON_TOO_LARGE, tenant_id=str(tenant_id))
        return ScanResult(STATUS_QUARANTINED, REASON_TOO_LARGE)
    declared = str(head.get("ContentType", ""))
    data: bytes = s3.get_object(Bucket=storage.bucket_quarantine(), Key=key)["Body"].read()

    verdict = scan_bytes(data)  # raises when ClamAV is unavailable: nothing is promoted
    if verdict.infected:
        log.warning(
            "upload_quarantined",
            reason=REASON_INFECTED,
            tenant_id=str(tenant_id),
            signature=verdict.signature,
        )
        return ScanResult(STATUS_QUARANTINED, REASON_INFECTED)
    if not storage.declared_matches_content(declared, data):
        log.warning("upload_quarantined", reason=REASON_MISMATCH, tenant_id=str(tenant_id))
        return ScanResult(STATUS_QUARANTINED, REASON_MISMATCH)

    digest = hashlib.sha256(data).hexdigest()
    s3.put_object(Bucket=storage.bucket_files(), Key=key, Body=data, ContentType=declared)
    s3.delete_object(Bucket=storage.bucket_quarantine(), Key=key)
    return ScanResult(STATUS_AVAILABLE, sha256=digest)


def _already_promoted(s3: Any, key: str) -> ScanResult:
    try:
        data: bytes = s3.get_object(Bucket=storage.bucket_files(), Key=key)["Body"].read()
    except ClientError as exc:
        if _is_missing(exc):
            raise NotFound("We could not find that file.") from exc
        raise
    return ScanResult(STATUS_AVAILABLE, sha256=hashlib.sha256(data).hexdigest())
