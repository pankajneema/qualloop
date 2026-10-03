"""File jobs (queue `ai`, ADR-011 item 3): `files.scan`. Runs in the worker; the register command of the owning module
(P03 documents, P04 NCR photos) enqueues it and marks its row `pending_scan` until the result is known."""

from uuid import UUID

import structlog

from app.core.files.job_refs import SCAN_FILE
from app.core.files.scanner import STATUS_QUARANTINED, scan_quarantined
from app.core.jobs import job

log = structlog.get_logger("files.jobs")


@job(SCAN_FILE)
def scan_file(tenant_id: str, key: str) -> None:
    result = scan_quarantined(UUID(tenant_id), key)
    if result.status == STATUS_QUARANTINED:
        log.warning("file_quarantined", tenant_id=tenant_id, reason=result.reason)
