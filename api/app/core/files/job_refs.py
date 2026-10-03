"""Job identities of the file service (safe for the HTTP layer to import; implementations are in `jobs.py`)."""

from app.core.jobs import JobRef

SCAN_FILE = JobRef("files.scan", "ai")
