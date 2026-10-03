"""S3 (SeaweedFS, ADR-020) helpers. boto3 is imported lazily; it is a P01 dependency."""

from typing import Any

from tests.factories.contract import load
from tests.factories.env import (
    bucket_files,
    bucket_quarantine,
    s3_access_key,
    s3_endpoint,
    s3_secret_key,
)


def client() -> Any:
    boto3 = load("boto3")
    config = load("botocore.config", "Config")
    return boto3.client(
        "s3",
        endpoint_url=s3_endpoint(),
        aws_access_key_id=s3_access_key(),
        aws_secret_access_key=s3_secret_key(),
        region_name="us-east-1",
        config=config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def put(bucket: str, key: str, data: bytes, content_type: str) -> None:
    client().put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)


def put_quarantine(key: str, data: bytes, content_type: str) -> None:
    put(bucket_quarantine(), key, data, content_type)


def put_files(key: str, data: bytes, content_type: str) -> None:
    put(bucket_files(), key, data, content_type)


def exists(bucket: str, key: str) -> bool:
    c = client()
    resp = c.list_objects_v2(Bucket=bucket, Prefix=key)
    return any(o["Key"] == key for o in resp.get("Contents", []))


def get(bucket: str, key: str) -> bytes:
    body: bytes = client().get_object(Bucket=bucket, Key=key)["Body"].read()
    return body
