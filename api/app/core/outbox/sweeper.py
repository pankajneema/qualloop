"""`core.sweep_pending` (ADR-006 item 5): re-enqueue stale pending domain work so that losing Redis loses no work.

P01 has no pending domain work yet (messages `queued`, documents `pending_scan` and import batches arrive in later
phases, each registering its own sweep); this is the stub the scheduler fans out every 5 minutes.
"""

from app.core.jobs import JobRef, job

SWEEP_PENDING = JobRef("core.sweep_pending", "scheduled")


@job(SWEEP_PENDING)
def sweep_pending(tenant_id: str | None = None) -> int:
    """Re-enqueue stale pending work of one tenant; returns how many items were re-enqueued."""
    return 0
