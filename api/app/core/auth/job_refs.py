"""Job identities of the auth module (safe for the HTTP layer to import; the implementations are in `jobs.py`)."""

from app.core.jobs import JobRef

SEND_PASSWORD_RESET = JobRef("auth.send_password_reset", "notifications")
