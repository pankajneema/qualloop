"""`POST /files/upload-url` (API.md 5): a presigned PUT into quarantine. Not a state change, so not a registered command,
but Quality/Admin only and CSRF-protected like every cookie-authenticated POST."""

from datetime import datetime
from typing import Annotated

from fastapi import Depends
from pydantic import BaseModel, ConfigDict, StrictInt

from app.core.auth.deps import require
from app.core.files import presign_upload, storage
from app.core.permissions import QUALITY, Actor
from app.core.routing import api_router

router = api_router("/files", tags=["files"])


class UploadUrlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purpose: str
    content_type: str
    size: StrictInt


class UploadUrlResponse(BaseModel):
    key: str
    url: str
    expires_at: datetime


@router.post("/upload-url", response_model=UploadUrlResponse)
def upload_url(
    body: UploadUrlRequest, actor: Annotated[Actor, Depends(require(QUALITY, command=False))]
) -> UploadUrlResponse:
    spec = storage.validate_upload_request(body.purpose, body.content_type, body.size)
    upload = presign_upload(actor.tenant_id, spec, body.size)
    return UploadUrlResponse(key=upload.key, url=upload.url, expires_at=upload.expires_at)
