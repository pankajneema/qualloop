"""Environment constants shared by integration tests (all local stand-ins, ADR-020, A-91)."""

import os
from urllib.parse import urlsplit, urlunsplit

APP_ROLE = "qualloop_app"
OWNER_ROLE = "qualloop_owner"
API = "/api/v1"
REDIS_WORKER_USER = (
    "qualloop_worker"  # ADR-008 amendment (A-122): Dramatiq consumers only; the app user minus KEYS
)
REDIS_WORKER_DEFAULT_PASSWORD = "qualloop-redis-worker-dev-only"
TEST_REDIS_DB = 15  # isolates tests from the dev worker/dispatcher that use db 0

# Seeded password for factory users; KNOWN_HASH is its argon2id hash (library defaults), so factories need
# no hashing dependency and API tests prove the app's own verifier accepts a standard argon2id hash.
PASSWORD = "Tr0ub4dor&3-qualloop"
KNOWN_HASH = "$argon2id$v=19$m=65536,t=3,p=4$IgmpEAhod7v7xlYz9PSc7Q$nBO3ECFcgp04BnnRZBAQt+KMA9tn3uyDjf9+75eaJS0"

MAX_UPLOAD_BYTES_CLEARLY_OK = 19_999_999
MAX_UPLOAD_BYTES_CLEARLY_OVER = 20 * 1024 * 1024 + 1


def pin_loopback(url: str) -> str:
    """Rewrite a `localhost` host to the IPv4 literal `127.0.0.1`.

    Why: `localhost` resolves to `::1` first, but the dev stack publishes its ports on IPv4 only (Colima/Lima forwards
    with `ssh -L` on 127.0.0.1). Connecting to a port nobody listens on can succeed as a TCP SELF-CONNECT when the
    kernel picks the same number as the ephemeral source port (host ports such as 55432 / 56379 sit inside
    49152-65535, roughly 1 connect in 16k). The client then reads its own commands back; redis-py ignores the replies
    to HELLO/CLIENT SETINFO, so the first checked reply (`SELECT 15`) fails with "Invalid Database". With a listener
    on 127.0.0.1 a self-connect cannot happen."""
    parts = urlsplit(url)
    if (parts.hostname or "").lower() != "localhost":
        return url
    userinfo, _, hostport = parts.netloc.rpartition("@")
    _host, sep, port = hostport.partition(":")
    netloc = f"{userinfo}@" if userinfo else ""
    return urlunsplit(
        (parts.scheme, f"{netloc}127.0.0.1{sep}{port}", parts.path, parts.query, parts.fragment)
    )


def redis_url_as(url: str, user: str, password: str) -> str:
    """The same Redis host/port/db with other ACL credentials."""
    parts = urlsplit(url)
    hostport = parts.netloc.rpartition("@")[2]
    return urlunsplit(
        (parts.scheme, f"{user}:{password}@{hostport}", parts.path, parts.query, parts.fragment)
    )


def worker_redis_url(app_url: str | None = None) -> str:
    """URL the Dramatiq consumers use in tests: `QL_REDIS_WORKER_URL`, else the app URL with the worker ACL user and
    `QL_REDIS_WORKER_PASSWORD`. Always pinned to the IPv4 loopback literal and Redis db 15."""
    explicit = os.environ.get("QL_REDIS_WORKER_URL")
    if explicit:
        return with_redis_db(pin_loopback(explicit))
    base = app_url or os.environ.get("QL_REDIS_URL", "redis://localhost:6379/0")
    password = os.environ.get("QL_REDIS_WORKER_PASSWORD", REDIS_WORKER_DEFAULT_PASSWORD)
    return with_redis_db(pin_loopback(redis_url_as(base, REDIS_WORKER_USER, password)))


def owner_url() -> str:
    """Migration/owner role URL for the TEST database, read straight from the environment.

    The runtime `Settings` holds no owner credential (P01 contract, item 8), so tests never take it from there."""
    return pin_loopback(
        os.environ.get(
            "QL_TEST_DATABASE_URL_OWNER",
            "postgresql+psycopg://qualloop_owner:qualloop_owner@localhost:5432/qualloop_test",
        )
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
