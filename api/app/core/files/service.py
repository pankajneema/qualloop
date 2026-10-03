"""Signed URLs (ADR-011, A-92). `presign_upload` serves `POST /files/upload-url`; `presign_download` is called by the
domain endpoints that own a file (documents P03, NCR photos P04, ...): there is no generic download endpoint in P01.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from botocore.exceptions import ClientError

from app.core.errors import Forbidden, NotFound, Unauthenticated
from app.core.files import storage
from app.core.ids import new_id
from app.core.permissions import ACTOR_USER, ROLE_VIEWER, Actor

# A-70: a Viewer may read NCR photos and generated reports, never the original documents, evidence or exports.
VIEWER_KINDS = frozenset({"ncr", "report"})
_NOT_FOUND = "We could not find that file."


@dataclass(frozen=True)
class PresignedUpload:
    key: str
    url: str
    expires_at: datetime


def presign_upload(
    tenant_id: UUID, spec: storage.UploadSpec, size: int, object_id: UUID | None = None
) -> PresignedUpload:
    """A 15-minute presigned PUT into the quarantine bucket. Content-Type and Content-Length are part of the signature."""
    key = storage.build_key(tenant_id, spec.kind, object_id or new_id(), spec.ext)
    url: str = storage.presign_client().generate_presigned_url(
        "put_object",
        Params={
            "Bucket": storage.bucket_quarantine(),
            "Key": key,
            "ContentType": spec.content_type,
            "ContentLength": size,
        },
        ExpiresIn=storage.MAX_PRESIGN_SECONDS,
        HttpMethod="PUT",
    )
    return PresignedUpload(
        key=key,
        url=url,
        expires_at=datetime.now(UTC) + timedelta(seconds=storage.MAX_PRESIGN_SECONDS),
    )


def _exists(bucket: str, key: str) -> bool:
    try:
        storage.s3_client().head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        status = str(exc.response.get("Error", {}).get("Code", ""))
        if status in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise
    return True


def in_quarantine(key: str) -> bool:
    """True while the uploaded object still waits in the quarantine bucket (not yet scanned and promoted)."""
    return _exists(storage.bucket_quarantine(), key)


def presign_download(caller: Actor | None, key: str, *, expires_in: int | None = None) -> str:
    """A presigned GET (at most 15 minutes) for a scanned file of the caller's tenant.

    Order of checks: caller, actor type, tenant prefix (another tenant's key is `NotFound`, the same answer as a missing
    object), viewer rights for the kind, then existence in the files bucket (an object still in quarantine does not
    exist for downloads: nothing unscanned is ever served)."""
    if caller is None:
        raise Unauthenticated("Sign in to continue.")
    if caller.type != ACTOR_USER:
        raise Forbidden("You do not have permission to do this.")
    if expires_in is not None and not 1 <= expires_in <= storage.MAX_PRESIGN_SECONDS:
        raise ValueError(f"expires_in must be between 1 and {storage.MAX_PRESIGN_SECONDS} seconds")
    storage.assert_key_in_tenant(key, caller.tenant_id)
    kind = storage.key_kind(key)
    if caller.role == ROLE_VIEWER and kind not in VIEWER_KINDS:
        raise Forbidden("You do not have permission to do this.")
    bucket = storage.bucket_files()
    if not _exists(bucket, key):
        raise NotFound(_NOT_FOUND)
    disposition = "inline" if kind == "ncr" else f'attachment; filename="{key.rsplit("/", 1)[-1]}"'
    url: str = storage.presign_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key, "ResponseContentDisposition": disposition},
        ExpiresIn=expires_in or storage.MAX_PRESIGN_SECONDS,
        HttpMethod="GET",
    )
    return url
