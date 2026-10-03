"""Environment constants shared by integration tests (all local stand-ins, ADR-020, A-91)."""

import os
from urllib.parse import urlsplit, urlunsplit

APP_ROLE = "qualloop_app"
OWNER_ROLE = "qualloop_owner"
API = "/api/v1"
TEST_REDIS_DB = 15  # isolates tests from the dev worker/dispatcher that use db 0

# Seeded password for factory users; KNOWN_HASH is its argon2id hash (library defaults), so factories need
# no hashing dependency and API tests prove the app's own verifier accepts a standard argon2id hash.
PASSWORD = "Tr0ub4dor&3-qualloop"
KNOWN_HASH = "$argon2id$v=19$m=65536,t=3,p=4$IgmpEAhod7v7xlYz9PSc7Q$nBO3ECFcgp04BnnRZBAQt+KMA9tn3uyDjf9+75eaJS0"

MAX_UPLOAD_BYTES_CLEARLY_OK = 19_999_999
MAX_UPLOAD_BYTES_CLEARLY_OVER = 20 * 1024 * 1024 + 1


def owner_url() -> str:
    """Migration/owner role URL for the TEST database, read straight from the environment.

    The runtime `Settings` holds no owner credential (P01 contract, item 8), so tests never take it from there."""
    return os.environ.get(
        "QL_TEST_DATABASE_URL_OWNER",
        "postgresql+psycopg://qualloop_owner:qualloop_owner@localhost:5432/qualloop_test",
    )


def with_redis_db(url: str, db: int = TEST_REDIS_DB) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{db}", parts.query, parts.fragment))


def origin() -> str:
    """Allowed Origin for CSRF (QL_PUBLIC_BASE_URL)."""
    return os.environ.get("QL_PUBLIC_BASE_URL", "http://localhost:3000").rstrip("/")


def s3_endpoint() -> str:
    return os.environ.get("QL_S3_ENDPOINT_URL", "http://localhost:8333")


def s3_access_key() -> str:
    return os.environ.get("QL_S3_ACCESS_KEY", "qualloop-dev")


def s3_secret_key() -> str:
    return os.environ.get("QL_S3_SECRET_KEY", "change-me-local-only")


def bucket_files() -> str:
    return os.environ.get("QL_S3_BUCKET_FILES", "qualloop-files")


def bucket_quarantine() -> str:
    return os.environ.get("QL_S3_BUCKET_QUARANTINE", "qualloop-quarantine")


def mailpit_url() -> str:
    return os.environ.get("QL_MAILPIT_URL", "http://localhost:8025")
