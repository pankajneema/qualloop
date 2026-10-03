"""Shared helpers for file-service tests."""

from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import UUID, uuid4

from tests.factories.contract import load
from tests.factories.db import SeededUser

PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"
PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"


def eicar() -> bytes:
    """The standard antivirus test string, assembled at runtime so no scanner flags this repository."""
    return b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$" + b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


def actor_for(user: SeededUser, kind: str = "user") -> Any:
    return load("app.core.permissions", "Actor")(
        type=kind,
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
        can_approve=user.can_approve,
        plant_ids=user.plant_ids,
    )


def new_key(tenant: UUID, kind: str = "doc", ext: str = "pdf") -> str:
    return str(load("app.core.files.storage", "build_key")(tenant, kind, uuid4(), ext))


def query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(url).query)


def expires_seconds(url: str) -> int:
    values = query(url).get("X-Amz-Expires") or query(url).get("x-amz-expires")
    assert values, f"not a SigV4 presigned URL: {url}"
    return int(values[0])


def disposition(url: str) -> str:
    values = query(url).get("response-content-disposition", [""])
    return unquote(values[0])
