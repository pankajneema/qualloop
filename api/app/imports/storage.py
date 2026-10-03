"""Object-storage side of a batch: the source pointer + header (`meta.json`) and the pre-confirm preview.

DATA_MODEL 7 has no column for the uploaded file's key or its header, and ARCHITECTURE 8.3 keeps the preview in object
storage, so both live next to each other under the batch's own prefix in the private files bucket. They are never
served through a presigned URL (the layout is deliberately not a `storage.build_key` key).
SPEC-GAP: A-121
"""

import json
from typing import Any
from uuid import UUID

from botocore.exceptions import ClientError

from app.core.errors import NotFound
from app.core.files import storage

_MISSING = {"404", "NoSuchKey", "NotFound"}


def _prefix(tenant_id: UUID, batch_id: UUID) -> str:
    return f"t/{tenant_id}/import/{batch_id}"


def meta_key(tenant_id: UUID, batch_id: UUID) -> str:
    return f"{_prefix(tenant_id, batch_id)}/meta.json"


def preview_key(tenant_id: UUID, batch_id: UUID) -> str:
    return f"{_prefix(tenant_id, batch_id)}/preview.json"


def put_json(key: str, payload: Any) -> None:
    storage.s3_client().put_object(
        Bucket=storage.bucket_files(),
        Key=key,
        Body=json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode(),
        ContentType="application/json",
    )


def get_object(key: str) -> bytes:
    try:
        body: bytes = (
            storage.s3_client().get_object(Bucket=storage.bucket_files(), Key=key)["Body"].read()
        )
    except ClientError as exc:
        if str(exc.response.get("Error", {}).get("Code", "")) in _MISSING:
            raise NotFound("We could not find that file.") from exc
        raise
    return body


def get_json(key: str) -> Any:
    return json.loads(get_object(key))
